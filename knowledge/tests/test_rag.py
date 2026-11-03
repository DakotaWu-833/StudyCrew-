"""Project RAG security, evidence freshness, and user-visible API behavior."""

from datetime import timedelta
import io
import json
import subprocess
import tempfile
from unittest.mock import patch
import zipfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from api.tests.base import APIDomainTestCase
from coordination.models import MeetingRecord
from documents_store import services as file_services
from documents_store.models import DocumentVersion, ProjectDocument
from documents_store.storage import blob_path
from knowledge import providers, services
from meetings.models import Meeting
from projects.models import Project, ProjectMembership


def docx_bytes(text):
    """A minimal OOXML text document accepted by the existing upload validator."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("word/document.xml", f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


def pdf_bytes(text):
    """An ordinary one-page text PDF; no external renderer or network required."""
    content = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    OPERATIONS_RATE_LIMITS=False,
    PROJECT_FILES_REQUIRE_SCAN=False,
    PROJECT_FILES_CLAMSCAN="",
    RAG_PROVIDER="disabled",
    RAG_MODEL="",
    RAG_API_KEY="",
)
class ProjectRAGTests(APIDomainTestCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        setting = override_settings(MEDIA_ROOT=directory.name)
        setting.enable()
        self.addCleanup(setting.disable)

    def upload(self, text="Nebulawork report requires a security review.", *, name="requirements.txt", content_type="text/plain", project=None, document=None):
        payload = text.encode("utf-8") if isinstance(text, str) else text
        return file_services.upload(
            actor=self.owner,
            project_id=(project or self.project).pk,
            document_id=document.pk if document else None,
            values={"expected_revision": document.revision} if document else {"title": name},
            upload=SimpleUploadedFile(name, payload, content_type=content_type),
        )

    def record(self, minutes="Nebulawork report needs an independent security review.", *, project=None):
        now = timezone.now()
        meeting = Meeting.objects.create(
            project=project or self.project,
            organiser=self.owner,
            title="Report planning",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
        )
        return MeetingRecord.objects.create(meeting=meeting, minutes=minutes, decisions="", version=1)

    def search(self, question="Nebulawork", user=None, **kwargs):
        return services.search(user or self.member, self.project.pk, question, **kwargs)

    def ask(self, question="Nebulawork", user=None, **kwargs):
        return services.ask(user or self.member, self.project.pk, question, **kwargs)

    def url(self, operation=""):
        return f"/api/v1/knowledge/projects/{self.project.pk}/" + (f"{operation}/" if operation else "")

    def configured(self):
        return override_settings(RAG_PROVIDER="ollama", RAG_BASE_URL="http://127.0.0.1:11434", RAG_MODEL="test-model")

    def assert_no_private_paths(self, result):
        text = json.dumps(result, default=str)
        self.assertNotIn("storage_key", text)
        self.assertNotIn("private-project-files", text)
        self.assertNotIn("sha256", text)

    def test_file_evidence_has_clickable_versioned_citation_and_no_storage_details(self):
        document = self.upload()
        result = self.search()
        self.assertEqual(result["retrieval"], "bm25")
        self.assertEqual(len(result["sources"]), 1)
        source = result["sources"][0]
        self.assertEqual(source["citation"], "S1")
        self.assertEqual(source["kind"], "file")
        self.assertEqual(source["source_id"], str(document.pk))
        self.assertEqual(source["version"], 1)
        self.assertIn("security review", source["excerpt"])
        self.assertTrue(source["url"].startswith("/"))
        self.assertTrue(source["locator"])
        self.assert_no_private_paths(result)

    def test_cross_project_content_cannot_enter_results(self):
        other = Project.objects.create(name="Private project", created_by=self.owner)
        ProjectMembership.objects.create(project=other, user=self.owner, role="owner")
        self.upload("Nebulawork private revenue is 99999.", project=other)
        self.upload("Nebulawork report requires a security review.")
        result = self.search()
        self.assertNotIn("99999", json.dumps(result))
        with self.assertRaises(Http404):
            services.search(self.member, other.pk, "Nebulawork")

    def test_outsider_cannot_read_settings_search_or_ask(self):
        self.authenticate(self.outsider)
        with patch("knowledge.providers.generate") as generate:
            self.assertEqual(self.client.get(self.url()).status_code, 404)
            for operation in ("search", "ask"):
                response = self.client.post(self.url(operation), {"question": "Nebulawork"}, format="json")
                self.assertEqual(response.status_code, 404, response.content)
            generate.assert_not_called()

    def test_removed_members_cannot_query_with_stale_user_object(self):
        self.upload()
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
        for callback in (self.search, self.ask):
            with self.assertRaises(Http404):
                callback()

    def test_disabled_and_closed_accounts_are_rechecked_in_database(self):
        self.upload()
        User = get_user_model()
        for changed in ({"is_active": False}, {"closed_at": timezone.now()}):
            with self.subTest(changed=changed):
                User.objects.filter(pk=self.member.pk).update(**changed)
                for callback in (self.search, self.ask):
                    with self.assertRaises(Http404):
                        callback()
                User.objects.filter(pk=self.member.pk).update(is_active=True, closed_at=None)

    def test_new_file_version_replaces_old_text_in_retrieval(self):
        document = self.upload("Nebulawork OLDSECRET required on Monday.")
        self.upload("Nebulawork NEWSECRET required on Friday.", document=document)
        result = self.search()
        self.assertNotIn("OLDSECRET", json.dumps(result))
        self.assertIn("NEWSECRET", json.dumps(result))
        self.assertEqual(result["sources"][0]["version"], 2)

    def test_deleted_document_has_no_evidence(self):
        document = self.upload()
        file_services.remove(actor=self.owner, project_id=self.project.pk, document_id=document.pk, expected_revision=1)
        self.assertEqual(self.search()["sources"], [])

    def test_corrupted_file_never_enters_excerpts(self):
        document = self.upload()
        blob_path(document.versions.get().storage_key).write_bytes(b"Nebulawork UNTRUSTED changed bytes")
        result = self.search()
        self.assertEqual(result["sources"], [])
        self.assertNotIn("UNTRUSTED", json.dumps(result))
        self.assertTrue(result["warnings"])

    def test_required_scan_excludes_local_unscanned_document(self):
        self.upload()
        with override_settings(PROJECT_FILES_REQUIRE_SCAN=True):
            result = self.search()
        self.assertEqual(result["sources"], [])
        self.assertTrue(result["warnings"])

    def test_latest_unavailable_version_does_not_fall_back_to_old_evidence(self):
        document = self.upload("Nebulawork old approved draft")
        self.upload("Nebulawork new pending review", document=document)
        first = document.versions.get(number=1)
        DocumentVersion.objects.filter(pk=first.pk).update(scan_status="clean")
        with override_settings(PROJECT_FILES_REQUIRE_SCAN=True):
            result = self.search()
        self.assertEqual(result["sources"], [])
        self.assertNotIn("old approved draft", json.dumps(result))

    def test_meeting_minutes_and_decisions_are_retrieved_with_record_version(self):
        record = self.record("Nebulawork requirements were reviewed.")
        MeetingRecord.objects.filter(pk=record.pk).update(decisions="Approve the Nebulawork security review", version=4)
        result = self.search()
        self.assertTrue(result["sources"])
        source = result["sources"][0]
        self.assertEqual(source["kind"], "meeting")
        self.assertEqual(source["source_id"], str(record.pk))
        self.assertEqual(source["version"], 4)
        self.assertIn("security review", source["excerpt"])

    def test_cancelled_and_archived_meetings_are_excluded(self):
        cancelled = self.record("Nebulawork cancelled secret")
        archived = self.record("Nebulawork archived secret")
        Meeting.objects.filter(pk=cancelled.meeting_id).update(cancelled_at=timezone.now())
        Meeting.objects.filter(pk=archived.meeting_id).update(archived_at=timezone.now())
        self.assertEqual(self.search()["sources"], [])

    def test_meeting_edits_replace_previous_minutes(self):
        record = self.record("Nebulawork old meeting decision")
        MeetingRecord.objects.filter(pk=record.pk).update(minutes="Nebulawork revised meeting decision", version=2)
        result = self.search()
        self.assertNotIn("old meeting", json.dumps(result))
        self.assertIn("revised meeting", json.dumps(result))
        self.assertEqual(result["sources"][0]["version"], 2)

    def test_csv_content_is_searchable(self):
        self.upload("topic,requirement\nNebulawork,security review\n", name="requirements.csv", content_type="text/csv")
        self.assertIn("security review", self.search()["sources"][0]["excerpt"])

    def test_chinese_query_retrieves_chinese_evidence(self):
        self.upload("项目报告必须包含权限检查和数据库设计说明。")
        self.assertTrue(self.search("权限检查")["sources"])

    def test_docx_content_is_searchable(self):
        self.upload(docx_bytes("Nebulawork needs a security review"), name="requirements.docx", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertIn("security review", self.search()["sources"][0]["excerpt"])

    def test_pdf_content_is_searchable_with_page_locator(self):
        self.upload(pdf_bytes("Nebulawork needs a security review"), name="requirements.pdf", content_type="application/pdf")
        source = self.search()["sources"][0]
        self.assertIn("security review", source["excerpt"])
        self.assertEqual(source["page"], 1)

    def test_unsupported_images_produce_warning_without_fake_text(self):
        output = io.BytesIO()
        Image.new("RGB", (2, 2)).save(output, format="PNG")
        self.upload(output.getvalue(), name="Nebulawork.png", content_type="image/png")
        result = self.search()
        self.assertEqual(result["sources"], [])
        self.assertTrue(result["warnings"])

    def test_unreadable_latest_blob_produces_warning_and_no_evidence(self):
        document = self.upload()
        blob_path(document.versions.get().storage_key).unlink()
        result = self.search()
        self.assertEqual(result["sources"], [])
        self.assertTrue(result["warnings"])

    def test_parser_timeout_is_contained_and_other_sources_remain_searchable(self):
        self.upload(docx_bytes("Nebulawork private document"), name="requirements.docx", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.record()
        with patch("knowledge.sources.subprocess.run", side_effect=subprocess.TimeoutExpired("parser", 3)):
            result = self.search()
        self.assertTrue(result["warnings"])
        self.assertTrue(result["sources"])
        self.assertTrue(all(source["kind"] == "meeting" for source in result["sources"]))

    def test_corpus_limits_are_reported_to_user(self):
        self.upload("Nebulawork file one")
        self.upload("Nebulawork file two")
        self.record("Nebulawork meeting one")
        self.record("Nebulawork meeting two")
        with override_settings(RAG_MAX_FILES=1, RAG_MAX_MEETINGS=1):
            result = self.search()
        self.assertTrue(result["limited"])
        self.assertTrue(result["warnings"])
        self.assertEqual(len(result["sources"]), 2)

    def test_large_text_is_marked_partially_searched(self):
        self.upload("Nebulawork start. " + "background context " * 1900)
        result = self.search()
        self.assertTrue(result["limited"])
        self.assertTrue(result["warnings"])
        self.assertTrue(result["sources"])

    def test_archived_project_remains_readable_to_current_members(self):
        self.upload()
        Project.objects.filter(pk=self.project.pk).update(archived_at=timezone.now())
        self.assertTrue(self.search()["sources"])

    def test_unmatched_question_returns_no_evidence_without_model_call(self):
        self.upload()
        with self.configured(), patch("knowledge.providers.generate") as generate:
            result = self.ask("Quasarwhimsy")
        self.assertEqual(result["status"], "no_evidence")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["sources"], [])
        generate.assert_not_called()

    def test_disabled_provider_keeps_evidence_and_returns_no_fabricated_answer(self):
        self.upload()
        result = self.ask()
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIsNone(result["answer"])
        self.assertTrue(result["sources"])

    def test_provider_failure_keeps_evidence_without_exposing_internal_failure(self):
        self.upload()
        with self.configured(), patch("knowledge.providers.generate", side_effect=providers.ProviderUnavailable("private token failure")):
            result = self.ask()
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIsNone(result["answer"])
        self.assertTrue(result["sources"])
        self.assertNotIn("private token", json.dumps(result))

    def test_grounded_response_retains_citation_and_only_current_project_context(self):
        self.upload()
        with self.configured(), patch("knowledge.providers.generate", return_value="A security review is required [S1].") as generate:
            result = self.ask()
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"], "A security review is required [S1].")
        self.assertEqual(result["model"], "test-model")
        generate.assert_called_once()
        question, sources = generate.call_args.args
        self.assertEqual(question, "Nebulawork")
        self.assertEqual(sources, result["sources"])

    def test_answer_generation_receives_only_remaining_shared_request_budget(self):
        self.upload()
        clock = [0.0]
        retrieve = services._retrieve

        def delayed_retrieve(*args):
            result = retrieve(*args)
            clock[0] = 7.5
            return result

        with self.configured(), patch("knowledge.services.time.monotonic", side_effect=lambda: clock[0]), patch("knowledge.services._retrieve", side_effect=delayed_retrieve), patch("knowledge.providers.generate", return_value="A security review is required [S1].") as generate:
            result = self.ask()
        self.assertEqual(result["status"], "answered")
        self.assertEqual(generate.call_args.kwargs["timeout"], 16.5)

    def test_exhausted_shared_budget_has_no_generation_egress(self):
        self.upload()
        clock = [0.0]
        retrieve = services._retrieve

        def delayed_retrieve(*args):
            result = retrieve(*args)
            clock[0] = 24.0
            return result

        with self.configured(), patch("knowledge.services.time.monotonic", side_effect=lambda: clock[0]), patch("knowledge.services._retrieve", side_effect=delayed_retrieve), patch("knowledge.providers.generate") as generate:
            result = self.ask()
        generate.assert_not_called()
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIsNone(result["answer"])
        self.assertTrue(result["sources"])

    def test_late_model_answer_is_withheld_after_shared_deadline(self):
        self.upload()
        clock = [0.0]

        def late_answer(*args, **kwargs):
            clock[0] = 25.0
            return "A security review is required [S1]."

        with self.configured(), patch("knowledge.services.time.monotonic", side_effect=lambda: clock[0]), patch("knowledge.providers.generate", side_effect=late_answer):
            result = self.ask()
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIsNone(result["answer"])
        self.assertTrue(result["sources"])

    def test_unknown_or_absent_citation_withholds_generated_answer(self):
        self.upload()
        for answer in ("Security review required [S99].", "Security review required.", "Security review required [S1] and invented [S99]."):
            with self.subTest(answer=answer), self.configured(), patch("knowledge.providers.generate", return_value=answer):
                result = self.ask()
            self.assertEqual(result["status"], "unverified_answer")
            self.assertIsNone(result["answer"])
            self.assertTrue(result["sources"])

    def test_transport_bracket_normalization_accepts_known_labels_but_withholds_unknown_ones(self):
        from knowledge.tests.test_provider import StubClient, StubResponse
        self.upload()
        cases = (
            ("A security review is required 【S1】.", "answered", "A security review is required [S1]."),
            ("A security review is required ［S1］.", "answered", "A security review is required [S1]."),
            ("Review 【S1】 with invented support ［S99］.", "unverified_answer", None),
        )
        for answer, status, expected in cases:
            payload = json.dumps({"done": True, "message": {"content": answer}}).encode()
            client = StubClient(StubResponse(200, [payload]))
            with self.subTest(answer=answer), self.configured(), \
                    patch("integrations.rag_model.httpx.AsyncClient", return_value=client):
                result = self.ask()
            self.assertEqual(result["status"], status)
            self.assertEqual(result["answer"], expected)
            self.assertTrue(result["sources"])

    def test_transport_bracket_normalization_preserves_credential_withholding(self):
        from knowledge.tests.test_provider import StubClient, StubResponse
        self.upload("Nebulawork password is BLUE-MOON-SECRET.")
        payload = json.dumps({"done": True, "message": {
            "content": "The password is BLUE-MOON-SECRET 【S1】."}}).encode()
        client = StubClient(StubResponse(200, [payload]))
        with self.configured(), patch("integrations.rag_model.httpx.AsyncClient", return_value=client):
            result = self.ask()
        self.assertEqual(result["status"], "unverified_answer")
        self.assertIsNone(result["answer"])
        self.assertNotIn("BLUE-MOON-SECRET", " ".join(result["warnings"]))

    def test_membership_revocation_during_model_call_withholds_response(self):
        self.upload()
        def revoke(*args, **kwargs):
            ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
            return "A security review is required [S1]."
        with self.configured(), patch("knowledge.providers.generate", side_effect=revoke), self.assertRaises(Http404):
            self.ask()

    def test_account_closure_during_model_call_withholds_response(self):
        self.upload()
        def close(*args, **kwargs):
            get_user_model().objects.filter(pk=self.member.pk).update(closed_at=timezone.now())
            return "A security review is required [S1]."
        with self.configured(), patch("knowledge.providers.generate", side_effect=close), self.assertRaises(Http404):
            self.ask()

    def test_document_deletion_during_model_call_requires_fresh_question(self):
        document = self.upload()
        def remove(*args, **kwargs):
            ProjectDocument.objects.filter(pk=document.pk).update(removed_at=timezone.now())
            return "A security review is required [S1]."
        with self.configured(), patch("knowledge.providers.generate", side_effect=remove), self.assertRaises(ValidationError):
            self.ask()

    def test_new_file_version_during_model_call_requires_fresh_question(self):
        document = self.upload()
        def update(*args, **kwargs):
            self.upload("Nebulawork now requires a different review", document=document)
            return "A security review is required [S1]."
        with self.configured(), patch("knowledge.providers.generate", side_effect=update), self.assertRaises(ValidationError):
            self.ask()

    def test_meeting_edit_during_model_call_requires_fresh_question(self):
        record = self.record()
        def update(*args, **kwargs):
            MeetingRecord.objects.filter(pk=record.pk).update(minutes="Nebulawork revised decision", version=2)
            return "A security review is required [S1]."
        with self.configured(), patch("knowledge.providers.generate", side_effect=update), self.assertRaises(ValidationError):
            self.ask()

    def test_blob_tampering_during_model_call_requires_fresh_question(self):
        document = self.upload()
        def tamper(*args, **kwargs):
            blob_path(document.versions.get().storage_key).write_bytes(b"Corrupted after retrieval")
            return "A security review is required [S1]."
        with self.configured(), patch("knowledge.providers.generate", side_effect=tamper), self.assertRaises(ValidationError):
            self.ask()

    def test_cancelled_meeting_during_model_call_requires_fresh_question(self):
        record = self.record()
        def cancel(*args, **kwargs):
            Meeting.objects.filter(pk=record.meeting_id).update(cancelled_at=timezone.now())
            return "A security review is required [S1]."
        with self.configured(), patch("knowledge.providers.generate", side_effect=cancel), self.assertRaises(ValidationError):
            self.ask()

    def test_settings_and_post_responses_are_private_and_not_cacheable(self):
        self.authenticate(self.member)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["generation_available"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("api_key", json.dumps(response.json()).lower())
        self.upload()
        for operation in ("search", "ask"):
            response = self.client.post(self.url(operation), {"question": "Nebulawork"}, format="json")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertIn("no-store", response["Cache-Control"])
            self.assert_no_private_paths(response.json())

    def test_authentication_and_mfa_required_for_rag_endpoints(self):
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.assertEqual(self.client.post(self.url("ask"), {"question": "Nebulawork"}, format="json").status_code, 401)

    def test_csrf_required_for_search_and_ask_posts(self):
        client = APIClient(enforce_csrf_checks=True)
        self.authenticate(self.member, client=client)
        for operation in ("search", "ask"):
            response = client.post(self.url(operation), {"question": "Nebulawork"}, format="json")
            self.assertEqual(response.status_code, 403)

    def test_invalid_input_cannot_trigger_generation(self):
        self.authenticate(self.member)
        invalid = (
            {}, {"question": " "}, {"question": 123}, {"question": "x" * 4000},
            {"question": "Nebulawork", "max_sources": 0},
            {"question": "Nebulawork", "max_sources": 7},
            {"question": "Nebulawork", "max_sources": True},
            {"question": "Nebulawork", "project": str(self.project.pk)},
        )
        with patch("knowledge.providers.generate") as generate:
            for payload in invalid:
                with self.subTest(payload=payload):
                    response = self.client.post(self.url("ask"), payload, format="json")
                    self.assertEqual(response.status_code, 400, response.content)
            generate.assert_not_called()

    def test_source_limit_bounds_evidence_and_citation_numbering(self):
        for index in range(7):
            self.record(f"Nebulawork security review evidence number {index}.")
        result = self.search(max_sources=2)
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual([row["citation"] for row in result["sources"]], ["S1", "S2"])
