"""Transactional application services for account security workflows."""

from __future__ import annotations

import ipaddress
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Iterable

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from accounts.models import EmailOTPChallenge, LoginThrottle, User


logger = logging.getLogger(__name__)


class RegistrationUnavailable(Exception):
    """Registration could not be completed without revealing why."""


class SignInUnavailable(Exception):
    """Credentials were invalid, the account was disabled, or throttling applied."""


class OTPUnavailable(Exception):
    """A challenge could not be verified or resent."""


@dataclass(frozen=True)
class OTPStartResult:
    challenge: EmailOTPChallenge
    delivered: bool


def normalise_email(email: str) -> str:
    return User.objects.normalize_email(email).strip().lower()


def normalise_ip(value: str | None) -> str:
    """Return a canonical IP without trusting arbitrary forwarding headers."""

    try:
        return ipaddress.ip_address((value or "").strip()).compressed
    except ValueError:
        return "unknown"


def client_ip(request: HttpRequest) -> str:
    """Resolve the client IP using only the configured number of trusted proxies."""

    remote = normalise_ip(request.META.get("REMOTE_ADDR"))
    proxy_count = int(getattr(settings, "REST_FRAMEWORK", {}).get("NUM_PROXIES", 0) or 0)
    if proxy_count <= 0:
        return remote

    forwarded = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")]
    chain = [normalise_ip(part) for part in forwarded if part.strip()] + [remote]
    if len(chain) <= proxy_count:
        return remote
    candidate = chain[-(proxy_count + 1)]
    return candidate if candidate != "unknown" else remote


