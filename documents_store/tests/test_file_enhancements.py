from datetime import timedelta
import hashlib
import io
import json
import tempfile
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.http import Http404
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from documents_store import selectors, services
from documents_store.account_hooks import close_documents
from documents_store.models import ProjectDocument, UploadDailyUsage
from documents_store.storage import blob_path
from documents_store.tests.test_private_files import file
from operations.models import OperationAudit
from operations.tests.helpers import OperationsTestCase
from projects.models import Project, ProjectMembership


class FileEnhancementsTests(OperationsTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config = override_settings(MEDIA_ROOT=self.directory.name, PROJECT_FILES_REQUIRE_SCAN=False,
            PROJECT_FILES_CLAMSCAN="", PROJECT_FILE_MAX_BYTES=1024 * 1024)
        config.enable()
        self.addCleanup(config.disable)

    def upload(self, data=b"First line\nOld section\n", name="notes.txt", kind="text/plain", actor=None):
        return services.upload(actor=actor or self.member, project_id=self.project.pk,
            upload=file(name, data, kind), values={"title": "Team notes"})

    def url(self, document=None, suffix=""):
        base = f"/api/v1/files/projects/{self.project.pk}/"
        return f"{base}documents/{document.pk}/{suffix}" if document else base

    def remove(self, document):
        services.remove(actor=self.member, project_id=self.project.pk, document_id=document.pk,
            expected_revision=document.revision)
        document.refresh_from_db()

    def test_author_restores_retained_versions_metadata_and_storage_without_upload_quota(self):
        document = self.upload()
        original = document.versions.get()
        document = services.upload(actor=self.member, project_id=self.project.pk, document_id=document.pk,
            upload=file(data=b"New text"), values={"expected_revision": 1})
        self.remove(document)
        usage = selectors.usage(self.project)["bytes"]
        daily = UploadDailyUsage.objects.get(user=self.member).count
        with override_settings(PROJECT_FILE_DAILY_UPLOADS=0, PROJECT_FILE_QUOTA_BYTES=0):
            restored = services.restore(actor=self.member, project_id=self.project.pk,
                document_id=document.pk, expected_revision=3)
        self.assertIsNone(restored.removed_at)
        self.assertEqual(restored.revision, 4)
        self.assertEqual(restored.versions.count(), 2)
        self.assertEqual(selectors.usage(self.project)["bytes"], usage)
        self.assertEqual(UploadDailyUsage.objects.get(user=self.member).count, daily)
        stream, _ = services.open_download(user=self.owner, project_id=self.project.pk,
            document_id=document.pk, version_id=original.pk)
        with stream:
            self.assertEqual(stream.read(), b"First line\nOld section\n")
        self.assertTrue(OperationAudit.objects.filter(action="project_file_restored", target_id=document.pk).exists())

    def test_manager_can_restore_other_author_but_member_cannot_restore_manager_file(self):
        document = self.upload(actor=self.owner)
        services.remove(actor=self.owner, project_id=self.project.pk, document_id=document.pk, expected_revision=1)
        with self.assertRaises(PermissionDenied):
            services.restore(actor=self.member, project_id=self.project.pk, document_id=document.pk, expected_revision=2)
        own = self.upload()
        self.remove(own)
        services.restore(actor=self.owner, project_id=self.project.pk, document_id=own.pk, expected_revision=2)

    def test_restore_rejects_stale_revision_double_restore_expiry_and_archived_project(self):
        document = self.upload()
        self.remove(document)
        with self.assertRaises(ValidationError):
            services.restore(actor=self.member, project_id=self.project.pk, document_id=document.pk, expected_revision=1)
        self.project.archived_at = timezone.now()
        self.project.save()
        with self.assertRaises(ValidationError):
            services.restore(actor=self.member, project_id=self.project.pk, document_id=document.pk, expected_revision=2)
        self.project.archived_at = None
        self.project.save()
        ProjectDocument.objects.filter(pk=document.pk).update(removed_at=timezone.now() - timedelta(days=30))
        with self.assertRaises(ValidationError):
            services.restore(actor=self.member, project_id=self.project.pk, document_id=document.pk, expected_revision=2)
        ProjectDocument.objects.filter(pk=document.pk).update(removed_at=timezone.now())
        services.restore(actor=self.member, project_id=self.project.pk, document_id=document.pk, expected_revision=2)
        with self.assertRaises(Http404):
            services.restore(actor=self.member, project_id=self.project.pk, document_id=document.pk, expected_revision=3)

    def test_trash_no_download_links_closed_author_hidden_and_old_files_not_recoverable(self):
        document = self.upload()
        self.remove(document)
        row = selectors.trash(self.member, self.project.pk)["results"][0]
        self.assertTrue(row["can_restore"])
        self.assertIsNone(row["latest"])
        self.assertNotIn("download_url", json.dumps(row, default=str))
        self.assertFalse(row["can_edit"])
        ProjectDocument.objects.filter(pk=document.pk).update(removed_at=timezone.now() - timedelta(days=31))
        self.assertFalse(selectors.trash(self.owner, self.project.pk)["results"][0]["can_restore"])
        close_documents(self.member)
        self.assertEqual(selectors.trash(self.owner, self.project.pk)["count"], 0)
        with self.assertRaises(ValidationError):
            services.restore(actor=self.owner, project_id=self.project.pk, document_id=document.pk, expected_revision=2)

    def test_closure_marks_previously_removed_files_irrecoverable_even_if_user_active(self):
        document = self.upload()
        self.remove(document)
        close_documents(self.member)
        document.refresh_from_db()
        self.assertTrue(document.restoration_blocked)
        with self.assertRaises(ValidationError):
            services.restore(actor=self.owner, project_id=self.project.pk, document_id=document.pk, expected_revision=2)

    def test_missing_corrupt_unscanned_or_purged_retained_version_cannot_restore(self):
        document = self.upload()
        self.remove(document)
        version = document.versions.get()
        path = blob_path(version.storage_key)
        for payload in (b"tampered", None):
            if payload is None:
                path.unlink()
            else:
                path.write_bytes(payload)
            with self.assertRaises(ValidationError):
                services.restore(actor=self.owner, project_id=self.project.pk, document_id=document.pk, expected_revision=2)
        path.write_bytes(b"First line\nOld section\n")
        with override_settings(PROJECT_FILES_REQUIRE_SCAN=True), self.assertRaises(ValidationError):
            services.restore(actor=self.owner, project_id=self.project.pk, document_id=document.pk, expected_revision=2)
        ProjectDocument.objects.filter(pk=document.pk).update(removed_at=timezone.now() - timedelta(days=31))
        call_command("purge_private_files", apply=True, stdout=io.StringIO())
        with self.assertRaises(Http404):
            services.restore(actor=self.owner, project_id=self.project.pk, document_id=document.pk, expected_revision=2)

    def test_outsider_former_member_inactive_user_cannot_read_trash_restore_or_preview(self):
        document = self.upload()
        self.remove(document)
        for callback in [lambda: selectors.trash(self.outsider, self.project.pk),
            lambda: services.restore(actor=self.outsider, project_id=self.project.pk, document_id=document.pk, expected_revision=2)]:
            with self.assertRaises(Http404):
                callback()
        self.membership.removed_at = timezone.now()
        self.membership.save()
        with self.assertRaises(Http404):
            selectors.trash(self.member, self.project.pk)

    def test_preview_authenticated_nostore_integrity_text_is_plain_and_markup_never_html(self):
        document = self.upload(b"<script>alert('test')</script>\n", name="code.txt")
        self.signin()
        response = self.client.get(self.url(document, "preview/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertEqual(b"".join(response.streaming_content), b"<script>alert('test')</script>\n")
        version = document.versions.get()
        blob_path(version.storage_key).write_bytes(b"bad")
        self.assertEqual(self.client.get(self.url(document, "preview/")).status_code, 404)

    def test_preview_pdf_and_image_mime_and_unsupported_office_download_remains(self):
        pdf = self.upload(b"%PDF-1.4\nLocal fixture\n%%EOF", "brief.pdf", "application/pdf")
        output = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(output, format="PNG")
        image = self.upload(output.getvalue(), "chart.png", "image/png")
        for document, kind in [(pdf, "pdf"), (image, "image")]:
            stream, version, truncated = services.open_preview(user=self.member, project_id=self.project.pk, document_id=document.pk)
            with stream:
                self.assertTrue(stream.read())
            self.assertEqual(services.preview_kind(version), kind)
            self.assertFalse(truncated)
            self.signin()
            response = self.client.get(self.url(document, "preview/"), HTTP_ACCEPT="*/*")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], version.content_type)
            self.assertTrue(b"".join(response.streaming_content))
        document = self.upload()
        version = document.versions.get()
        version.content_type = "application/zip"
        version.save()
        with self.assertRaises(ValidationError):
            services.open_preview(user=self.member, project_id=self.project.pk, document_id=document.pk)

    def test_large_text_preview_truncates_at_valid_utf8_boundary_with_notice_header(self):
        text = "中" * 200_000
        document = self.upload(text.encode())
        self.signin()
        response = self.client.get(self.url(document, "preview/"))
        payload = b"".join(response.streaming_content)
        self.assertEqual(response["X-Preview-Truncated"], "true")
        self.assertLessEqual(len(payload), services.PREVIEW_TEXT_BYTES)
        self.assertTrue(text.startswith(payload.decode("utf-8")))

    def test_premfa_unauthenticated_outsider_deleted_and_wrong_version_previews_404(self):
        document = self.upload()
        url = self.url(document, "preview/")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.signin(mfa=False)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.signin(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.signin()
        self.assertEqual(self.client.get(url + "?version=wrong").status_code, 404)
        self.remove(document)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_diff_reports_actual_changes_does_not_cross_documents_and_checks_integrity(self):
        document = self.upload()
        old = document.versions.get()
        document = services.upload(actor=self.member, project_id=self.project.pk, document_id=document.pk,
            upload=file(data=b"First line\nNew section\n"), values={"expected_revision": 1})
        latest = document.versions.first()
        arguments = dict(user=self.owner, project_id=self.project.pk, document_id=document.pk,
            from_version=old.pk, to_version=latest.pk)
        result = services.text_diff(**arguments)
        self.assertFalse(result["identical"])
        self.assertIn({"kind": "removed", "text": "-Old section", "no_final_newline": False}, result["lines"])
        self.assertIn({"kind": "added", "text": "+New section", "no_final_newline": False}, result["lines"])
        other = self.upload().versions.get()
        with self.assertRaises(Http404):
            services.text_diff(**{**arguments, "to_version": other.pk})
        blob_path(latest.storage_key).write_bytes(b"tampered")
        with self.assertRaises(Http404):
            services.text_diff(**arguments)

    def test_diff_bounds_nontext_same_version_and_final_newline(self):
        document = self.upload(b"A")
        old = document.versions.get()
        document = services.upload(actor=self.member, project_id=self.project.pk, document_id=document.pk,
            upload=file(data=b"A\n"), values={"expected_revision": 1})
        latest = document.versions.first()
        args = dict(user=self.member, project_id=self.project.pk, document_id=document.pk,
            from_version=old.pk, to_version=latest.pk)
        result = services.text_diff(**args)
        self.assertFalse(result["identical"])
        self.assertTrue(result["line_ending_changed"])
        self.assertTrue(any(row["no_final_newline"] for row in result["lines"]))
        with self.assertRaises(ValidationError):
            services.text_diff(**{**args, "to_version": old.pk})
        latest.content_type = "application/pdf"
        latest.save()
        with self.assertRaises(ValidationError):
            services.text_diff(**args)
        latest.content_type = "text/plain"
        latest.size = services.DIFF_TEXT_BYTES + 1
        latest.save()
        with self.assertRaises(ValidationError):
            services.text_diff(**args)

    def test_api_trash_restore_revision_and_compare_query_validation(self):
        document = self.upload()
        self.remove(document)
        self.signin()
        self.assertEqual(self.client.get(self.url() + "trash/").json()["count"], 1)
        self.assertEqual(self.client.post(self.url(document, "restore/"), json.dumps({"expected_revision": 1}), content_type="application/json").status_code, 400)
        response = self.client.post(self.url(document, "restore/"), json.dumps({"expected_revision": 2}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["revision"], 3)
        self.assertEqual(self.client.get(self.url(document, "compare/") + "?from_version=wrong").status_code, 400)
        self.assertEqual(self.client.get(self.url() + "trash/?page=wrong").status_code, 400)

    def test_scan_and_rate_policy_applies_to_preview_and_diff(self):
        document = self.upload()
        old = document.versions.get()
        document = services.upload(actor=self.member, project_id=self.project.pk, document_id=document.pk,
            upload=file(data=b"new"), values={"expected_revision": 1})
        latest = document.versions.first()
        with override_settings(PROJECT_FILES_REQUIRE_SCAN=True), self.assertRaises(Http404):
            services.open_preview(user=self.member, project_id=self.project.pk, document_id=document.pk)
        with patch("documents_store.services.consume_rate", return_value=False), self.assertRaises(ValidationError):
            services.text_diff(user=self.member, project_id=self.project.pk, document_id=document.pk,
                from_version=old.pk, to_version=latest.pk)
