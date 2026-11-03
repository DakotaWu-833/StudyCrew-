"""Compile actual service locks with PostgreSQL without opening a PG connection.

SQLite allows FOR UPDATE joins that PostgreSQL rejects when a selected relation
is nullable. These tests execute the use case on the isolated Django test DB and
compile its real locking QuerySet with the PostgreSQL backend. They establish
the SQL lock target, not PostgreSQL runtime or concurrency performance.
"""
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.models.query import QuerySet
from django.utils import timezone

from api.tests.base import APIDomainTestCase
from coordination.models import CalendarSubscription
from coordination.services import consume_subscription, token_digest
from offline_sync.services import synchronize
from operations import discussion_services
from operations.models import PostReport
from tasks.models import Task


@contextmanager
def postgres_lock_sql(model):
    """Observe the service query rather than rebuilding its implementation."""
    postgres = DatabaseWrapper({"NAME": "compile_only", "TIME_ZONE": None}, alias="lock_compile_only")
    statements = []
    original_fetch = QuerySet._fetch_all

    def capture(queryset):
        if queryset.model is model and queryset.query.select_for_update:
            sql, _params = queryset.query.get_compiler(connection=postgres).as_sql()
            statements.append(sql)
        return original_fetch(queryset)

    # SQLCompiler checks transaction state. No PostgreSQL connection is opened
    # or SQL executed against one; application calls still use the test DB.
    with patch.object(postgres, "get_autocommit", return_value=False), patch.object(QuerySet, "_fetch_all", capture):
        yield statements
    if postgres.connection is not None:
        raise AssertionError("Compilation unexpectedly opened a PostgreSQL connection")


class NullableJoinLockTargetsTests(APIDomainTestCase):
    def assert_root_lock_with_nullable_join(self, statements, model, *nullable_tables):
        self.assertTrue(statements, "The real service must execute its locking queryset.")
        for sql in statements:
            for table in nullable_tables:
                self.assertIn(f'LEFT OUTER JOIN "{table}"', sql)
            self.assertTrue(
                sql.endswith(f'FOR UPDATE OF "{model._meta.db_table}"'),
                "Locking an outer-joined nullable relation is rejected by PostgreSQL: " + sql,
            )

    def test_offline_sync_locks_task_without_locking_nullable_author_profile(self):
        task = Task.objects.create(project=self.project, created_by=self.owner, title="Offline SQL lock target")
        with postgres_lock_sql(Task) as statements:
            updated, duplicate = synchronize(
                actor=self.owner, task_id=task.pk, mutation_id=uuid4(),
                expected_updated_at=task.updated_at, changes={"title": "Offline edit applied"},
            )
        # update_task also fetches Task with a lock but without the nullable
        # profile; examine the query that actually includes that outer join.
        nullable_queries = [sql for sql in statements if 'LEFT OUTER JOIN "accounts_profile"' in sql]
        self.assert_root_lock_with_nullable_join(nullable_queries, Task, "accounts_profile")
        self.assertFalse(duplicate)
        self.assertEqual(updated.title, "Offline edit applied")

    def test_personal_calendar_feed_locks_subscription_without_nullable_project_or_profile(self):
        token = "calendar-test-" + "x" * 40
        subscription = CalendarSubscription.objects.create(
            user=self.owner, project=None, token_hash=token_digest(token),
            expires_at=timezone.now() + timedelta(days=1),
        )
        with postgres_lock_sql(CalendarSubscription) as statements:
            consumed = consume_subscription(token)
        self.assert_root_lock_with_nullable_join(
            statements, CalendarSubscription, "projects_project", "accounts_profile",
        )
        self.assertEqual(consumed.pk, subscription.pk)
        self.assertEqual(consumed.request_count, 1)

    def test_post_report_moderation_locks_report_without_nullable_reply(self):
        post = discussion_services.save_post(self.owner, self.project, {"title": "Reported post", "body": "Review this post."})
        report = discussion_services.report_content(self.member, post, "A concern about this post", reply=None)
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.owner.user_permissions.add(
            Permission.objects.get(codename="moderate_reports"),
            Permission.objects.get(codename="manage_user_status"),
        )
        with postgres_lock_sql(PostReport) as statements:
            moderated = discussion_services.moderate_report(self.owner, report, True, "Removed after review")
        self.assert_root_lock_with_nullable_join(statements, PostReport, "operations_postreply")
        moderated.post.refresh_from_db()
        self.assertIsNotNone(moderated.post.removed_at)
