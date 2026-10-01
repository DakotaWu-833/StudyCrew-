"""Profile media and sign-in email changes, shared by HTML and REST views."""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import timedelta
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from accounts.models import EmailOTPChallenge, PendingEmailChange, Profile, User
from accounts.services import normalise_email


logger = logging.getLogger(__name__)
MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000
EMAIL_CHANGE_COOLDOWN = timedelta(seconds=60)


class AvatarUploadUnavailable(Exception):
    pass


class EmailChangeUnavailable(Exception):
    pass


def save_profile_avatar(profile: Profile, upload) -> Profile:
    """Decode and re-encode a bounded image; never serve the original upload."""

    if not upload or upload.size > MAX_AVATAR_BYTES:
        raise AvatarUploadUnavailable("Choose a JPG, PNG or WebP image under 2 MB.")
    try:
        upload.seek(0)
        with Image.open(upload) as original:
            if original.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported image format")
            if original.width * original.height > MAX_AVATAR_PIXELS:
                raise ValueError("Image dimensions are too large")
            original.load()
            cropped = ImageOps.fit(
                ImageOps.exif_transpose(original),
                (512, 512),
                method=Image.Resampling.LANCZOS,
            ).convert("RGBA")
            flattened = Image.new("RGB", cropped.size, "white")
            flattened.paste(cropped, mask=cropped.getchannel("A"))
            buffer = BytesIO()
            flattened.save(buffer, format="JPEG", quality=86, optimize=True)
    except (OSError, ValueError, Image.DecompressionBombError, UnidentifiedImageError) as exc:
        raise AvatarUploadUnavailable("Choose a valid JPG, PNG or WebP image under 2 MB.") from exc

    with transaction.atomic():
        saved = Profile.objects.select_for_update().get(pk=profile.pk)
        old_name = saved.avatar.name
        saved.avatar.save(f"{uuid.uuid4().hex}.jpg", ContentFile(buffer.getvalue()), save=False)
        saved.save(update_fields=("avatar", "updated_at"))
        if old_name and old_name != saved.avatar.name:
            def remove_previous_avatar():
                try:
                    saved.avatar.storage.delete(old_name)
                except OSError:
                    logger.exception("Previous avatar cleanup failed for user %s", saved.user_id)

            transaction.on_commit(remove_previous_avatar)
    return saved


def _code_digest(change_id: uuid.UUID, code: str) -> str:
    return salted_hmac(
        "accounts.email-change",
        f"{change_id}:{code}",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def start_email_change(*, user: User, new_email: str, current_password: str) -> PendingEmailChange:
    """Require the current password and send a one-use code to the new address."""

    new_email = normalise_email(new_email)
    ttl_minutes = max(1, (settings.OTP_TTL_SECONDS + 59) // 60)
    try:
        validate_email(new_email)
    except Exception as exc:
        raise EmailChangeUnavailable("Enter a valid new email address.") from exc

    now = timezone.now()
    with transaction.atomic():
        current = User.objects.select_for_update().get(pk=user.pk)
        if (
            not current.is_active
            or not current.check_password(current_password)
            or new_email == current.email
            or User.objects.filter(email__iexact=new_email).exclude(pk=current.pk).exists()
        ):
            raise EmailChangeUnavailable("Check the new address and your current password.")

        change = PendingEmailChange.objects.select_for_update().filter(user=current).first()
        if change and change.last_sent_at + EMAIL_CHANGE_COOLDOWN > now:
            raise EmailChangeUnavailable("Wait one minute before requesting another code.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        if change is None:
            change = PendingEmailChange(user=current)
        change.new_email = new_email
        change.code_hash = _code_digest(change.id, code)
        change.expires_at = now + timedelta(seconds=settings.OTP_TTL_SECONDS)
        change.attempt_count = 0
        change.max_attempts = settings.OTP_MAX_ATTEMPTS
        change.last_sent_at = now
        change.save()

    try:
        sent = send_mail(
            subject="Verify your new StudyCrew email",
            message=(
                f"Your StudyCrew email-change code is {code}.\n\n"
                "Enter this code in your open StudyCrew profile to confirm the new address. "
                f"It expires in {ttl_minutes} minute(s). If you did not request this, ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[new_email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Email-change code delivery failed for request %s", change.id)
        sent = 0
    if sent != 1:
        PendingEmailChange.objects.filter(pk=change.pk, code_hash=change.code_hash).delete()
        raise EmailChangeUnavailable("The verification email could not be sent. Try again later.")
    return change


def confirm_email_change(*, user: User, change_id: str, code: str) -> str:
    """Consume the code atomically and switch the sign-in address once."""

    try:
        parsed_id = uuid.UUID(str(change_id))
    except (TypeError, ValueError) as exc:
        raise EmailChangeUnavailable("The code is invalid or has expired.") from exc
    if not re.fullmatch(r"\d{6}", code):
        raise EmailChangeUnavailable("The code is invalid or has expired.")

    old_email = ""
    new_email = ""
    now = timezone.now()
    try:
        with transaction.atomic():
            current = User.objects.select_for_update().get(pk=user.pk)
            change = PendingEmailChange.objects.select_for_update().filter(pk=parsed_id, user=current).first()
            if change is None:
                pass
            elif change.expires_at <= now or change.attempt_count >= change.max_attempts:
                change.delete()
            elif not constant_time_compare(change.code_hash, _code_digest(change.id, code)):
                change.attempt_count += 1
                if change.attempt_count >= change.max_attempts:
                    change.delete()
                else:
                    change.save(update_fields=("attempt_count",))
            elif User.objects.filter(email__iexact=change.new_email).exclude(pk=current.pk).exists():
                change.delete()
            else:
                old_email = current.email
                new_email = change.new_email
                current.email = new_email
                current.email_verified_at = now
                current.save(update_fields=("email", "email_verified_at", "updated_at"))
                EmailOTPChallenge.objects.filter(
                    user=current,
                    purpose=EmailOTPChallenge.Purpose.LOGIN,
                    consumed_at__isnull=True,
                ).update(consumed_at=now)
                change.delete()
    except IntegrityError as exc:
        raise EmailChangeUnavailable("The new address is no longer available.") from exc

    if not new_email:
        raise EmailChangeUnavailable("The code is invalid or has expired.")
    try:
        send_mail(
            subject="Your StudyCrew email was changed",
            message=(
                f"Your StudyCrew sign-in email was changed to {new_email}. "
                "If this was not you, contact your project administrator immediately."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[old_email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Old-address email-change notice failed for user %s", user.pk)
    return new_email
