from django.test import SimpleTestCase
from drf_spectacular.generators import SchemaGenerator

from api.schema import MFASessionAuthenticationScheme


class AuthenticationSchemaTests(SimpleTestCase):
    def test_mfa_session_schema_documents_cookie_and_csrf_requirement(self):
        extension = object.__new__(MFASessionAuthenticationScheme)
        definition = extension.get_security_definition(None)
        self.assertEqual(definition["type"], "apiKey")
        self.assertEqual(definition["in"], "cookie")
        self.assertEqual(definition["name"], "sessionid")
        self.assertIn("X-CSRFToken", definition["description"])


class GeneratedContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def test_contract_has_only_canonical_versioned_resource_paths(self):
        paths = self.schema["paths"]
        self.assertNotIn("/api/v1/", paths)
        self.assertFalse(any("{format}" in path for path in paths))
        self.assertIn("/api/v1/projects/", paths)
        self.assertIn("/api/v1/tasks/{id}/transition/", paths)
        self.assertIn("/api/v1/tasks/{id}/send-reminder/", paths)
        self.assertIn("/api/v1/meetings/{id}/cancel/", paths)
        self.assertIn("/api/v1/meetings/{id}/send-reminder/", paths)

    def test_write_operations_document_their_actual_response_resources(self):
        paths = self.schema["paths"]
        expected = {
            ("/api/v1/tasks/", "post"): "#/components/schemas/Task",
            ("/api/v1/comments/", "post"): "#/components/schemas/Comment",
            ("/api/v1/meetings/", "post"): "#/components/schemas/Meeting",
            ("/api/v1/exports/", "post"): "#/components/schemas/ExportJob",
        }
        for (path, method), component in expected.items():
            response = paths[path][method]["responses"]["201"]
            self.assertEqual(
                response["content"]["application/json"]["schema"]["$ref"],
                component,
            )

    def test_export_download_documents_both_binary_media_types(self):
        response = self.schema["paths"]["/api/v1/exports/{id}/download/"]["get"][
            "responses"
        ]["200"]
        content = response["content"]
        self.assertEqual(set(content), {"text/csv", "application/pdf"})
        self.assertTrue(
            all(media["schema"] == {"type": "string", "format": "binary"} for media in content.values())
        )

    def test_meeting_contract_distinguishes_cancel_archive_and_record_scope(self):
        paths = self.schema["paths"]
        self.assertIn("post", paths["/api/v1/meetings/{id}/cancel/"])
        self.assertIn("delete", paths["/api/v1/meetings/{id}/"])
        parameters = paths["/api/v1/meetings/"]["get"]["parameters"]
        scope = next(parameter for parameter in parameters if parameter["name"] == "scope")
        self.assertEqual(scope["schema"]["enum"], ["active", "archived", "all"])
