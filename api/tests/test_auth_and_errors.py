from django.test import override_settings
from rest_framework.test import APIClient

from accounts.session_security import MFA_VERIFIED_SESSION_KEY
from api.tests.base import APIDomainTestCase


class APIAuthenticationTests(APIDomainTestCase):
    def test_health_is_public_and_checks_database(self):
        response = self.client.get("/api/v1/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_visitor_gets_stable_401(self):
        response = self.client.get("/api/v1/projects/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "not_authenticated")
        self.assertNotIn("traceback", response.content.decode().lower())

    def test_authenticated_session_without_mfa_marker_is_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "not_authenticated")

    def test_tampered_mfa_marker_is_rejected(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session[MFA_VERIFIED_SESSION_KEY] = "not-a-timestamp"
        session.save()
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)

    def test_me_and_profile_are_owned_by_current_user(self):
        self.authenticate(self.member)
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], self.member.email)
        response = self.client.patch(
            "/api/v1/profile/",
            {"display_name": "Updated Member", "time_zone": "Pacific/Auckland"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.display_name, "Updated Member")
        rejected = self.client.patch(
            "/api/v1/profile/",
            {"email": "takeover@example.com", "is_staff": True},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(set(rejected.json()["error"]["fields"]), {"email", "is_staff"})

    def test_invalid_timezone_has_field_error_without_internal_detail(self):
        self.authenticate(self.member)
        response = self.client.patch(
            "/api/v1/profile/", {"time_zone": "Mars/Olympus"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "validation_error")
        self.assertIn("time_zone", body["error"]["fields"])
        self.assertNotIn("Traceback", response.content.decode())

    def test_csrf_is_required_for_session_mutations(self):
        client = APIClient(enforce_csrf_checks=True)
        self.authenticate(self.owner, client=client)
        blocked = client.post("/api/v1/projects/", {"name": "CSRF project"}, format="json")
        self.assertEqual(blocked.status_code, 403)

        # Rendering a Django form issues the same-origin CSRF cookie.
        page = client.get("/account/profile/")
        self.assertEqual(page.status_code, 200)
        token = client.cookies["csrftoken"].value
        allowed = client.post(
            "/api/v1/projects/",
            {"name": "CSRF project"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(allowed.status_code, 201)
