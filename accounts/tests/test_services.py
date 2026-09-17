from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts.models import EmailOTPChallenge, LoginThrottle, Profile, User
from accounts.services import (
    OTPUnavailable,
    RegistrationUnavailable,
    SignInUnavailable,
    client_ip,
    register_user,
    resend_otp,
    start_password_login,
    throttle_digest,
    verify_otp,
)
from accounts.tests.helpers import VALID_PASSWORD, extract_otp


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    LOGIN_FAILURE_LIMIT=2,
    LOGIN_FAILURE_WINDOW_SECONDS=300,
    LOGIN_LOCKOUT_SECONDS=300,
    OTP_TTL_SECONDS=120,
    OTP_MAX_ATTEMPTS=2,
    OTP_RESEND_COOLDOWN_SECONDS=60,
    OTP_MAX_SENDS=3,
)
class AccountServiceTests(TestCase):
    def test_registration_is_inactive_atomic_and_otp_is_never_plaintext(self):
        result = register_user(
            email="NewUser@Example.com",
            display_name="New User",
            password=VALID_PASSWORD,
        )
        user = User.objects.get(email="newuser@example.com")
        challenge = result.challenge
        code = extract_otp(mail.outbox[0].body)

        self.assertFalse(user.is_active)
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(Profile.objects.filter(user=user).count(), 1)
        self.assertEqual(challenge.user, user)
        self.assertNotEqual(challenge.code_hash, code)
        self.assertNotIn(code, challenge.code_hash)
        self.assertEqual(len(challenge.code_hash), 64)
        self.assertTrue(result.delivered)

    def test_registration_otp_activates_once_and_is_single_use(self):
        result = register_user(
            email="verify@example.com",
            display_name="Verify User",
            password=VALID_PASSWORD,
        )
        code = extract_otp(mail.outbox[-1].body)
        user = verify_otp(
            challenge_id=str(result.challenge.id),
            purpose=EmailOTPChallenge.Purpose.REGISTRATION,
            code=code,
        )
        user.refresh_from_db()
        result.challenge.refresh_from_db()

        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.email_verified_at)
        self.assertIsNotNone(result.challenge.consumed_at)
        with self.assertRaises(OTPUnavailable):
            verify_otp(
                challenge_id=str(result.challenge.id),
                purpose=EmailOTPChallenge.Purpose.REGISTRATION,
                code=code,
            )

    def test_expired_otp_is_rejected_and_consumed(self):
        result = register_user(
            email="expired@example.com",
            display_name="Expired User",
            password=VALID_PASSWORD,
        )
        code = extract_otp(mail.outbox[-1].body)
        EmailOTPChallenge.objects.filter(pk=result.challenge.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        with self.assertRaises(OTPUnavailable):
            verify_otp(
                challenge_id=str(result.challenge.id),
                purpose=EmailOTPChallenge.Purpose.REGISTRATION,
                code=code,
            )
        result.challenge.refresh_from_db()
        self.assertIsNotNone(result.challenge.consumed_at)
        self.assertFalse(result.challenge.user.is_active)

    def test_wrong_otp_is_bounded_by_persistent_attempt_limit(self):
        result = register_user(
            email="attempts@example.com",
            display_name="Attempt User",
            password=VALID_PASSWORD,
        )
        real_code = extract_otp(mail.outbox[-1].body)
        wrong_codes = [code for code in ("111111", "222222", "333333") if code != real_code][:2]
        for code in wrong_codes:
            with self.assertRaises(OTPUnavailable):
                verify_otp(
                    challenge_id=str(result.challenge.id),
                    purpose=EmailOTPChallenge.Purpose.REGISTRATION,
                    code=code,
                )
        result.challenge.refresh_from_db()
        self.assertEqual(result.challenge.attempt_count, 2)
        self.assertIsNotNone(result.challenge.consumed_at)

    def test_correct_password_requires_login_otp(self):
        user = User.objects.create_user(email="login@example.com", password=VALID_PASSWORD)
        result = start_password_login(
            email="LOGIN@example.com",
            password=VALID_PASSWORD,
            ip_address="192.0.2.10",
        )
        code = extract_otp(mail.outbox[-1].body)

        self.assertEqual(result.challenge.purpose, EmailOTPChallenge.Purpose.LOGIN)
        self.assertEqual(
            verify_otp(
                challenge_id=str(result.challenge.id),
                purpose=EmailOTPChallenge.Purpose.LOGIN,
                code=code,
            ),
            user,
        )

    def test_unknown_and_wrong_password_fail_with_same_exception(self):
        User.objects.create_user(email="known@example.com", password=VALID_PASSWORD)
        for email in ("unknown@example.com", "known@example.com"):
            with self.assertRaises(SignInUnavailable):
                start_password_login(
                    email=email,
                    password="WrongPass!234",
                    ip_address="192.0.2.11" if email.startswith("unknown") else "192.0.2.12",
                )

    def test_account_and_ip_lockouts_are_persistent_and_hashed(self):
        user = User.objects.create_user(email="locked@example.com", password=VALID_PASSWORD)
        for _ in range(2):
            with self.assertRaises(SignInUnavailable):
                start_password_login(
                    email=user.email,
                    password="WrongPass!234",
                    ip_address="198.51.100.5",
                )

        rows = LoginThrottle.objects.all()
        self.assertEqual(rows.count(), 2)
        self.assertTrue(all(row.locked_until for row in rows))
        self.assertFalse(any(user.email in row.key_digest for row in rows))
        self.assertFalse(any("198.51.100.5" in row.key_digest for row in rows))
        self.assertTrue(
            rows.filter(
                kind=LoginThrottle.KeyKind.ACCOUNT,
                key_digest=throttle_digest(LoginThrottle.KeyKind.ACCOUNT, user.email),
            ).exists()
        )

        # Account lock follows the account to another address.
        with self.assertRaises(SignInUnavailable):
            start_password_login(
                email=user.email,
                password=VALID_PASSWORD,
                ip_address="198.51.100.99",
            )
        # IP lock also applies to another account.
        other = User.objects.create_user(email="other@example.com", password=VALID_PASSWORD)
        with self.assertRaises(SignInUnavailable):
            start_password_login(
                email=other.email,
                password=VALID_PASSWORD,
                ip_address="198.51.100.5",
            )

    def test_successful_password_check_clears_existing_failure_counters(self):
        user = User.objects.create_user(email="clear@example.com", password=VALID_PASSWORD)
        with self.assertRaises(SignInUnavailable):
            start_password_login(
                email=user.email,
                password="WrongPass!234",
                ip_address="203.0.113.4",
            )
        start_password_login(
            email=user.email,
            password=VALID_PASSWORD,
            ip_address="203.0.113.4",
        )
        self.assertFalse(LoginThrottle.objects.exclude(failure_count=0).exists())

    def test_resend_has_cooldown_rotates_code_and_preserves_attempt_budget(self):
        result = register_user(
            email="resend@example.com",
            display_name="Resend User",
            password=VALID_PASSWORD,
        )
        old_code = extract_otp(mail.outbox[-1].body)
        with self.assertRaises(OTPUnavailable):
            resend_otp(
                challenge_id=str(result.challenge.id),
                purpose=result.challenge.purpose,
            )

        EmailOTPChallenge.objects.filter(pk=result.challenge.pk).update(
            last_sent_at=timezone.now() - timedelta(seconds=61)
        )
        resent = resend_otp(
            challenge_id=str(result.challenge.id),
            purpose=result.challenge.purpose,
        )
        new_code = extract_otp(mail.outbox[-1].body)
        self.assertNotEqual(old_code, new_code)
        resent.challenge.refresh_from_db()
        self.assertEqual(resent.challenge.send_count, 2)
        self.assertEqual(resent.challenge.attempt_count, 0)

        with self.assertRaises(OTPUnavailable):
            verify_otp(
                challenge_id=str(resent.challenge.id),
                purpose=resent.challenge.purpose,
                code=old_code,
            )
        self.assertEqual(
            verify_otp(
                challenge_id=str(resent.challenge.id),
                purpose=resent.challenge.purpose,
                code=new_code,
            ).email,
            "resend@example.com",
        )

    def test_invalid_challenge_identifier_is_a_safe_failure(self):
        with self.assertRaises(OTPUnavailable):
            verify_otp(challenge_id="not-a-uuid", purpose="login", code="123456")
        with self.assertRaises(OTPUnavailable):
            resend_otp(challenge_id="not-a-uuid", purpose="login")

    def test_registration_service_rechecks_password_policy(self):
        with self.assertRaises(RegistrationUnavailable):
            register_user(
                email="weak@example.com",
                display_name="Weak Password",
                password="weak",
            )
        self.assertFalse(User.objects.filter(email="weak@example.com").exists())

    def test_email_delivery_failure_is_non_destructive_and_reported(self):
        with patch("accounts.services.send_mail", side_effect=OSError("mail unavailable")):
            result = register_user(
                email="mail-failure@example.com",
                display_name="Mail Failure",
                password=VALID_PASSWORD,
            )
        self.assertFalse(result.delivered)
        self.assertTrue(User.objects.filter(email="mail-failure@example.com").exists())
        self.assertTrue(EmailOTPChallenge.objects.filter(pk=result.challenge.pk).exists())

    def test_disabled_verified_account_cannot_start_mfa(self):
        user = User.objects.create_user(email="disabled@example.com", password=VALID_PASSWORD)
        user.is_active = False
        user.save(update_fields=("is_active", "updated_at"))
        with self.assertRaises(SignInUnavailable):
            start_password_login(
                email=user.email,
                password=VALID_PASSWORD,
                ip_address="192.0.2.50",
            )
        self.assertFalse(EmailOTPChallenge.objects.filter(user=user).exists())

    def test_unverified_user_can_restart_registration_from_login(self):
        registration = register_user(
            email="restart@example.com",
            display_name="Restart User",
            password=VALID_PASSWORD,
        )
        restarted = start_password_login(
            email="restart@example.com",
            password=VALID_PASSWORD,
            ip_address="192.0.2.51",
        )
        registration.challenge.refresh_from_db()
        self.assertIsNotNone(registration.challenge.consumed_at)
        self.assertEqual(restarted.challenge.purpose, EmailOTPChallenge.Purpose.REGISTRATION)

    def test_existing_uuid_without_challenge_is_safe_failure(self):
        with self.assertRaises(OTPUnavailable):
            verify_otp(challenge_id=str(uuid4()), purpose="login", code="123456")

    @override_settings(
        REST_FRAMEWORK={"NUM_PROXIES": 1},
    )
    def test_client_ip_uses_only_configured_trusted_proxy_depth(self):
        request = RequestFactory().get(
            "/",
            REMOTE_ADDR="10.0.0.8",
            HTTP_X_FORWARDED_FOR="198.51.100.8",
        )
        self.assertEqual(client_ip(request), "198.51.100.8")

    def test_invalid_ip_is_normalised_before_hashing(self):
        with self.assertRaises(SignInUnavailable):
            start_password_login(
                email="missing@example.com",
                password="WrongPass!234",
                ip_address="not-an-ip-address",
            )
        ip_row = LoginThrottle.objects.get(kind=LoginThrottle.KeyKind.IP_ADDRESS)
        self.assertEqual(
            ip_row.key_digest,
            throttle_digest(LoginThrottle.KeyKind.IP_ADDRESS, "unknown"),
        )
