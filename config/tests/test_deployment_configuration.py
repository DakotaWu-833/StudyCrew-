"""Source-level production guards; these do not replace a live Linux/DB check."""

from pathlib import Path
import re

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.test.client import BOUNDARY, encode_multipart

from accounts.profile_services import MAX_AVATAR_BYTES


ROOT = Path(__file__).resolve().parents[2]
DELETE_ALLOWLIST = {
    "public.django_session",
    "public.tasks_taskassignment",
    "public.accounts_pendingemailchange",
}
AUDIT_TABLES = {"activity_activityevent", "activity_siteauditevent"}


def sql_source(path: Path) -> str:
    """Normalise whitespace after removing comments, not SQL string contents."""
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))).strip()


class ProductionConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.sql = sql_source(ROOT / "deploy/postgresql/permissions.sql")
        self.nginx = (ROOT / "deploy/nginx/studycrew.conf").read_text(encoding="utf-8")

    def test_runtime_delete_rights_are_an_explicit_small_allowlist(self):
        grants = re.findall(
            r"GRANT DELETE ON TABLE (.*?) TO studycrew_app;", self.sql, re.IGNORECASE
        )
        granted_tables = {
            table.strip().lower() for grant in grants for table in grant.split(",")
        }
        self.assertEqual(granted_tables, DELETE_ALLOWLIST)
        revoke = "REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM studycrew_app;"
        self.assertIn(revoke, self.sql)
        first_grant = re.search(r"GRANT DELETE ON TABLE", self.sql, re.IGNORECASE)
        self.assertIsNotNone(first_grant)
        self.assertLess(self.sql.index(revoke), first_grant.start())
        self.assertNotRegex(
            self.sql, r"(?i)GRANT\s+(?:ALL|[^;]*\bDELETE\b)[^;]*ON ALL TABLES[^;]*TO studycrew_app"
        )

    def test_runtime_role_has_no_database_or_schema_creation_grants(self):
        self.assertIn(
            "REVOKE CONNECT, CREATE, TEMPORARY ON DATABASE studycrew FROM PUBLIC;", self.sql
        )
        self.assertIn("REVOKE ALL ON SCHEMA public FROM PUBLIC;", self.sql)
        self.assertIn("REVOKE ALL ON SCHEMA public FROM studycrew_app;", self.sql)
        self.assertIn("GRANT CONNECT ON DATABASE studycrew TO studycrew_app;", self.sql)
        self.assertIn("GRANT USAGE ON SCHEMA public TO studycrew_app;", self.sql)
        self.assertNotRegex(
            self.sql,
            r"(?i)GRANT\s+(?:ALL|[^;]*\b(?:CREATE|TEMPORARY|TEMP)\b)[^;]*TO studycrew_app;",
        )
        self.assertTrue(self.sql.startswith(r"\set ON_ERROR_STOP on BEGIN;"))
        self.assertTrue(self.sql.endswith("COMMIT;"))

    def test_existing_and_future_rows_keep_the_required_application_capabilities(self):
        self.assertIn(
            "GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO studycrew_app;",
            self.sql,
        )
        self.assertIn(
            "ALTER DEFAULT PRIVILEGES FOR ROLE studycrew_migrator IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE ON TABLES TO studycrew_app;",
            self.sql,
        )
        self.assertIn(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO studycrew_app;", self.sql
        )

    def test_audit_rows_remain_append_only_after_general_row_grants(self):
        self.assertIn("SECURITY DEFINER SET search_path = pg_catalog", self.sql)
        self.assertIn(
            "REVOKE ALL ON FUNCTION public.prevent_studycrew_audit_mutation() FROM PUBLIC;",
            self.sql,
        )
        self.assertIn(
            "REVOKE ALL ON FUNCTION public.prevent_studycrew_audit_mutation() FROM studycrew_app;",
            self.sql,
        )
        general_grant_position = self.sql.index("GRANT SELECT, INSERT, UPDATE ON ALL TABLES")
        for table in AUDIT_TABLES:
            with self.subTest(table=table):
                self.assertIn(
                    f"BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW "
                    "EXECUTE FUNCTION public.prevent_studycrew_audit_mutation();",
                    self.sql,
                )
                revoke = f"REVOKE UPDATE, DELETE ON public.{table} FROM studycrew_app;"
                self.assertIn(revoke, self.sql)
                self.assertGreater(self.sql.index(revoke), general_grant_position)

    def test_nginx_accepts_the_largest_permitted_avatar_with_multipart_overhead(self):
        limits = re.findall(r"\bclient_max_body_size\s+(\d+)([kKmM]?)\s*;", self.nginx)
        self.assertEqual(len(limits), 1, "Keep one reviewed edge request-body limit.")
        amount, unit = limits[0]
        edge_limit = int(amount) * {"": 1, "k": 1024, "m": 1024 * 1024}[unit.lower()]
        # Real multipart encoding adds boundaries and headers to the file bytes.
        upload = SimpleUploadedFile("a" * 240 + ".jpg", b"x" * MAX_AVATAR_BYTES, "image/jpeg")
        multipart_body = encode_multipart(BOUNDARY, {"avatar": upload})
        self.assertGreater(len(multipart_body), MAX_AVATAR_BYTES)
        self.assertGreaterEqual(edge_limit, len(multipart_body))
        self.assertLessEqual(edge_limit, 3 * 1024 * 1024)
        self.assertEqual(MAX_AVATAR_BYTES, 2 * 1024 * 1024)

    def test_private_media_is_only_served_after_an_internal_authorised_handoff(self):
        location = re.search(r"location \^~ /protected-media/\s*\{([^}]+)\}", self.nginx)
        self.assertIsNotNone(location)
        self.assertRegex(location.group(1), r"\binternal\s*;")
        self.assertIn("alias /srv/studycrew/app/var/media/;", location.group(1))
        self.assertIn('Cache-Control "private, no-store" always;', location.group(1))
        self.assertNotRegex(self.nginx, r"location\s+(?:\^~\s+)?/media/")


