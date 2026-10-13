"""MFA, CSRF, reauthentication and cross-account isolation at the API boundary."""

from django.core import mail
from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import AccountDeviceSession, RecoveryEmail, User
from accounts.tests.helpers import VALID_PASSWORD
from accounts.tests.test_readiness_services import latest_token


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                   PUBLIC_BASE_URL="https://studycrew.example",
                   ROOT_URLCONF="accounts.tests.readiness_test_urls")
class AccountReadinessViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="student@example.com", password=VALID_PASSWORD)
        cls.other = User.objects.create_user(email="other@example.com", password=VALID_PASSWORD)

    def signin(self, client=None, *, mfa=True):
        target = client or self.client
        target.force_login(self.user)
        if mfa:
            session = target.session
            session["mfa_verified_at"] = timezone.now().isoformat()
            session.save()
        return target

    def unlock(self):
        return self.client.post("/api/v1/account/reauthenticate/", {"current_password": VALID_PASSWORD}, content_type="application/json")

    def test_security_api_requires_login_and_mfa(self):
        self.assertEqual(self.client.get("/api/v1/account/security/").status_code, 401)
        self.signin(mfa=False)
        self.assertEqual(self.client.get("/api/v1/account/security/").status_code, 401)
        self.signin()
        self.assertEqual(self.client.get("/api/v1/account/security/").status_code, 200)

    def test_reauthentication_checks_password_and_sensitive_actions_require_it(self):
        self.signin()
        self.assertEqual(self.client.post("/api/v1/account/recovery-email/", {"email": "backup@example.com"}, content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post("/api/v1/account/reauthenticate/", {"current_password": "wrong"}, content_type="application/json").status_code, 400)
        self.assertEqual(self.unlock().status_code, 200)
        self.assertEqual(self.client.post("/api/v1/account/recovery-email/", {"email": "backup@example.com"}, content_type="application/json").status_code, 202)

    def test_sensitive_api_enforces_csrf(self):
        strict = self.signin(Client(enforce_csrf_checks=True))
        self.assertEqual(strict.post("/api/v1/account/reauthenticate/", {"current_password": VALID_PASSWORD}).status_code, 403)

    def test_reauthentication_expires(self):
        from datetime import timedelta
        self.signin()
        session = self.client.session
        session["accounts.reauthenticated_at"] = (timezone.now() - timedelta(minutes=6)).isoformat()
        session.save()
        self.assertEqual(self.client.post("/api/v1/account/devices/revoke-others/").status_code, 403)

    def test_summary_exposes_opaque_device_id_not_session_key_or_other_users(self):
        self.signin()
        row = AccountDeviceSession.objects.create(user=self.other, session_key="other-session", expires_at=timezone.now() + timezone.timedelta(hours=1))
        response = self.client.get("/api/v1/account/security/")
        data = response.json()
        self.assertEqual(len(data["devices"]), 1)
        self.assertTrue(data["devices"][0]["current"])
        self.assertNotIn("session_key", data["devices"][0])
        self.assertNotIn(str(row.pk), response.content.decode())
        self.assertEqual(response["Cache-Control"], "no-store, private")

    def test_cannot_revoke_other_users_device(self):
        self.signin()
        self.unlock()
        row = AccountDeviceSession.objects.create(user=self.other, session_key="other-session", expires_at=timezone.now() + timezone.timedelta(hours=1))
        response = self.client.post(f"/api/v1/account/devices/{row.pk}/revoke/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(AccountDeviceSession.objects.filter(pk=row.pk).exists())

    def test_current_device_revoke_flushes_session(self):
        self.signin()
        self.unlock()
        row = self.client.get("/api/v1/account/security/").json()["devices"][0]
        key = self.client.session.session_key
        response = self.client.post(f"/api/v1/account/devices/{row['id']}/revoke/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["signed_out"])
        self.assertFalse(Session.objects.filter(pk=key).exists())
        self.assertEqual(self.client.get("/api/v1/account/security/").status_code, 401)

    def test_download_requires_reauthentication_and_returns_private_attachment(self):
        self.signin()
        self.assertEqual(self.client.post("/api/v1/account/data/download/").status_code, 403)
        self.unlock()
        response = self.client.post("/api/v1/account/data/download/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(response.json()["account"]["email"], self.user.email)

    def test_password_reset_public_feedback_is_identical_for_known_and_unknown_accounts(self):
        known = self.client.post("/account/password/reset/", {"email": self.user.email}, follow=True)
        unknown = self.client.post("/account/password/reset/", {"email": "unknown@example.com"}, follow=True)
        self.assertEqual(known.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        self.assertContains(known, "If the details match an eligible account")
        self.assertContains(unknown, "If the details match an eligible account")
        self.assertEqual(len(mail.outbox), 1)

    def test_public_link_get_does_not_consume_token_and_post_requires_csrf(self):
        self.signin()
        self.unlock()
        self.client.post("/api/v1/account/recovery-email/", {"email": "backup@example.com"}, content_type="application/json")
        token = latest_token()
        strict = Client(enforce_csrf_checks=True)
        response = strict.get("/account/recovery/email/verify/", {"token": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Referrer-Policy"], "strict-origin")
        self.assertFalse(RecoveryEmail.objects.filter(user=self.user).exists())
        self.assertEqual(strict.post("/account/recovery/email/verify/", {"token": token}).status_code, 403)
        self.assertEqual(self.client.post("/account/recovery/email/verify/", {"token": token}).status_code, 302)
        self.assertTrue(RecoveryEmail.objects.filter(user=self.user).exists())

    def test_closure_logs_out_and_cannot_sign_back_in(self):
        self.signin()
        self.unlock()
        response = self.client.post("/api/v1/account/close/", {"confirmation": "CLOSE MY ACCOUNT"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/account/security/").status_code, 401)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_login_page_links_to_both_recovery_flows_and_privacy(self):
        response = self.client.get("/account/login/")
        self.assertContains(response, "Forgot your password?")
        self.assertContains(response, "Cannot access your sign-in email?")
        self.assertContains(response, "Privacy and data retention")
