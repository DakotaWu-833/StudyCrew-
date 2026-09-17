from django.contrib.auth import get_user_model
from django.test import TestCase


class WorkspaceShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="workspace@example.com",
            password="Strong!Passphrase42",
            display_name="Workspace User",
        )

    def test_nested_client_route_serves_workspace_shell(self):
        self.client.force_login(self.user)
        response = self.client.get(
            "/app/projects/5b6d1139-2ce9-4cff-99a0-8d18b343ac49/tasks/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="workspace-root"')
        self.assertContains(response, 'href="#workspace-main-content"')
        self.assertContains(response, 'data-time-zone="Australia/Sydney"')
        self.assertContains(response, 'img/favicon.svg')
        self.assertIn("csrftoken", response.cookies)

    def test_nested_client_route_requires_login(self):
        response = self.client.get("/app/notifications/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/login/", response.url)