class RuntimePermissionsVerifierGuards(SimpleTestCase):
    def test_verifier_is_fail_fast_and_read_only(self):
        source = sql_source(ROOT / "deploy/postgresql/verify_runtime_permissions.sql")
        self.assertTrue(source.startswith(r"\set ON_ERROR_STOP on BEGIN READ ONLY;"))
        self.assertTrue(source.endswith("ROLLBACK;"))
        self.assertIn("current_user <> 'studycrew_app'", source)
        self.assertIn("RAISE EXCEPTION", source)
        self.assertNotRegex(source, r"(?i)\b(?:GRANT|REVOKE|CREATE|ALTER|DROP)\s+(?:TABLE|ROLE|DATABASE|SCHEMA)\b")
        self.assertNotRegex(source, r"(?i)\b(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE\s+public\.)")

    def test_verifier_checks_effective_rights_and_protected_audits_not_only_grant_text(self):
        source = sql_source(ROOT / "deploy/postgresql/verify_runtime_permissions.sql")
        for table in DELETE_ALLOWLIST:
            self.assertIn(f"'{table}'", source)
        self.assertIn("has_table_privilege", source)
        self.assertIn("has_database_privilege", source)
        self.assertIn("has_schema_privilege", source)
        self.assertIn("pg_has_role", source)
        self.assertIn("role.rolname <> current_user", source)
        self.assertIn("rolsuper", source)
        self.assertIn("rolcreaterole", source)
        self.assertIn("rolcreatedb", source)
        self.assertIn("rolreplication", source)
        self.assertIn("rolbypassrls", source)
        self.assertIn("has_function_privilege", source)
        self.assertIn("pg_trigger", source)
        for table in AUDIT_TABLES:
            self.assertIn(f"'public.{table}'", source)
