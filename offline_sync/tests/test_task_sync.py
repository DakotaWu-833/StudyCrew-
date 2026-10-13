"""Offline mutations preserve permission, atomicity, and optimistic versions."""
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.readiness_services import close_account
from activity.models import ActivityEvent
from api.tests.base import APIDomainTestCase
from campus.models import ChecklistItem, TaskPlan
from offline_sync import services
from offline_sync.models import TaskSyncReceipt
from projects.models import ProjectMembership
from tasks.models import Task
from tasks.services import replace_assignees, update_task


@override_settings(OPERATIONS_RATE_LIMITS=False)
class OfflineTaskSyncTests(APIDomainTestCase):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(project=self.project, created_by=self.owner, title="Original offline task", description="Original description")

    def url(self, task=None):
        return f"/api/v1/offline/tasks/{(task or self.task).pk}/sync/"

    def payload(self, changes=None, user=None):
        return {"mutation_id": str(uuid4()), "expected_user_id": str((user or self.owner).pk), "expected_updated_at": self.task.updated_at.isoformat(), "changes": changes or {"title": "Edited offline task"}}

    def sync(self, changes=None, actor=None, nonce=None, base=None, task=None):
        task = task or self.task
        return services.synchronize(actor=actor or self.owner, task_id=task.pk, mutation_id=nonce or uuid4(), expected_updated_at=base or task.updated_at, changes=changes or {"title": "Edited offline task"})

    def assert_original_and_no_write_evidence(self):
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Original offline task")
        self.assertEqual(self.task.description, "Original description")
        self.assertEqual(self.task.status, "todo")
        self.assertFalse(TaskSyncReceipt.objects.exists())
        self.assertFalse(ActivityEvent.objects.filter(target_id=self.task.pk).exists())

    def test_api_requires_mfa_and_current_membership_before_edit(self):
        payload = self.payload()
        self.assertEqual(self.client.post(self.url(), payload, format="json").status_code, 401)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.url(), payload, format="json").status_code, 401)
        self.authenticate(self.outsider)
        payload["expected_user_id"] = str(self.outsider.pk)
        response = self.client.post(self.url(), payload, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Original description", response.content.decode())
        self.assert_original_and_no_write_evidence()

    def test_browser_csrf_is_required_and_valid_cookie_allows_sync(self):
        client = APIClient(enforce_csrf_checks=True)
        self.authenticate(self.owner, client=client)
        payload = self.payload()
        self.assertEqual(client.post(self.url(), payload, format="json").status_code, 403)
        self.assert_original_and_no_write_evidence()
        self.assertEqual(client.get("/account/profile/").status_code, 200)
        response = client.post(self.url(), payload, format="json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["duplicate"])

    def test_same_browser_other_account_cannot_apply_previous_users_queue(self):
        payload = self.payload()
        self.authenticate(self.member)
        response = self.client.post(self.url(), payload, format="json")
        self.assertEqual(response.status_code, 403, response.content)
        self.assert_original_and_no_write_evidence()

    def test_atomic_detail_and_status_change_creates_one_receipt_and_two_events(self):
        updated, duplicate = self.sync({"title": "Working offline draft", "description": "Locally revised description", "status": "in_progress"})
        self.assertFalse(duplicate)
        self.assertEqual(updated.title, "Working offline draft")
        self.assertEqual(updated.description, "Locally revised description")
        self.assertEqual(updated.status, "in_progress")
        self.assertEqual(TaskSyncReceipt.objects.filter(task=self.task, user=self.owner).count(), 1)
        self.assertCountEqual(ActivityEvent.objects.filter(target_id=self.task.pk).values_list("event_type", flat=True), ["task_updated", "task_status_changed"])

    def test_invalid_transition_rolls_back_detail_change_receipt_and_activity(self):
        base = self.task.updated_at
        with self.assertRaises(ValidationError):
            self.sync({"title": "Must not survive failure", "status": "blocked", "blocker_note": ""})
        self.assert_original_and_no_write_evidence()
        self.assertEqual(self.task.updated_at, base)

    def test_denied_transition_rolls_back_otherwise_permitted_member_detail_edit(self):
        self.authenticate(self.member)
        response = self.client.post(self.url(), self.payload({"title": "Member detail before denied status", "status": "in_progress"}, user=self.member), format="json")
        self.assertEqual(response.status_code, 403, response.content)
        self.assert_original_and_no_write_evidence()

    def test_completion_validation_rolls_back_details_and_status(self):
        ChecklistItem.objects.create(task=self.task, text="Required evidence still missing")
        with self.assertRaises(ValidationError):
            self.sync({"title": "Cannot complete yet", "status": "done"})
        self.assert_original_and_no_write_evidence()

    def test_official_deadline_is_enforced_without_partial_changes(self):
        official = timezone.now() + timedelta(days=2)
        TaskPlan.objects.create(task=self.task, official_due_at=official)
        with self.assertRaises(ValidationError):
            self.sync({"title": "Cannot bypass deadline", "due_at": official + timedelta(hours=1)})
        self.assert_original_and_no_write_evidence()

    def test_conflict_returns_current_snapshot_including_assignees(self):
        self.authenticate(self.owner)
        payload = self.payload()
        replace_assignees(task=self.task, actor=self.owner, assignee_ids=[self.member.pk])
        update_task(task=self.task, actor=self.owner, data={"title": "Latest server task", "description": "Latest server description"})
        response = self.client.post(self.url(), payload, format="json")
        self.assertEqual(response.status_code, 409, response.content)
        body = response.json()
        self.assertEqual(body["error"]["code"], "edit_conflict")
        self.assertEqual(body["current"]["title"], "Latest server task")
        self.assertEqual(body["current"]["description"], "Latest server description")
        self.assertEqual([row["id"] for row in body["current"]["assignees"]], [str(self.member.pk)])
        self.task.refresh_from_db()
        self.assertEqual(datetime.fromisoformat(body["current"]["updated_at"]), self.task.updated_at)
        self.assertFalse(TaskSyncReceipt.objects.exists())

    def test_conflict_snapshot_rechecks_account_and_membership_after_sync_failure(self):
        self.authenticate(self.member)
        for changed in ["membership", "account"]:
            def revoked_during_attempt(**kwargs):
                if changed == "membership":
                    ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
                else:
                    get_user_model().objects.filter(pk=self.member.pk).update(closed_at=timezone.now())
                raise services.EditConflict()
            with patch("api.offline_views.synchronize", side_effect=revoked_during_attempt):
                response = self.client.post(self.url(), self.payload(user=self.member), format="json")
            self.assertEqual(response.status_code, 403, response.content)
            self.assertNotIn("current", response.json())
            self.assertNotIn("Original description", response.content.decode())
            ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=None)
            get_user_model().objects.filter(pk=self.member.pk).update(closed_at=None)
        self.assert_original_and_no_write_evidence()

    def test_failure_to_save_receipt_rolls_back_successful_details_and_transition(self):
        with patch("offline_sync.services.TaskSyncReceipt.objects.create", side_effect=ValidationError("Receipt storage unavailable")):
            with self.assertRaises(ValidationError):
                self.sync({"title": "Changes before final write", "status": "in_progress"})
        self.assert_original_and_no_write_evidence()

    def test_idempotent_retry_after_later_server_edit_returns_current_without_overwrite(self):
        self.authenticate(self.owner)
        payload = self.payload({"title": "First offline edit", "status": "in_progress"})
        first = self.client.post(self.url(), payload, format="json")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertFalse(first.json()["duplicate"])
        self.task.refresh_from_db()
        update_task(task=self.task, actor=self.owner, data={"title": "Later teammate revision"})
        events_before = ActivityEvent.objects.filter(target_id=self.task.pk).count()
        retry = self.client.post(self.url(), payload, format="json")
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertTrue(retry.json()["duplicate"])
        self.assertEqual(retry.json()["task"]["title"], "Later teammate revision")
        self.assertEqual(TaskSyncReceipt.objects.count(), 1)
        self.assertEqual(ActivityEvent.objects.filter(target_id=self.task.pk).count(), events_before)

    def test_mutation_nonce_cannot_be_reused_for_changed_payload_or_other_task(self):
        nonce, base = uuid4(), self.task.updated_at
        self.sync(nonce=nonce, base=base)
        with self.assertRaises(ValidationError):
            self.sync({"title": "Changed nonce payload"}, nonce=nonce, base=base)
        other = Task.objects.create(project=self.project, created_by=self.owner, title="Another queued task")
        with self.assertRaises(ValidationError):
            self.sync(nonce=nonce, task=other)
        self.assertEqual(TaskSyncReceipt.objects.count(), 1)
        other.refresh_from_db()
        self.assertEqual(other.title, "Another queued task")

    def test_same_mutation_uuid_is_independent_between_users(self):
        nonce = uuid4()
        self.sync(nonce=nonce)
        self.task.refresh_from_db()
        updated, duplicate = self.sync({"description": "Other user queued detail"}, actor=self.member, nonce=nonce)
        self.assertFalse(duplicate)
        self.assertEqual(updated.description, "Other user queued detail")
        self.assertEqual(TaskSyncReceipt.objects.count(), 2)

    def test_member_can_change_details_and_assignee_can_transition(self):
        self.sync({"description": "Permitted member detail"}, actor=self.member)
        replace_assignees(task=self.task, actor=self.owner, assignee_ids=[self.member.pk])
        self.task.refresh_from_db()
        updated, _ = self.sync({"status": "blocked", "blocker_note": "Waiting for reviewed source"}, actor=self.member)
        self.assertEqual(updated.status, "blocked")
        self.assertEqual(updated.blocker_note, "Waiting for reviewed source")
        self.task.refresh_from_db()
        updated, _ = self.sync({"status": "in_progress"}, actor=self.member)
        self.assertEqual(updated.blocker_note, "")

    def test_removed_members_cannot_receive_conflict_snapshot_or_retry_receipt(self):
        nonce, base = uuid4(), self.task.updated_at
        self.sync(actor=self.member, nonce=nonce, base=base)
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.sync(actor=self.member, nonce=nonce, base=base)
        self.authenticate(self.member)
        response = self.client.post(self.url(), self.payload(user=self.member), format="json")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("current", response.json())
        self.assertEqual(TaskSyncReceipt.objects.count(), 1)

    def test_archived_project_and_task_are_read_only_even_for_idempotent_retry(self):
        nonce, base = uuid4(), self.task.updated_at
        self.sync(nonce=nonce, base=base)
        for model, obj in [(type(self.project), self.project), (Task, self.task)]:
            model.objects.filter(pk=obj.pk).update(archived_at=timezone.now())
            with self.assertRaises(ValidationError):
                self.sync(nonce=nonce, base=base)
            model.objects.filter(pk=obj.pk).update(archived_at=None)
        self.assertEqual(TaskSyncReceipt.objects.count(), 1)

    def test_database_closed_or_inactive_identity_rejects_stale_loaded_actor(self):
        for changes in [{"closed_at": timezone.now()}, {"is_active": False}]:
            get_user_model().objects.filter(pk=self.owner.pk).update(**changes)
            with self.assertRaises(PermissionDenied):
                self.sync()
            get_user_model().objects.filter(pk=self.owner.pk).update(is_active=True, closed_at=None)
        self.assert_original_and_no_write_evidence()

    def test_assignment_changes_invalidate_queued_snapshot_but_noop_does_not(self):
        base = self.task.updated_at
        replace_assignees(task=self.task, actor=self.owner, assignee_ids=[])
        self.task.refresh_from_db()
        self.assertEqual(self.task.updated_at, base)
        replace_assignees(task=self.task, actor=self.owner, assignee_ids=[self.member.pk])
        self.task.refresh_from_db()
        self.assertGreater(self.task.updated_at, base)
        with self.assertRaises(services.EditConflict):
            self.sync(base=base)
        self.assertFalse(TaskSyncReceipt.objects.exists())

    def test_closing_assignee_invalidates_task_version_and_removes_receipts(self):
        replace_assignees(task=self.task, actor=self.owner, assignee_ids=[self.member.pk])
        self.task.refresh_from_db()
        self.sync({"description": "Member offline notes"}, actor=self.member)
        self.task.refresh_from_db()
        base = self.task.updated_at
        close_account(user=self.member, confirmation="CLOSE MY ACCOUNT")
        self.task.refresh_from_db()
        self.assertGreater(self.task.updated_at, base)
        self.assertFalse(TaskSyncReceipt.objects.filter(user=self.member).exists())
        self.assertFalse(self.task.assignments.filter(user=self.member).exists())
        with self.assertRaises(services.EditConflict):
            self.sync(base=base)

    def test_empty_or_invalid_fields_and_user_scope_are_rejected_before_writes(self):
        self.authenticate(self.owner)
        for changes in [{}, {"blocker_note": "Missing status"}, {"title": "ab"}, {"status": "invented"}, {"assignees": [str(self.member.pk)]}, {"description": "x" * 4001}]:
            payload = self.payload()
            payload["changes"] = changes
            with self.subTest(changes=list(changes)):
                self.assertEqual(self.client.post(self.url(), payload, format="json").status_code, 400)
        payload = self.payload()
        del payload["expected_user_id"]
        self.assertEqual(self.client.post(self.url(), payload, format="json").status_code, 400)
        self.assert_original_and_no_write_evidence()

    def test_missing_task_returns_404_without_receipt(self):
        with self.assertRaises(Http404):
            services.synchronize(actor=self.owner, task_id=uuid4(), mutation_id=uuid4(), expected_updated_at=self.task.updated_at, changes={"title": "Missing task attempt"})
        self.assertFalse(TaskSyncReceipt.objects.exists())

    def test_personal_receipts_have_only_own_identifiers_and_cleanup_expires_after_seven_days(self):
        self.sync(actor=self.member)
        self.task.refresh_from_db()
        self.sync({"description": "Owner queued change"})
        data = services.personal_data(self.member)
        self.assertEqual(len(data), 1)
        self.assertEqual(set(data[0]), {"task_id", "mutation_id", "applied_at"})
        TaskSyncReceipt.objects.filter(user=self.member).update(applied_at=timezone.now()-timedelta(days=8))
        self.assertEqual(services.cleanup_receipts(), 1)
        self.assertEqual(TaskSyncReceipt.objects.count(), 1)
        self.assertEqual(TaskSyncReceipt.objects.get().user, self.owner)

    @override_settings(OPERATIONS_RATE_LIMITS=True)
    def test_throttled_request_does_not_write_task_events_or_receipt(self):
        self.authenticate(self.owner)
        with patch("api.offline_views.consume_rate", return_value=False):
            self.assertEqual(self.client.post(self.url(), self.payload(), format="json").status_code, 429)
        self.assert_original_and_no_write_evidence()
