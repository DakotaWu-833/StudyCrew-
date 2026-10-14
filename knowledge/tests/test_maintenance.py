"""Cleanup expires derived/transient AI data without deleting domain evidence."""

from datetime import timedelta
import hashlib
import io
from pathlib import Path
import re
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from api.tests.base import APIDomainTestCase
from knowledge.models import AssistantTaskReceipt, EmbeddingCache
from tasks.models import Task


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class KnowledgeMaintenanceTests(APIDomainTestCase):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.task = Task.objects.create(project=self.project, created_by=self.owner,
            title="Retained approved task", description="Project evidence stays retained.")

    def vector(self, age, label="vector"):
        row = EmbeddingCache.objects.create(project=self.project, model="test-embed",
            content_sha256=hashlib.sha256(label.encode()).hexdigest(), vector=[1, 0])
        EmbeddingCache.objects.filter(pk=row.pk).update(created_at=self.now - age)
        return row

    def receipt(self, age, label="receipt"):
        row = AssistantTaskReceipt.objects.create(project=self.project, user=self.member, task=self.task,
            token_digest=hashlib.sha256(label.encode()).hexdigest(), payload_sha256="b" * 64)
        AssistantTaskReceipt.objects.filter(pk=row.pk).update(created_at=self.now - age)
        return row

    def cleanup(self, **options):
        output = io.StringIO()
        with patch("knowledge.management.commands.purge_knowledge_data.timezone.now", return_value=self.now):
            call_command("purge_knowledge_data", stdout=output, **options)
        return output.getvalue()

    def test_default_and_explicit_dry_run_report_without_deleting(self):
        self.vector(timedelta(days=15))
        self.receipt(timedelta(days=31))
        for options in ({}, {"dry_run": True}):
            with self.subTest(options=options):
                output = self.cleanup(**options)
                self.assertIn("Dry run", output)
                self.assertIn("would delete vectors=1, receipts=1", output)
                self.assertEqual(EmbeddingCache.objects.count(), 1)
                self.assertEqual(AssistantTaskReceipt.objects.count(), 1)
                self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_execute_deletes_only_expired_rows_and_retains_tasks_projects_and_members(self):
        expired_vector = self.vector(timedelta(days=14, seconds=1), "expired")
        boundary_vector = self.vector(timedelta(days=14), "boundary")
        recent_vector = self.vector(timedelta(days=1), "recent")
        expired_receipt = self.receipt(timedelta(days=30, seconds=1), "expired")
        boundary_receipt = self.receipt(timedelta(days=30), "boundary")
        recent_receipt = self.receipt(timedelta(days=1), "recent")
        output = self.cleanup(execute=True)
        self.assertIn("Deleted vectors=1, receipts=1", output)
        self.assertFalse(EmbeddingCache.objects.filter(pk=expired_vector.pk).exists())
        self.assertFalse(AssistantTaskReceipt.objects.filter(pk=expired_receipt.pk).exists())
        self.assertEqual(set(EmbeddingCache.objects.values_list("pk", flat=True)), {boundary_vector.pk, recent_vector.pk})
        self.assertEqual(set(AssistantTaskReceipt.objects.values_list("pk", flat=True)), {boundary_receipt.pk, recent_receipt.pk})
        self.assertTrue(Task.objects.filter(pk=self.task.pk, description="Project evidence stays retained.").exists())
        self.assertTrue(type(self.project).objects.filter(pk=self.project.pk).exists())
        self.assertEqual(self.project.memberships.count(), 2)

    def test_custom_retention_overrides_are_applied(self):
        self.vector(timedelta(days=3))
        self.receipt(timedelta(days=4))
        self.cleanup(execute=True)
        self.assertEqual(EmbeddingCache.objects.count(), 1)
        self.assertEqual(AssistantTaskReceipt.objects.count(), 1)
        self.cleanup(execute=True, embedding_days=2, receipt_days=3)
        self.assertEqual(EmbeddingCache.objects.count(), 0)
        self.assertEqual(AssistantTaskReceipt.objects.count(), 0)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_limit_bounds_each_table_and_deletes_oldest_first(self):
        vectors = [self.vector(timedelta(days=20 + index), str(index)) for index in range(3)]
        receipts = [self.receipt(timedelta(days=40 + index), str(index)) for index in range(3)]
        preview = self.cleanup(limit=2)
        self.assertIn("would delete vectors=2, receipts=2", preview)
        self.cleanup(execute=True, limit=2)
        self.assertEqual(list(EmbeddingCache.objects.values_list("pk", flat=True)), [vectors[0].pk])
        self.assertEqual(list(AssistantTaskReceipt.objects.values_list("pk", flat=True)), [receipts[0].pk])
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_receipt_failure_rolls_back_vector_deletion(self):
        self.vector(timedelta(days=15))
        self.receipt(timedelta(days=31))
        from django.db.models import QuerySet
        original = QuerySet.delete
        def failing_delete(query):
            if query.model is AssistantTaskReceipt:
                raise DatabaseError("Simulated missing cleanup privilege")
            return original(query)
        with patch("django.db.models.QuerySet.delete", failing_delete), self.assertRaises(DatabaseError):
            self.cleanup(execute=True)
        self.assertEqual(EmbeddingCache.objects.count(), 1)
        self.assertEqual(AssistantTaskReceipt.objects.count(), 1)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_invalid_retention_and_limits_cannot_delete_rows(self):
        self.vector(timedelta(days=15))
        invalid = ({"embedding_days": 0}, {"receipt_days": 0}, {"embedding_days": 3651},
                   {"receipt_days": True}, {"limit": 0}, {"limit": 10001}, {"limit": True},
                   {"execute": True, "dry_run": True})
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.cleanup(**options)
        self.assertEqual(EmbeddingCache.objects.count(), 1)
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())


class KnowledgeCleanupPermissionTests(SimpleTestCase):
    root = Path(__file__).resolve().parents[2]

    def test_launch_delete_grants_exactly_match_verifier_allowlist(self):
        repository = self.root
        grants_sql = (repository / "deployment/postgresql/launch-permissions.sql").read_text(encoding="utf-8")
        verifier_sql = (repository / "deployment/postgresql/verify-launch-permissions.sql").read_text(encoding="utf-8")
        grants = re.search(r"GRANT DELETE ON TABLE\s+(.*?)\s+TO studycrew_app;", grants_sql, re.S).group(1)
        allowlist = re.search(r"delete_allowlist constant text\[\] := ARRAY\[(.*?)\];", verifier_sql, re.S).group(1)
        actual = {table.strip() for table in grants.split(",")}
        verified = set(re.findall(r"'(public\.[a-z_]+)'", allowlist))
        self.assertEqual(actual, verified)
        self.assertEqual({table for table in actual if table.startswith("public.knowledge_")},
                         {"public.knowledge_embeddingcache", "public.knowledge_assistanttaskreceipt"})
        for protected in ("public.tasks_task", "public.tasks_taskcomment", "public.projects_project",
                          "public.meetings_meeting", "public.accounts_user", "public.activity_activityevent",
                          "public.activity_siteauditevent", "public.operations_operationaudit",
                          "public.coordination_coordinationevent", "public.coordination_claimreview"):
            self.assertNotIn(protected, actual)
        self.assertIn("REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM studycrew_app;", grants_sql)
        self.assertIn("BEGIN READ ONLY;", verifier_sql)
        self.assertNotRegex(grants_sql, r"(?i)GRANT\s+DELETE\s+ON\s+ALL TABLES")
