"""Bounded uploads and email changes remain safe on failure and expiry."""

import tempfile
from datetime import timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

from PIL import Image
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import EmailOTPChallenge, PendingEmailChange, Profile, User
from accounts.profile_services import (
    MAX_AVATAR_BYTES,
    MAX_AVATAR_PIXELS,
    AvatarUploadUnavailable,
    EmailChangeUnavailable,
    confirm_email_change,
    save_profile_avatar,
    start_email_change,
)
from accounts.tests.helpers import VALID_PASSWORD, extract_otp


def image_upload(*, image_format="PNG", mode="RGB", color="navy"):
    buffer = BytesIO()
    Image.new(mode, (64, 48), color).save(buffer, format=image_format)
    return SimpleUploadedFile("avatar", buffer.getvalue(), content_type="image/png")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ProfileAvatarServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="avatar@example.com", password=VALID_PASSWORD)

    def setUp(self):
        media_root = tempfile.TemporaryDirectory()
        self.addCleanup(media_root.cleanup)
        settings_override = override_settings(MEDIA_ROOT=media_root.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.profile = Profile.objects.get(user=self.user)

    def test_missing_or_oversized_file_is_rejected_before_image_decoding(self):
        oversized = SimpleUploadedFile("avatar.png", b"x" * (MAX_AVATAR_BYTES + 1))
        with patch("accounts.profile_services.Image.open") as decode:
            for upload in (None, oversized):
                with self.subTest(upload="missing" if upload is None else "oversized"):
                    with self.assertRaises(AvatarUploadUnavailable):
                        save_profile_avatar(self.profile, upload)
            decode.assert_not_called()
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.avatar)

    def test_unsupported_actual_format_is_rejected_despite_declared_content_type(self):
        with self.assertRaises(AvatarUploadUnavailable):
            save_profile_avatar(self.profile, image_upload(image_format="GIF"))
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.avatar)

    def test_excessive_dimensions_are_rejected_before_loading_pixels(self):
        decoded = MagicMock()
        decoded.format = "PNG"
        decoded.width = MAX_AVATAR_PIXELS + 1
        decoded.height = 1
        opened = MagicMock()
        opened.__enter__.return_value = decoded
        with patch("accounts.profile_services.Image.open", return_value=opened):
            with self.assertRaises(AvatarUploadUnavailable):
                save_profile_avatar(self.profile, image_upload())
        decoded.load.assert_not_called()
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.avatar)

    def test_transparent_image_is_flattened_to_a_safe_square_jpeg(self):
        saved = save_profile_avatar(
            self.profile, image_upload(mode="RGBA", color=(0, 0, 0, 0))
        )
        with saved.avatar.open("rb") as stored, Image.open(stored) as rendered:
            self.assertEqual(rendered.format, "JPEG")
            self.assertEqual(rendered.mode, "RGB")
            self.assertEqual(rendered.size, (512, 512))
            self.assertEqual(rendered.getpixel((256, 256)), (255, 255, 255))

    def test_previous_avatar_is_only_removed_after_successful_commit(self):
        first = save_profile_avatar(self.profile, image_upload())
        old_name = first.avatar.name
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            saved = save_profile_avatar(first, image_upload(color="green"))
        self.assertEqual(len(callbacks), 1)
        self.assertNotEqual(saved.avatar.name, old_name)
        self.assertTrue(saved.avatar.storage.exists(old_name))
        callbacks[0]()
        self.assertFalse(saved.avatar.storage.exists(old_name))
        self.assertTrue(saved.avatar.storage.exists(saved.avatar.name))

    def test_previous_avatar_cleanup_failure_keeps_new_image_available(self):
        first = save_profile_avatar(self.profile, image_upload())
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            saved = save_profile_avatar(first, image_upload(color="green"))
        with patch.object(saved.avatar.storage, "delete", side_effect=OSError("storage unavailable")):
            with self.assertLogs("accounts.profile_services", level="ERROR"):
                callbacks[0]()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.avatar.name, saved.avatar.name)
        self.assertTrue(saved.avatar.storage.exists(saved.avatar.name))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    OTP_TTL_SECONDS=61,
    OTP_MAX_ATTEMPTS=2,
)
class EmailChangeServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="original@example.com", password=VALID_PASSWORD)
        cls.other = User.objects.create_user(email="other@example.com", password=VALID_PASSWORD)

    def start(self, new_email="updated@example.com"):
        change = start_email_change(
            user=self.user, new_email=new_email, current_password=VALID_PASSWORD
        )
        return change, extract_otp(mail.outbox[-1].body)

    def assert_original_address(self):
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "original@example.com")

    def test_invalid_new_address_is_rejected_without_sending_or_persisting(self):
        with self.assertRaisesMessage(EmailChangeUnavailable, "valid new email"):
            self.start("not-an-address")
        self.assertFalse(PendingEmailChange.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_user_cannot_change_address_even_with_correct_password(self):
        self.user.is_active = False
        self.user.save(update_fields=("is_active",))
        with self.assertRaises(EmailChangeUnavailable):
            self.start()
        self.assertFalse(PendingEmailChange.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_current_address_is_rejected_after_normalisation(self):
        with self.assertRaises(EmailChangeUnavailable):
            self.start("  ORIGINAL@EXAMPLE.COM  ")
        self.assertFalse(PendingEmailChange.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_after_cooldown_replaces_code_and_resets_attempts(self):
        with patch("accounts.profile_services.secrets.randbelow", return_value=123456):
            first, first_code = self.start()
        PendingEmailChange.objects.filter(pk=first.pk).update(
            last_sent_at=timezone.now() - timedelta(seconds=61), attempt_count=1
        )
        with patch("accounts.profile_services.secrets.randbelow", return_value=654321):
            second, second_code = self.start("  SECOND@EXAMPLE.COM  ")
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.new_email, "second@example.com")
        self.assertEqual(second.attempt_count, 0)
        self.assertNotEqual(second.code_hash, first.code_hash)
        self.assertIn("2 minute(s)", mail.outbox[-1].body)
        with self.assertRaises(EmailChangeUnavailable):
            confirm_email_change(user=self.user, change_id=str(second.pk), code=first_code)
        self.assertEqual(
            confirm_email_change(user=self.user, change_id=str(second.pk), code=second_code),
            "second@example.com",
        )

    def test_failed_delivery_removes_only_the_unusable_request(self):
        for result in (0, RuntimeError("SMTP unavailable")):
            with self.subTest(result=type(result).__name__):
                options = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with patch("accounts.profile_services.send_mail", **options):
                    if isinstance(result, Exception):
                        with self.assertLogs("accounts.profile_services", level="ERROR"):
                            with self.assertRaisesMessage(EmailChangeUnavailable, "could not be sent"):
                                self.start()
                    else:
                        with self.assertRaisesMessage(EmailChangeUnavailable, "could not be sent"):
                            self.start()
                self.assertFalse(PendingEmailChange.objects.filter(user=self.user).exists())
                self.assert_original_address()

    def test_stale_delivery_failure_does_not_delete_a_newer_request(self):
        def newer_request_before_delivery_returns(**kwargs):
            PendingEmailChange.objects.filter(user=self.user).update(code_hash="b" * 64)
            return 0

        with patch("accounts.profile_services.send_mail", side_effect=newer_request_before_delivery_returns):
            with self.assertRaises(EmailChangeUnavailable):
                self.start()
        self.assertEqual(PendingEmailChange.objects.get(user=self.user).code_hash, "b" * 64)
        self.assert_original_address()

    def test_malformed_confirmation_does_not_spend_attempts_or_change_address(self):
        change, code = self.start()
        for request_id, submitted_code in (("invalid", code), (str(change.pk), "12345"), (None, code)):
            with self.subTest(request_id=request_id, submitted_code=submitted_code):
                with self.assertRaises(EmailChangeUnavailable):
                    confirm_email_change(user=self.user, change_id=request_id, code=submitted_code)
        change.refresh_from_db()
        self.assertEqual(change.attempt_count, 0)
        self.assert_original_address()

    def test_missing_or_another_users_request_cannot_be_confirmed(self):
        change, code = self.start()
        for actor, request_id in ((self.user, uuid4()), (self.other, change.pk)):
            with self.subTest(actor=actor.pk):
                with self.assertRaises(EmailChangeUnavailable):
                    confirm_email_change(user=actor, change_id=str(request_id), code=code)
        change.refresh_from_db()
        self.assertEqual(change.attempt_count, 0)
        self.assert_original_address()

    def test_already_exhausted_request_is_deleted_even_with_correct_code(self):
        change, code = self.start()
        PendingEmailChange.objects.filter(pk=change.pk).update(attempt_count=change.max_attempts)
        with self.assertRaises(EmailChangeUnavailable):
            confirm_email_change(user=self.user, change_id=str(change.pk), code=code)
        self.assertFalse(PendingEmailChange.objects.filter(pk=change.pk).exists())
        self.assert_original_address()

    def test_last_incorrect_attempt_deletes_request_and_prevents_code_reuse(self):
        change, code = self.start()
        wrong_code = "000000" if code != "000000" else "999999"
        for _ in range(change.max_attempts):
            with self.assertRaises(EmailChangeUnavailable):
                confirm_email_change(user=self.user, change_id=str(change.pk), code=wrong_code)
        self.assertFalse(PendingEmailChange.objects.filter(pk=change.pk).exists())
        with self.assertRaises(EmailChangeUnavailable):
            confirm_email_change(user=self.user, change_id=str(change.pk), code=code)
        self.assert_original_address()

    def test_address_claimed_after_request_is_rejected_and_request_consumed(self):
        change, code = self.start()
        self.other.email = change.new_email
        self.other.save(update_fields=("email",))
        with self.assertRaises(EmailChangeUnavailable):
            confirm_email_change(user=self.user, change_id=str(change.pk), code=code)
        self.assertFalse(PendingEmailChange.objects.filter(pk=change.pk).exists())
        self.assert_original_address()

    def test_database_uniqueness_race_is_a_safe_error_and_rolls_back(self):
        change, code = self.start()
        with patch("accounts.profile_services.User.save", side_effect=IntegrityError("duplicate email")):
            with self.assertRaisesMessage(EmailChangeUnavailable, "no longer available"):
                confirm_email_change(user=self.user, change_id=str(change.pk), code=code)
        self.assert_original_address()
        self.assertTrue(PendingEmailChange.objects.filter(pk=change.pk).exists())
        self.assertEqual(len(mail.outbox), 1)

    def test_old_address_notice_failure_does_not_undo_successful_change(self):
        change, code = self.start()
        login = EmailOTPChallenge.objects.create(
            user=self.user, purpose=EmailOTPChallenge.Purpose.LOGIN, code_hash="a" * 64,
            expires_at=timezone.now() + timedelta(minutes=2), max_attempts=2,
            last_sent_at=timezone.now(),
        )
        registration = EmailOTPChallenge.objects.create(
            user=self.user, purpose=EmailOTPChallenge.Purpose.REGISTRATION, code_hash="b" * 64,
            expires_at=timezone.now() + timedelta(minutes=2), max_attempts=2,
            last_sent_at=timezone.now(),
        )
        with patch("accounts.profile_services.send_mail", side_effect=RuntimeError("SMTP unavailable")):
            with self.assertLogs("accounts.profile_services", level="ERROR"):
                result = confirm_email_change(user=self.user, change_id=str(change.pk), code=code)
        self.assertEqual(result, "updated@example.com")
        self.user.refresh_from_db()
        login.refresh_from_db()
        registration.refresh_from_db()
        self.assertEqual(self.user.email, result)
        self.assertIsNotNone(self.user.email_verified_at)
        self.assertIsNotNone(login.consumed_at)
        self.assertIsNone(registration.consumed_at)
        self.assertFalse(PendingEmailChange.objects.filter(pk=change.pk).exists())
        with self.assertRaises(EmailChangeUnavailable):
            confirm_email_change(user=self.user, change_id=str(change.pk), code=code)
