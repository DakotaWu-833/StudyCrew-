"""Only a fresh, user-bound approval may turn an assistant draft into a task."""

from datetime import timedelta
import hashlib
import json
import tempfile
import time
from unittest.mock import patch
import zlib

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from activity.models import ActivityEvent
from api.tests.base import APIDomainTestCase
from coordination.models import MeetingRecord
from documents_store import services as file_services
from documents_store.models import ProjectDocument
from documents_store.storage import blob_path
from knowledge import actions, agent, services
from knowledge.models import AssistantTaskReceipt
from meetings.models import Meeting
from projects.models import Project, ProjectMembership
from tasks.models import Task

UNSET = object()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    OPERATIONS_RATE_LIMITS=False, PROJECT_FILES_REQUIRE_SCAN=False, PROJECT_FILES_CLAMSCAN="",
    RAG_PROVIDER="disabled", RAG_RETRIEVAL_MODE="bm25",
)
class AssistantTaskApprovalTests(APIDomainTestCase):
    title = "Complete an independent security review"
    description = "Check the project report against its requirements."

    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        setting = override_settings(MEDIA_ROOT=directory.name)
        setting.enable()
        self.addCleanup(setting.disable)

    def upload(self, text="Nebulawork PRIVATE-EXCERPT requires a security review.", document=None):
        return file_services.upload(
            actor=self.owner, project_id=self.project.pk, document_id=document.pk if document else None,
            values={"expected_revision": document.revision} if document else {"title": "Assignment requirements"},
            upload=SimpleUploadedFile("requirements.txt", text.encode(), content_type="text/plain"),
        )

    def signed_drafts(self, rows=None, user=None):
        if rows is None:
            _, rows = services._retrieve(user or self.member, self.project.pk, "Nebulawork", 5)
        return actions.sign_drafts(user or self.member, self.project.pk, [{
            "title": self.title, "description": self.description, "source_citations": ["S1"],
        }], rows)

    def token(self, rows=None):
        return self.signed_drafts(rows)[0]["approval_token"]

    def approve(self, token, *, user=None, project=None, title=UNSET, description=UNSET):
        return actions.approve_task(
            user or self.member, (project or self.project).pk, token,
            self.title if title is UNSET else title,
            self.description if description is UNSET else description,
        )

    def url(self):
        return f"/api/v1/knowledge/projects/{self.project.pk}/assistant/tasks/"

    def payload(self, token, **changes):
        return {"approval_token": token, "title": self.title, "description": self.description, **changes}

    def token_payload(self, token):
        encoded = token.split(":", 1)[0]
        raw = signing.b64_decode(encoded.lstrip(".").encode())
        return zlib.decompress(raw) if encoded.startswith(".") else raw

    def assert_no_created_task(self):
        self.assertEqual(Task.objects.count(), 0)
        self.assertEqual(AssistantTaskReceipt.objects.count(), 0)

    def test_signing_is_read_only_and_token_contains_no_raw_source_excerpt(self):
        self.upload()
        draft = self.signed_drafts()[0]
        self.assertTrue(draft["can_create"])
        token = draft["approval_token"]
        self.assertTrue(token)
        raw = self.token_payload(token)
        self.assertNotIn(b"PRIVATE-EXCERPT", raw)
        self.assertNotIn(b"Nebulawork", raw)
        self.assert_no_created_task()

    def test_signed_but_malformed_references_are_rejected_without_server_errors(self):
        self.upload()
        original = signing.loads(self.token(), salt=actions.SALT)
        reference = original["sources"][0]
        invalid = [None, {}, {**reference, "source_id": "not-a-uuid"},
                   {**reference, "snapshot": "invalid"}, {**reference, "citation": "S99"},
                   {**reference, "title": "x" * 151}, {**reference, "kind": "unknown"}]
        for row in invalid:
            with self.subTest(reference=row):
                token = signing.dumps({**original, "sources": [row]}, salt=actions.SALT)
                with self.assertRaises(ValidationError):
                    self.approve(token)
        self.assert_no_created_task()

    def test_explicit_approval_creates_task_through_normal_audited_service(self):
        document = self.upload()
        token = self.token()
        result = self.approve(token)
        self.assertTrue(result["created"])
        task = Task.objects.get(pk=result["task_id"])
        self.assertEqual(task.project_id, self.project.pk)
        self.assertEqual(task.created_by_id, self.member.pk)
        self.assertEqual(task.title, self.title)
        self.assertIn(self.description, task.description)
        self.assertIn(str(document.pk), task.description)
        self.assertNotIn("PRIVATE-EXCERPT", task.description)
        self.assertTrue(result["task_url"].startswith("/"))
        event = ActivityEvent.objects.get(event_type="task_created", target_id=task.pk)
        self.assertEqual(event.actor_id, self.member.pk)
        self.assertEqual(event.project_id, self.project.pk)
        receipt = AssistantTaskReceipt.objects.get(task=task)
        self.assertEqual(receipt.token_digest, hashlib.sha256(token.encode()).hexdigest())
        self.assertEqual(len(receipt.payload_sha256), 64)
        self.assertNotIn(token, json.dumps(list(AssistantTaskReceipt.objects.values()), default=str))

    def test_user_can_edit_title_and_description_before_first_approval(self):
        self.upload()
        result = self.approve(self.token(), title="Review the final report", description="Review the revised requirements.")
        task = Task.objects.get(pk=result["task_id"])
        self.assertEqual(task.title, "Review the final report")
        self.assertIn("Review the revised requirements.", task.description)

    def test_identical_retry_returns_receipt_without_duplicate_task_or_audit(self):
        self.upload()
        token = self.token()
        first = self.approve(token)
        again = self.approve(token)
        self.assertTrue(first["created"])
        self.assertFalse(again["created"])
        self.assertEqual(first["task_id"], again["task_id"])
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(AssistantTaskReceipt.objects.count(), 1)
        self.assertEqual(ActivityEvent.objects.filter(event_type="task_created").count(), 1)

    def test_retry_with_edited_payload_cannot_change_created_task(self):
        self.upload()
        token = self.token()
        self.approve(token)
        before = list(Task.objects.values())
        with self.assertRaises(ValidationError):
            self.approve(token, title="An edited retry title")
        with self.assertRaises(ValidationError):
            self.approve(token, description="An edited retry description")
        self.assertEqual(list(Task.objects.values()), before)
        self.assertEqual(AssistantTaskReceipt.objects.count(), 1)

    def test_tampered_and_expired_real_signatures_are_rejected(self):
        self.upload()
        valid = self.token()
        with self.assertRaises(ValidationError):
            self.approve(valid + "tampered")
        with patch("django.core.signing.time.time", return_value=1):
            expired = self.token()
        with self.assertRaises(ValidationError):
            self.approve(expired)
        self.assert_no_created_task()

    def test_token_is_bound_to_actor_and_project(self):
        self.upload()
        token = self.token()
        other = Project.objects.create(name="Other approved project", created_by=self.member)
        ProjectMembership.objects.create(project=other, user=self.member, role="owner")
        with self.assertRaises(ValidationError):
            self.approve(token, user=self.owner)
        with self.assertRaises(ValidationError):
            self.approve(token, project=other)
        self.assert_no_created_task()

    def test_removed_member_cannot_use_previously_valid_token(self):
        self.upload()
        token = self.token()
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
        with self.assertRaises(Http404):
            self.approve(token)
        self.assert_no_created_task()

    def test_disabled_or_closed_actor_is_refreshed_from_database(self):
        self.upload()
        token = self.token()
        for change in ({"is_active": False}, {"closed_at": timezone.now()}):
            with self.subTest(change=change):
                get_user_model().objects.filter(pk=self.member.pk).update(**change)
                with self.assertRaises(Http404):
                    self.approve(token)
                get_user_model().objects.filter(pk=self.member.pk).update(is_active=True, closed_at=None)
        self.assert_no_created_task()

    def test_archived_project_rejects_creation_and_marks_drafts_read_only(self):
        self.upload()
        token = self.token()
        Project.objects.filter(pk=self.project.pk).update(archived_at=timezone.now())
        with self.assertRaises(ValidationError):
            self.approve(token)
        draft = self.signed_drafts()[0]
        self.assertFalse(draft["can_create"])
        self.assertEqual(draft["approval_token"], "")
        self.assert_no_created_task()

    def test_updated_or_removed_file_invalidates_pending_approval(self):
        document = self.upload()
        token = self.token()
        self.upload("Nebulawork revised requirements", document=document)
        with self.assertRaises(ValidationError):
            self.approve(token)
        updated_token = self.token()
        ProjectDocument.objects.filter(pk=document.pk).update(removed_at=timezone.now())
        with self.assertRaises(ValidationError):
            self.approve(updated_token)
        self.assert_no_created_task()

    def test_tampered_or_scan_unavailable_file_invalidates_approval(self):
        document = self.upload()
        token = self.token()
        version = document.versions.get()
        with override_settings(PROJECT_FILES_REQUIRE_SCAN=True), self.assertRaises(ValidationError):
            self.approve(token)
        blob_path(version.storage_key).write_bytes(b"Changed file content")
        with self.assertRaises(ValidationError):
            self.approve(token)
        self.assert_no_created_task()

    def test_meeting_edit_or_cancellation_invalidates_pending_approval(self):
        now = timezone.now()
        meeting = Meeting.objects.create(project=self.project, organiser=self.owner, title="Report planning",
            starts_at=now - timedelta(hours=2), ends_at=now - timedelta(hours=1))
        record = MeetingRecord.objects.create(meeting=meeting, minutes="Nebulawork review decision", version=1)
        token = self.token()
        MeetingRecord.objects.filter(pk=record.pk).update(minutes="Nebulawork changed decision", version=2)
        with self.assertRaises(ValidationError):
            self.approve(token)
        token = self.token()
        Meeting.objects.filter(pk=meeting.pk).update(cancelled_at=timezone.now())
        with self.assertRaises(ValidationError):
            self.approve(token)
        self.assert_no_created_task()

    def test_task_evidence_edit_invalidates_pending_approval(self):
        task = Task.objects.create(project=self.project, created_by=self.owner, title="Review the report", description="Original instructions")
        tools = agent.ProjectTools(self.member, self.project.pk, time.monotonic() + 22)
        tools.execute("list_project_tasks", {"status": "all"})
        token = self.token(tools.sources)
        Task.objects.filter(pk=task.pk).update(description="Changed instructions")
        with self.assertRaises(ValidationError):
            self.approve(token)
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(AssistantTaskReceipt.objects.count(), 0)

    def test_task_source_token_hashes_private_description_and_blocker_text(self):
        Task.objects.create(project=self.project, created_by=self.owner, title="Review the report",
            description="TASK-PRIVATE-DESCRIPTION", status="blocked", blocker_note="TASK-PRIVATE-BLOCKER")
        tools = agent.ProjectTools(self.member, self.project.pk, time.monotonic() + 22)
        tools.execute("list_project_tasks", {"status": "all"})
        raw = self.token_payload(self.token(tools.sources))
        self.assertNotIn(b"TASK-PRIVATE-DESCRIPTION", raw)
        self.assertNotIn(b"TASK-PRIVATE-BLOCKER", raw)

    def test_duplicate_current_title_is_rejected(self):
        self.upload()
        token = self.token()
        Task.objects.create(project=self.project, created_by=self.owner, title=self.title.upper())
        with self.assertRaises(ValidationError):
            self.approve(token)
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(AssistantTaskReceipt.objects.count(), 0)

    def test_activity_failure_rolls_back_task_and_receipt(self):
        self.upload()
        token = self.token()
        with patch("activity.services.record_event", side_effect=RuntimeError("Failed audit")), self.assertRaises(RuntimeError):
            self.approve(token)
        self.assert_no_created_task()

    def test_service_rejects_invalid_confirmed_fields_without_writes(self):
        self.upload()
        token = self.token()
        invalid = ({"title": "x"}, {"title": "x" * 121}, {"title": 123},
                   {"description": "x" * 2001}, {"description": None})
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.approve(token, **fields)
        self.assert_no_created_task()

    def test_api_success_and_retry_have_private_responses(self):
        self.upload()
        token = self.token()
        self.authenticate(self.member)
        response = self.client.post(self.url(), self.payload(token), format="json")
        self.assertIn(response.status_code, (200, 201), response.content)
        self.assertTrue(response.json()["created"])
        self.assertIn("no-store", response["Cache-Control"])
        again = self.client.post(self.url(), self.payload(token), format="json")
        self.assertEqual(again.status_code, 200, again.content)
        self.assertFalse(again.json()["created"])
        self.assertEqual(Task.objects.count(), 1)

    def test_completed_agent_proposal_is_unsaved_until_explicit_user_approval(self):
        self.upload()
        turns = [
            {"content": "", "tool_calls": [{"id": "search-1", "name": "search_project_sources", "arguments": {"query": "Nebulawork"}}]},
            {"content": "", "tool_calls": [{"id": "draft-1", "name": "propose_tasks", "arguments": {"tasks": [{"title": self.title, "description": self.description, "source_citations": ["S1"]}]}}]},
            {"content": "An independent review is suggested by the requirements [S1].", "tool_calls": []},
        ]
        with override_settings(RAG_PROVIDER="ollama", RAG_BASE_URL="http://127.0.0.1:11434", RAG_MODEL="test-model"), patch("knowledge.agent.providers.agent_chat", side_effect=turns):
            result = agent.run(self.member, self.project.pk, "Propose an action for the Nebulawork report")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["drafts"]), 1)
        self.assertTrue(result["drafts"][0]["approval_token"])
        self.assert_no_created_task()
        self.approve(result["drafts"][0]["approval_token"])
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(AssistantTaskReceipt.objects.count(), 1)

    def test_api_requires_mfa_and_csrf_before_task_creation(self):
        self.upload()
        token = self.token()
        self.assertEqual(self.client.post(self.url(), self.payload(token), format="json").status_code, 401)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(self.url(), self.payload(token), format="json").status_code, 401)
        csrf = APIClient(enforce_csrf_checks=True)
        self.authenticate(self.member, client=csrf)
        self.assertEqual(csrf.post(self.url(), self.payload(token), format="json").status_code, 403)
        self.assert_no_created_task()

    def test_api_strict_body_cannot_select_priority_assignee_or_project(self):
        self.upload()
        token = self.token()
        self.authenticate(self.member)
        invalid = ({}, self.payload(token, priority="urgent"), self.payload(token, assignee_id=str(self.owner.pk)),
                   self.payload(token, project_id=str(self.project.pk)), self.payload(token, title=123),
                   self.payload(token, approval_token=123), self.payload(token, description="x" * 2001))
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.post(self.url(), payload, format="json")
                self.assertEqual(response.status_code, 400, response.content)
        self.assert_no_created_task()
