from django.contrib.sessions.models import Session
from django.core import mail
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch

from accounts.middleware import UserTimezoneMiddleware
from accounts.models import EmailOTPChallenge, User
from accounts.session_security import MFA_VERIFIED_SESSION_KEY, is_mfa_verified
from accounts.tests.helpers import NEW_VALID_PASSWORD, VALID_PASSWORD, extract_otp
from accounts.views import GENERIC_REGISTRATION_ERROR, GENERIC_SIGN_IN_ERROR


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    LOGIN_FAILURE_LIMIT=3,
    LOGIN_FAILURE_WINDOW_SECONDS=300,
    LOGIN_LOCKOUT_SECONDS=300,
    OTP_TTL_SECONDS=120,
    OTP_MAX_ATTEMPTS=3,
)
class AccountViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="member@example.com",
            password=VALID_PASSWORD,
            display_name="First Member",
        )

    def test_registration_verification_then_session(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "new@example.com",
                "display_name": "New Member",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        self.assertRedirects(response, reverse("accounts:verify_otp"), fetch_redirect_response=False)
        new_user = User.objects.get(email="new@example.com")
        self.assertFalse(new_user.is_active)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn(MFA_VERIFIED_SESSION_KEY, self.client.session)

        code = extract_otp(mail.outbox[-1].body)
        response = self.client.post(reverse("accounts:verify_otp"), {"code": code})
        self.assertRedirects(response, reverse("web:dashboard"), fetch_redirect_response=False)
        new_user.refresh_from_db()
        self.assertTrue(new_user.is_active)
        self.assertIsNotNone(new_user.email_verified_at)
        self.assertEqual(self.client.session["_auth_user_id"], str(new_user.pk))
        self.assertIn(MFA_VERIFIED_SESSION_KEY, self.client.session)

    def test_password_login_does_not_authenticate_until_mfa_succeeds(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"email": self.user.email, "password": VALID_PASSWORD},
            REMOTE_ADDR="192.0.2.20",
        )
        self.assertRedirects(response, reverse("accounts:verify_otp"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn(MFA_VERIFIED_SESSION_KEY, self.client.session)
        challenge = EmailOTPChallenge.objects.get(user=self.user, purpose="login")
        self.assertIsNone(challenge.consumed_at)

        code = extract_otp(mail.outbox[-1].body)
        response = self.client.post(reverse("accounts:verify_otp"), {"code": code})
        self.assertRedirects(response, reverse("web:dashboard"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))
        self.assertIn(MFA_VERIFIED_SESSION_KEY, self.client.session)

    def test_login_rejects_external_next_url(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "email": self.user.email,
                "password": VALID_PASSWORD,
                "next": "https://attacker.example/steal",
            },
            REMOTE_ADDR="192.0.2.21",
        )
        self.assertEqual(response.status_code, 302)
        code = extract_otp(mail.outbox[-1].body)
        response = self.client.post(reverse("accounts:verify_otp"), {"code": code})
        self.assertEqual(response.headers["Location"], reverse("web:dashboard"))

    def test_unknown_email_and_wrong_password_have_same_user_facing_error(self):
        responses = (
            self.client.post(
                reverse("accounts:login"),
                {"email": "unknown@example.com", "password": "WrongPass!234"},
                REMOTE_ADDR="192.0.2.30",
            ),
            self.client.post(
                reverse("accounts:login"),
                {"email": self.user.email, "password": "WrongPass!234"},
                REMOTE_ADDR="192.0.2.31",
            ),
        )
        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, GENERIC_SIGN_IN_ERROR)

    def test_duplicate_registration_uses_generic_error_and_creates_nothing(self):
        before_users = User.objects.count()
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": self.user.email.upper(),
                "display_name": "Duplicate",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, GENERIC_REGISTRATION_ERROR)
        self.assertEqual(User.objects.count(), before_users)

    def test_tampered_challenge_session_is_safe(self):
        session = self.client.session
        session["accounts.otp_challenge_id"] = "not-a-uuid"
        session["accounts.otp_purpose"] = "login"
        session.save()
        response = self.client.get(reverse("accounts:verify_otp"))
        self.assertRedirects(response, reverse("accounts:login"), fetch_redirect_response=False)

    def test_logout_is_post_only_and_invalidates_server_session(self):
        self.client.force_login(self.user)
        old_session_key = self.client.session.session_key
        self.assertTrue(Session.objects.filter(session_key=old_session_key).exists())

        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("web:home"), fetch_redirect_response=False)
        self.assertFalse(Session.objects.filter(session_key=old_session_key).exists())
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn(MFA_VERIFIED_SESSION_KEY, self.client.session)

    def test_profile_route_updates_only_authenticated_users_own_profile(self):
        other = User.objects.create_user(
            email="other@example.com",
            password=VALID_PASSWORD,
            display_name="Other Member",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "user": str(other.pk),
                "display_name": "Updated Member",
                "course_code": "ELEC3609",
                "time_zone": "Pacific/Auckland",
                "biography": "Updated safely.",
                "avatar_url": "https://example.com/me.png",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        other.profile.refresh_from_db()
        self.assertEqual(self.user.profile.display_name, "Updated Member")
        self.assertEqual(self.user.profile.time_zone, "Pacific/Auckland")
        self.assertEqual(other.profile.display_name, "Other Member")

    def test_profile_requires_authentication(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.headers["Location"])

    def test_password_change_rotates_current_session_and_invalidates_other_sessions(self):
        current_client = Client()
        other_client = Client()
        current_client.force_login(self.user)
        other_client.force_login(self.user)
        current_session = current_client.session.session_key

        response = current_client.post(
            reverse("accounts:password_change"),
            {
                "old_password": VALID_PASSWORD,
                "new_password1": NEW_VALID_PASSWORD,
                "new_password2": NEW_VALID_PASSWORD,
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_VALID_PASSWORD))
        self.assertNotEqual(current_client.session.session_key, current_session)
        self.assertEqual(current_client.get(reverse("accounts:profile")).status_code, 200)
        self.assertEqual(other_client.get(reverse("accounts:profile")).status_code, 302)

    def test_resend_and_logout_mutations_reject_get(self):
        self.assertEqual(self.client.get(reverse("accounts:resend_otp")).status_code, 405)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)

    def test_verification_page_masks_email_and_wrong_code_is_generic(self):
        self.client.post(
            reverse("accounts:login"),
            {"email": self.user.email, "password": VALID_PASSWORD},
            REMOTE_ADDR="192.0.2.60",
        )
        response = self.client.get(reverse("accounts:verify_otp"))
        self.assertContains(response, "m•••••@example.com")
        self.assertNotContains(response, self.user.email)
        real_code = extract_otp(mail.outbox[-1].body)
        wrong_code = "999999" if real_code != "999999" else "999998"
        response = self.client.post(reverse("accounts:verify_otp"), {"code": wrong_code})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "invalid or no longer available")

    def test_resend_requires_a_current_challenge(self):
        response = self.client.post(reverse("accounts:resend_otp"))
        self.assertRedirects(response, reverse("accounts:login"), fetch_redirect_response=False)

    def test_resend_enforces_cooldown_then_sends_rotated_code(self):
        self.client.post(
            reverse("accounts:login"),
            {"email": self.user.email, "password": VALID_PASSWORD},
            REMOTE_ADDR="192.0.2.61",
        )
        response = self.client.post(reverse("accounts:resend_otp"), follow=True)
        self.assertContains(response, "not available yet")

        challenge = EmailOTPChallenge.objects.get(user=self.user, purpose="login")
        EmailOTPChallenge.objects.filter(pk=challenge.pk).update(
            last_sent_at=timezone.now() - timedelta(seconds=61)
        )
        response = self.client.post(reverse("accounts:resend_otp"), follow=True)
        self.assertContains(response, "new six-digit code was sent", html=False)
        challenge.refresh_from_db()
        self.assertEqual(challenge.send_count, 2)

    def test_authenticated_user_is_redirected_away_from_authentication_pages(self):
        self.client.force_login(self.user)
        for name in ("register", "login", "verify_otp"):
            response = self.client.get(reverse(f"accounts:{name}"))
            self.assertRedirects(response, reverse("web:dashboard"), fetch_redirect_response=False)
        response = self.client.post(reverse("accounts:resend_otp"))
        self.assertRedirects(response, reverse("web:dashboard"), fetch_redirect_response=False)

    def test_delivery_failure_is_visible_without_exposing_internal_error(self):
        with patch("accounts.services.send_mail", side_effect=OSError("SMTP secret detail")):
            response = self.client.post(
                reverse("accounts:register"),
                {
                    "email": "delivery@example.com",
                    "display_name": "Delivery User",
                    "password1": VALID_PASSWORD,
                    "password2": VALID_PASSWORD,
                },
                follow=True,
            )
        self.assertContains(response, "could not be delivered")
        self.assertNotContains(response, "SMTP secret detail")

    def test_password_change_get_and_invalid_old_password_render_form(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:password_change")).status_code, 200)
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "WrongPass!234",
                "new_password1": NEW_VALID_PASSWORD,
                "new_password2": NEW_VALID_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "old password was entered incorrectly")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class UserTimezoneMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(email="timezone@example.com", password=VALID_PASSWORD)

    def test_activates_profile_timezone_for_request(self):
        self.user.profile.time_zone = "Pacific/Auckland"
        self.user.profile.save(update_fields=("time_zone",))
        observed = {}
        previous_zone = timezone.get_current_timezone_name()

        def response(request):
            observed["zone"] = timezone.get_current_timezone_name()
            return None

        request = self.factory.get("/")
        request.user = self.user
        UserTimezoneMiddleware(response)(request)
        self.assertEqual(observed["zone"], "Pacific/Auckland")
        self.assertEqual(timezone.get_current_timezone_name(), previous_zone)

    def test_invalid_stored_timezone_falls_back_to_utc(self):
        self.user.profile.time_zone = "Invalid/Zone"
        self.user.profile.save(update_fields=("time_zone",))
        observed = {}

        def response(request):
            observed["zone"] = timezone.get_current_timezone_name()
            return None

        request = self.factory.get("/")
        request.user = self.user
        UserTimezoneMiddleware(response)(request)
        self.assertEqual(observed["zone"], "UTC")
