from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase

from config import views


class SafeErrorViewTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/missing/")
        self.request.user = AnonymousUser()

    def test_all_error_handlers_render_generic_safe_responses(self):
        cases = (
            (views.bad_request, 400, "Invalid request"),
            (views.permission_denied, 403, "Access denied"),
            (views.not_found, 404, "Page not found"),
            (views.server_error, 500, "Something went wrong"),
        )
        secret_detail = "database password: should-never-render"
        for handler, expected_status, expected_title in cases:
            with self.subTest(status=expected_status):
                if handler is views.server_error:
                    response = handler(self.request)
                else:
                    response = handler(self.request, RuntimeError(secret_detail))
                body = response.content.decode()
                self.assertEqual(response.status_code, expected_status)
                self.assertIn(expected_title, body)
                self.assertNotIn(secret_detail, body)