def _security_digest(kind: str, value: str) -> str:
    """Create a stable keyed digest; raw account and IP keys never reach the DB."""

    return salted_hmac(
        "accounts.login-throttle",
        f"{kind}:{value}",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def throttle_digest(kind: str, value: str) -> str:
    """Public helper used by security audits without exposing the secret key."""

    return _security_digest(kind, value)


def _otp_digest(challenge_id, code: str) -> str:
    return salted_hmac(
        "accounts.email-otp",
        f"{challenge_id}:{code}",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """Equalise the expensive password check for unknown email addresses."""

    return make_password(secrets.token_urlsafe(32))


def _throttle_keys(email: str, ip_address: str) -> tuple[tuple[str, str], ...]:
    raw_keys = (
        (LoginThrottle.KeyKind.ACCOUNT, normalise_email(email)),
        (LoginThrottle.KeyKind.IP_ADDRESS, normalise_ip(ip_address)),
    )
    return tuple((kind, _security_digest(kind, value)) for kind, value in raw_keys)


def _locked_throttle_rows(keys: Iterable[tuple[str, str]]) -> list[LoginThrottle]:
    rows: list[LoginThrottle] = []
    # A stable order avoids account/IP lock inversion under concurrent requests.
    for kind, digest in sorted(keys):
        row, _ = LoginThrottle.objects.select_for_update().get_or_create(
            kind=kind,
            key_digest=digest,
            defaults={"window_started_at": timezone.now()},
        )
        rows.append(row)
    return rows


def _is_locked(rows: Iterable[LoginThrottle], now) -> bool:
    return any(row.locked_until is not None and row.locked_until > now for row in rows)


def _record_failure(rows: Iterable[LoginThrottle], now) -> None:
    window = timedelta(seconds=settings.LOGIN_FAILURE_WINDOW_SECONDS)
    lockout = timedelta(seconds=settings.LOGIN_LOCKOUT_SECONDS)
    limit = settings.LOGIN_FAILURE_LIMIT
    for row in rows:
        if now - row.window_started_at >= window:
            row.failure_count = 0
            row.window_started_at = now
            row.locked_until = None
        row.failure_count += 1
        row.last_failed_at = now
        if row.failure_count >= limit:
            row.locked_until = now + lockout
        row.save(
            update_fields=(
                "failure_count",
                "window_started_at",
                "last_failed_at",
                "locked_until",
                "updated_at",
            )
        )


def _clear_failures(rows: Iterable[LoginThrottle], now) -> None:
    for row in rows:
        row.failure_count = 0
        row.window_started_at = now
        row.last_failed_at = None
        row.locked_until = None
        row.save(
            update_fields=(
                "failure_count",
                "window_started_at",
                "last_failed_at",
                "locked_until",
                "updated_at",
            )
        )


def _new_otp_challenge(user: User, purpose: str, now) -> tuple[EmailOTPChallenge, str]:
    EmailOTPChallenge.objects.filter(
        user=user,
        purpose=purpose,
        consumed_at__isnull=True,
    ).update(consumed_at=now)

    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = EmailOTPChallenge(
        user=user,
        purpose=purpose,
        expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
        max_attempts=settings.OTP_MAX_ATTEMPTS,
        last_sent_at=now,
    )
    challenge.code_hash = _otp_digest(challenge.id, code)
    challenge.save(force_insert=True)
    return challenge, code


def _rotated_otp(challenge: EmailOTPChallenge) -> tuple[str, str]:
    """Generate a code that is guaranteed to differ from the current code."""

    while True:
        code = f"{secrets.randbelow(1_000_000):06d}"
        digest = _otp_digest(challenge.id, code)
        if not constant_time_compare(challenge.code_hash, digest):
            return code, digest


def _deliver_otp(challenge: EmailOTPChallenge, code: str) -> bool:
    ttl_minutes = max(1, settings.OTP_TTL_SECONDS // 60)
    try:
        sent = send_mail(
            subject="Your StudyCrew security code",
            message=(
                f"Your StudyCrew security code is {code}.\n\n"
                f"It expires in {ttl_minutes} minutes. "
                "If you did not request this code, you can ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[challenge.user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("OTP email delivery failed for challenge %s", challenge.id)
        return False
    return sent == 1


def register_user(*, email: str, display_name: str, password: str) -> OTPStartResult:
    """Atomically create one inactive user/profile and a verification challenge."""

    email = normalise_email(email)
    try:
        validate_password(password, user=User(email=email))
    except ValidationError as error:
        raise RegistrationUnavailable from error

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password,
                display_name=display_name,
                is_active=False,
                email_verified_at=None,
            )
            challenge, code = _new_otp_challenge(
                user,
                EmailOTPChallenge.Purpose.REGISTRATION,
                timezone.now(),
            )
    except IntegrityError as error:
        raise RegistrationUnavailable from error

    return OTPStartResult(challenge=challenge, delivered=_deliver_otp(challenge, code))


def start_password_login(*, email: str, password: str, ip_address: str) -> OTPStartResult:
    """Verify password and throttles, then issue the required MFA challenge."""

    email = normalise_email(email)
    now = timezone.now()
    unavailable = False
    challenge: EmailOTPChallenge | None = None
    code = ""

    with transaction.atomic():
        throttle_rows = _locked_throttle_rows(_throttle_keys(email, ip_address))
        locked = _is_locked(throttle_rows, now)
        user = User.objects.select_for_update().filter(email=email).first()

        if user is None:
            password_valid = check_password(password, _dummy_password_hash())
        else:
            password_valid = user.check_password(password)

        disabled = bool(user and user.email_verified_at and not user.is_active)
        if locked or not password_valid or user is None or disabled:
            # An existing lock is not extended by every request; this bounds the
            # denial period while returning the same response as bad credentials.
            if not locked:
                _record_failure(throttle_rows, now)
            unavailable = True
        else:
            _clear_failures(throttle_rows, now)
            purpose = (
                EmailOTPChallenge.Purpose.LOGIN
                if user.email_verified_at is not None and user.is_active
                else EmailOTPChallenge.Purpose.REGISTRATION
            )
            challenge, code = _new_otp_challenge(user, purpose, now)

    if unavailable or challenge is None:
        raise SignInUnavailable
    return OTPStartResult(challenge=challenge, delivered=_deliver_otp(challenge, code))


def verify_otp(*, challenge_id: str, purpose: str, code: str) -> User:
    """Consume exactly one valid challenge and activate registrations atomically."""

    now = timezone.now()
    user: User | None = None
    valid = False

    try:
        parsed_challenge_id = uuid.UUID(str(challenge_id))
    except (AttributeError, TypeError, ValueError):
        constant_time_compare(_otp_digest(str(challenge_id), code), "0" * 64)
        raise OTPUnavailable from None

    with transaction.atomic():
        challenge = (
            EmailOTPChallenge.objects.select_for_update()
            .filter(id=parsed_challenge_id, purpose=purpose)
            .first()
        )
        if challenge is None:
            constant_time_compare(_otp_digest(challenge_id, code), "0" * 64)
        elif challenge.consumed_at is not None:
            pass
        elif challenge.expires_at <= now:
            challenge.consumed_at = now
            challenge.save(update_fields=("consumed_at",))
        elif challenge.attempt_count >= challenge.max_attempts:
            challenge.consumed_at = now
            challenge.save(update_fields=("consumed_at",))
        elif constant_time_compare(challenge.code_hash, _otp_digest(challenge.id, code)):
            challenge.consumed_at = now
            challenge.save(update_fields=("consumed_at",))
            user = User.objects.select_for_update().get(pk=challenge.user_id)
            if purpose == EmailOTPChallenge.Purpose.REGISTRATION:
                user.email_verified_at = user.email_verified_at or now
                user.is_active = True
                user.save(update_fields=("email_verified_at", "is_active", "updated_at"))
            valid = user.is_active
        else:
            challenge.attempt_count += 1
            if challenge.attempt_count >= challenge.max_attempts:
                challenge.consumed_at = now
            challenge.save(update_fields=("attempt_count", "consumed_at"))

    if not valid or user is None:
        raise OTPUnavailable
    return user


def resend_otp(*, challenge_id: str, purpose: str) -> OTPStartResult:
    """Rotate the code subject to a persistent cooldown and bounded send count."""

    now = timezone.now()
    cooldown_seconds = int(getattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 60))
    max_sends = int(getattr(settings, "OTP_MAX_SENDS", 3))
    challenge: EmailOTPChallenge | None = None
    code = ""

    try:
        parsed_challenge_id = uuid.UUID(str(challenge_id))
    except (AttributeError, TypeError, ValueError):
        raise OTPUnavailable from None

    with transaction.atomic():
        challenge = (
            EmailOTPChallenge.objects.select_for_update()
            .select_related("user")
            .filter(id=parsed_challenge_id, purpose=purpose)
            .first()
        )
        unavailable = (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.attempt_count >= challenge.max_attempts
            or challenge.send_count >= max_sends
            or challenge.last_sent_at + timedelta(seconds=cooldown_seconds) > now
        )
        if not unavailable and challenge is not None:
            code, challenge.code_hash = _rotated_otp(challenge)
            challenge.expires_at = now + timedelta(seconds=settings.OTP_TTL_SECONDS)
            challenge.last_sent_at = now
            challenge.send_count += 1
            challenge.save(
                update_fields=("code_hash", "expires_at", "last_sent_at", "send_count")
            )

    if challenge is None or not code:
        raise OTPUnavailable
    return OTPStartResult(challenge=challenge, delivered=_deliver_otp(challenge, code))
