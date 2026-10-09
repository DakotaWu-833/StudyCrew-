from django.test import TestCase
from django.contrib.auth import get_user_model
from django.test import override_settings
from tempfile import TemporaryDirectory
from pathlib import Path
import json


class BrowserReadinessTests(TestCase):
    def test_public_install_manifest_contains_only_public_icons_and_workspace_entry(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["start_url"], "/app/")
        self.assertEqual([icon["sizes"] for icon in response.json()["icons"]], ["192x192", "512x512"])
        self.assertNotIn("email", response.json())

    def test_worker_is_served_as_script_with_update_revalidation(self):
        response = self.client.get("/service-worker.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertEqual(self.client.post("/service-worker.js").status_code, 405)

    def test_offline_shell_is_identical_public_code_for_visitors_and_members(self):
        visitor = self.client.get("/offline-workspace/")
        user = get_user_model().objects.create_user(email="offline-shell@example.com", password="Offline!Shell2026", display_name="Private name")
        self.client.force_login(user)
        member = self.client.get("/offline-workspace/")
        self.assertEqual(visitor.content, member.content)
        self.assertNotContains(member, user.email)
        self.assertNotContains(member, "Private name")
        self.assertNotContains(member, "csrfmiddlewaretoken")
        self.assertContains(member, 'id="workspace-root"')
        self.assertTrue(member["Cache-Control"].startswith("public"))

    def test_offline_asset_inventory_includes_only_public_dependency_graph(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "static/workspace"
            (root / ".vite").mkdir(parents=True)
            manifest = {"entry": {"isEntry": True, "file": "main.js", "imports": ["shared"], "css": ["workspace.css"]},
                        "shared": {"file": "assets/shared-hash.js", "imports": ["entry"]},
                        "src/pages/OfflineTasksPage.tsx": {"file": "assets/offline-hash.js", "imports": ["shared", "unsafe"]},
                        "unsafe": {"file": "../../api/private.json"}, "unrelated": {"file": "assets/heavy.js"}}
            (root / ".vite/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with override_settings(BASE_DIR=Path(temporary)):
                assets = self.client.get("/offline-assets.json").json()["assets"]
            self.assertIn("/offline-workspace/", assets)
            self.assertIn("/static/workspace/assets/offline-hash.js", assets)
            self.assertIn("/static/workspace/assets/shared-hash.js", assets)
            self.assertNotIn("/static/workspace/assets/heavy.js", assets)
            self.assertTrue(all(value.startswith(("/static/workspace/", "/offline-workspace/")) and ".." not in value for value in assets))

    def test_missing_build_manifest_keeps_offline_inventory_empty(self):
        with TemporaryDirectory() as temporary, override_settings(BASE_DIR=Path(temporary)):
            self.assertEqual(self.client.get("/offline-assets.json").json(), {"assets": []})
