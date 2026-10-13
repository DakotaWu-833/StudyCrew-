from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
import zipfile

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError
from django.http import Http404
from django.test import override_settings, Client, RequestFactory
from django.db import transaction
from django.utils import timezone
from PIL import Image

from operations.tests.helpers import OperationsTestCase
from projects.models import Project, ProjectMembership
from documents_store import services, selectors
from documents_store.account_hooks import export_documents, close_documents
from documents_store.models import ProjectDocument, DocumentVersion, UploadDailyUsage
from documents_store.storage import blob_path, prepare, safe_name, validate_contents, scan
from documents_store.checks import private_upload_deploy_checks


def file(name="notes.txt", data=b"Project notes", content_type="text/plain"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, payload in files.items():
            zipped.writestr(name, payload)
    return output.getvalue()


class PrivateFilesTests(OperationsTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = override_settings(MEDIA_ROOT=self.directory.name, PROJECT_FILES_REQUIRE_SCAN=False,
            PROJECT_FILES_CLAMSCAN="", PROJECT_FILE_MAX_BYTES=1024 * 1024, PROJECT_FILE_QUOTA_BYTES=10 * 1024 * 1024,
            PROJECT_FILE_DAILY_BYTES=10 * 1024 * 1024, PROJECT_FILE_DAILY_UPLOADS=30)
        self.config.enable()
        self.addCleanup(self.config.disable)

    def upload(self, actor=None, **values):
        return services.upload(actor=actor or self.member, project_id=self.project.pk, upload=file(), values=values)

    def url(self, document=None, suffix=""):
        base = f"/api/v1/files/projects/{self.project.pk}/"
        return f"{base}documents/{document.pk}/{suffix}" if document else base

    def test_upload_hash_storage_and_metadata_do_not_expose_storage_key(self):
        document = self.upload(title="Lecture notes", tags=["report", "report"], folder="Week 1")
        version = document.versions.get()
        self.assertEqual(version.sha256, hashlib.sha256(b"Project notes").hexdigest())
        self.assertEqual(blob_path(version.storage_key).read_bytes(), b"Project notes")
        self.assertNotIn("notes", version.storage_key)
        self.assertEqual(version.scan_status, "local_unscanned")
        payload = selectors.detail(self.member, self.project.pk, document.pk)
        self.assertEqual(payload["tags"], ["report"])
        self.assertTrue(payload["can_edit"])
        self.assertNotIn("storage_key", json.dumps(payload, default=str))

    def test_versions_keep_original_bytes_and_use_expected_revision(self):
        document = self.upload()
        old = document.versions.get()
        document = services.upload(actor=self.member, project_id=self.project.pk, document_id=document.pk,
            upload=file(data=b"Second version"), values={"expected_revision": 1})
        self.assertEqual(document.revision, 2)
        self.assertEqual(list(document.versions.values_list("number", flat=True)), [2, 1])
        stream, _ = services.open_download(user=self.owner, project_id=self.project.pk, document_id=document.pk, version_id=old.pk)
        with stream:
            self.assertEqual(stream.read(), b"Project notes")
        with self.assertRaises(ValidationError):
            services.upload(actor=self.member, project_id=self.project.pk, document_id=document.pk,
                upload=file(), values={"expected_revision": 1})
        self.assertEqual(document.versions.count(), 2)

    def test_rename_conflict_cannot_overwrite(self):
        document = self.upload()
        services.update(actor=self.member, project_id=self.project.pk, document_id=document.pk,
            values={"expected_revision": 1, "title": "Updated title"})
        with self.assertRaises(ValidationError):
            services.update(actor=self.owner, project_id=self.project.pk, document_id=document.pk,
                values={"expected_revision": 1, "title": "Stale title"})
        document.refresh_from_db()
        self.assertEqual(document.title, "Updated title")

    def test_author_or_manager_permission_and_pin_manager_only(self):
        document = self.upload(self.owner)
        with self.assertRaises(PermissionDenied):
            services.update(actor=self.member, project_id=self.project.pk, document_id=document.pk,
                values={"expected_revision": 1, "title": "Forbidden"})
        with self.assertRaises(PermissionDenied):
            self.upload(pinned=True)
        own = self.upload()
        own = services.update(actor=self.owner, project_id=self.project.pk, document_id=own.pk,
            values={"expected_revision": 1, "pinned": True})
        self.assertTrue(own.pinned)

    def test_former_members_outsiders_and_closed_users_have_no_download(self):
        document = self.upload()
        for user in [self.outsider]:
            with self.assertRaises(Http404):
                services.open_download(user=user, project_id=self.project.pk, document_id=document.pk)
        self.membership.removed_at = timezone.now()
        self.membership.save()
        with self.assertRaises(Http404):
            services.open_download(user=self.member, project_id=self.project.pk, document_id=document.pk)
        self.owner.is_active = False
        self.owner.save()
        with self.assertRaises(Http404):
            services.open_download(user=self.owner, project_id=self.project.pk, document_id=document.pk)

    def test_archive_preserves_download_and_rejects_all_writes(self):
        document = self.upload()
        self.project.archived_at = timezone.now()
        self.project.save()
        for callback in [lambda: self.upload(), lambda: services.update(actor=self.member, project_id=self.project.pk,
            document_id=document.pk, values={"expected_revision": 1, "title": "No"}),
            lambda: services.remove(actor=self.member, project_id=self.project.pk, document_id=document.pk, expected_revision=1)]:
            with self.assertRaises(ValidationError):
                callback()
        stream, _ = services.open_download(user=self.member, project_id=self.project.pk, document_id=document.pk)
        stream.close()

    def test_soft_deleted_versions_still_count_toward_quota(self):
        document = self.upload()
        services.remove(actor=self.member, project_id=self.project.pk, document_id=document.pk, expected_revision=1)
        self.assertEqual(selectors.documents(self.member, self.project.pk)["count"], 0)
        with self.assertRaises(Http404):
            services.open_download(user=self.member, project_id=self.project.pk, document_id=document.pk)
        with override_settings(PROJECT_FILE_QUOTA_BYTES=len(b"Project notes")):
            with self.assertRaises(ValidationError):
                self.upload()
        self.assertEqual(DocumentVersion.objects.count(), 1)

    def test_user_daily_quota_cannot_be_bypassed_in_another_project(self):
        self.upload()
        second = Project.objects.create(name="Other class", created_by=self.member)
        ProjectMembership.objects.create(project=second, user=self.member, role="owner")
        with override_settings(PROJECT_FILE_DAILY_UPLOADS=1):
            with self.assertRaises(ValidationError):
                services.upload(actor=self.member, project_id=second.pk, upload=file())
        self.assertEqual(UploadDailyUsage.objects.get(user=self.member).count, 1)

    def test_day_bytes_file_size_and_retained_versions_limits(self):
        with override_settings(PROJECT_FILE_DAILY_BYTES=3):
            with self.assertRaises(ValidationError):
                self.upload()
        with override_settings(PROJECT_FILE_MAX_BYTES=3):
            with self.assertRaises(ValidationError):
                self.upload()
        self.assertEqual(ProjectDocument.objects.count(), 0)

    def test_database_failure_removes_pending_and_destination_files(self):
        with patch("documents_store.services.DocumentVersion.objects.create", side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                self.upload()
        self.assertEqual(ProjectDocument.objects.count(), 0)
        self.assertEqual([p for p in Path(self.directory.name).rglob("*") if p.is_file()], [])

    def test_scan_failure_saves_no_rows_or_pending_files(self):
        with override_settings(PROJECT_FILES_REQUIRE_SCAN=True):
            with self.assertRaises(ValidationError):
                self.upload()
        self.assertFalse(DocumentVersion.objects.exists())
        self.assertEqual([p for p in Path(self.directory.name).rglob("*") if p.is_file()], [])

    def test_required_scan_hides_older_local_unscanned_versions(self):
        document = self.upload()
        with override_settings(PROJECT_FILES_REQUIRE_SCAN=True):
            with self.assertRaises(Http404):
                services.open_download(user=self.member, project_id=self.project.pk, document_id=document.pk)

    def test_download_corruption_is_rejected(self):
        document = self.upload()
        version = document.versions.get()
        blob_path(version.storage_key).write_bytes(b"Changed bytes")
        with self.assertRaises(Http404):
            services.open_download(user=self.member, project_id=self.project.pk, document_id=document.pk)

    def test_list_filters_and_history_pagination(self):
        self.upload(title="Lecture notes", folder="Reports", tags=["math"])
        self.upload(title="Presentation", folder="Slides", tags=["mathematics"])
        result = selectors.documents(self.member, self.project.pk, tag="math")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["title"], "Lecture notes")
        self.assertEqual(selectors.documents(self.member, self.project.pk, query="Presentation")["count"], 1)
        with self.assertRaises(ValidationError):
            selectors.documents(self.member, self.project.pk, page="invalid")

    def test_account_export_withholds_former_project_content_and_close_hides_files(self):
        document = self.upload()
        self.assertEqual(export_documents(self.member)[0]["title"], "notes.txt")
        self.membership.removed_at = timezone.now()
        self.membership.save()
        exported = export_documents(self.member)[0]
        self.assertTrue(exported["content_withheld"])
        self.assertNotIn("versions", exported)
        close_documents(self.member)
        document.refresh_from_db()
        self.assertIsNotNone(document.removed_at)
        self.assertFalse(UploadDailyUsage.objects.filter(user=self.member).exists())

    def test_purge_only_removes_30_day_old_hidden_files_and_dry_run_changes_nothing(self):
        old = self.upload()
        recent = self.upload()
        retained = self.upload()
        ProjectDocument.objects.filter(pk=old.pk).update(removed_at=timezone.now() - timedelta(days=31))
        ProjectDocument.objects.filter(pk=recent.pk).update(removed_at=timezone.now())
        old_path = blob_path(old.versions.get().storage_key)
        recent_path = blob_path(recent.versions.get().storage_key)
        call_command("purge_private_files", stdout=io.StringIO())
        self.assertTrue(old_path.exists())
        call_command("purge_private_files", apply=True, stdout=io.StringIO())
        self.assertFalse(old_path.exists())
        self.assertFalse(ProjectDocument.objects.filter(pk=old.pk).exists())
        self.assertTrue(recent_path.exists())
        self.assertTrue(ProjectDocument.objects.filter(pk=retained.pk).exists())

    def test_api_multipart_upload_and_download_attachment(self):
        self.signin()
        response = self.client.post(self.url(), {"file": file(), "title": "Uploaded", "tags": '["lecture"]'})
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["tags"], ["lecture"])
        self.assertEqual(payload["latest"]["scan_status"], "local_unscanned")
        response = self.client.get(payload["latest"]["download_url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"Project notes")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", response["Cache-Control"])

    def test_unauthenticated_premfa_and_outsider_download_are_404(self):
        document = self.upload()
        url = self.url(document, "download/")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.signin(mfa=False)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.signin(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_api_versions_metadata_delete_and_invalid_revision(self):
        document = self.upload()
        self.signin()
        response = self.client.patch(self.url(document), json.dumps({"title": "Renamed", "expected_revision": 1}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        response = self.client.post(self.url(document, "versions/"), {"file": file(data=b"More notes"), "expected_revision": 2})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(len(response.json()["versions"]), 2)
        response = self.client.delete(self.url(document), json.dumps({"expected_revision": 2}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        response = self.client.delete(self.url(document), json.dumps({"expected_revision": 3}), content_type="application/json")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get(self.url(document)).status_code, 404)

    def test_raw_private_media_path_is_not_accessible(self):
        document = self.upload()
        version = document.versions.get()
        self.signin()
        self.assertEqual(self.client.get(f"/media/private-project-files/{version.storage_key}").status_code, 404)

    def test_symlink_storage_and_path_traversal_rejected(self):
        with self.assertRaises(ValidationError):
            blob_path("../../outside")
        with self.assertRaises(ValidationError):
            safe_name("folder\\file.txt")

    def test_upload_must_own_outer_commit_to_avoid_future_rollback_orphans(self):
        with transaction.atomic():
            with self.assertRaises(RuntimeError):
                self.upload()
        self.assertEqual([p for p in Path(self.directory.name).rglob("*") if p.is_file()], [])

    def test_existing_blob_on_uuid_collision_is_never_deleted(self):
        document = self.upload()
        original = document.versions.get()
        import uuid
        existing_id = uuid.UUID(Path(original.storage_key).stem)
        with patch("documents_store.services.uuid.uuid4", return_value=existing_id):
            with self.assertRaises(FileExistsError):
                self.upload()
        self.assertEqual(blob_path(original.storage_key).read_bytes(), b"Project notes")

    def test_project_retained_file_count_bounds_many_tiny_files(self):
        self.upload()
        with override_settings(PROJECT_FILE_MAX_VERSIONS_TOTAL=1), self.assertRaises(ValidationError):
            self.upload()

    def test_api_upload_requires_csrf_and_rejects_multiple_files(self):
        csrf_client = Client(enforce_csrf_checks=True)
        self.signin(client=csrf_client)
        self.assertEqual(csrf_client.post(self.url(), {"file": file()}).status_code, 403)
        self.signin()
        response = self.client.post(self.url(), {"file": file(), "extra": file("extra.txt")})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DocumentVersion.objects.exists())

    def test_api_content_length_guard_rejects_oversized_body(self):
        self.signin()
        with override_settings(PROJECT_FILE_MAX_BYTES=1):
            response = self.client.post(self.url(), {"file": file(data=b"a" * 70_000)})
        self.assertEqual(response.status_code, 413)
        self.assertFalse(DocumentVersion.objects.exists())

    def test_actual_chunk_handler_enforces_limit_with_understated_file_size(self):
        from django.core.files.uploadhandler import StopUpload
        from documents_store.middleware import BoundedPrivateUploadHandler
        request = RequestFactory().post(self.url())
        with override_settings(PROJECT_FILE_MAX_BYTES=2):
            handler = BoundedPrivateUploadHandler(request)
        handler.new_file("file", "notes.txt", "text/plain", None)
        with self.assertRaises(StopUpload):
            handler.receive_data_chunk(b"abc", 0)
        self.assertTrue(request.private_upload_rejected)

    def test_service_metadata_limits_and_sql_tag_rename(self):
        document = self.upload(tags=["old"])
        services.update(actor=self.member, project_id=self.project.pk, document_id=document.pk,
            values={"expected_revision": 1, "tags": ["new", "中文"]})
        self.assertEqual(selectors.documents(self.member, self.project.pk, tag="old")["count"], 0)
        self.assertEqual(selectors.documents(self.member, self.project.pk, tag="中文")["count"], 1)
        for values in [{"title": "x" * 151}, {"tags": ["x"] * 11}, {"author": self.owner}, {"pinned": "false"}]:
            with self.assertRaises(ValidationError):
                services.update(actor=self.member, project_id=self.project.pk, document_id=document.pk,
                    values={"expected_revision": 2, **values})

    def test_rate_limit_failure_stops_scan_and_integrity_reads(self):
        document = self.upload()
        with patch("documents_store.services.consume_rate", return_value=False):
            with self.assertRaises(ValidationError):
                self.upload()
            with self.assertRaises(ValidationError):
                services.open_download(user=self.member, project_id=self.project.pk, document_id=document.pk)

    def test_orphan_cleanup_preserves_live_blob_and_recent_pending(self):
        import os
        import uuid
        document = self.upload()
        version = document.versions.get()
        old_orphan = blob_path(f"{self.project.pk}/{uuid.uuid4()}.blob")
        old_orphan.write_bytes(b"orphan")
        ancient = (timezone.now() - timedelta(days=3)).timestamp()
        os.utime(old_orphan, (ancient, ancient))
        live = blob_path(version.storage_key)
        os.utime(live, (ancient, ancient))
        pending = live.parent.parent / "pending-recent"
        pending.write_bytes(b"pending")
        call_command("purge_private_files", apply=True, orphans=True, stdout=io.StringIO())
        self.assertFalse(old_orphan.exists())
        self.assertTrue(live.exists())
        self.assertTrue(pending.exists())


class FileContentTests(OperationsTestCase):
    def test_filename_rejects_double_extensions_paths_control_chars_and_ntfs_streams(self):
        for filename in ["../file.txt", "file.exe.txt", "file.txt:stream", "<bad>\x00.txt", "script.js", "image.svg", "page.html"]:
            with self.subTest(filename=repr(filename)), self.assertRaises(ValidationError):
                safe_name(filename)
        self.assertEqual(safe_name("论文 (final).TXT"), ("论文 (final).TXT", "txt"))

    def test_text_requires_utf8_and_csv_structural_validation(self):
        validate_contents("中文资料".encode(), "txt")
        for data in [b"\x00bad", b"\xffbad", b""]:
            with self.assertRaises(ValidationError):
                validate_contents(data, "txt")
        with self.assertRaises(ValidationError):
            validate_contents(b'"unfinished', "csv")

    def test_spoofed_media_header_rejected(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory, PROJECT_FILES_REQUIRE_SCAN=False):
            with self.assertRaises(ValidationError):
                prepare(file("notes.txt", content_type="application/pdf"))

    def test_png_verification_and_extension_mismatch(self):
        image = Image.new("RGB", (2, 2), "white")
        output = io.BytesIO()
        image.save(output, format="PNG")
        validate_contents(output.getvalue(), "png")
        with self.assertRaises(ValidationError):
            validate_contents(output.getvalue(), "jpg")
        with self.assertRaises(ValidationError):
            validate_contents(b"PNG not really", "png")

    def test_pdf_requires_header_eof_and_rejects_active_content(self):
        validate_contents(b"%PDF-1.4\nA simple local PDF fixture\n%%EOF", "pdf")
        for payload in [b"plain text", b"%PDF-1.4\n/JavaScript 1\n%%EOF", b"%PDF-1.4 no eof"]:
            with self.assertRaises(ValidationError):
                validate_contents(payload, "pdf")

    def test_safe_zip_bundle_and_path_executable_nested_archive_rejection(self):
        validate_contents(archive({"notes.txt": b"notes", "sub/data.csv": b"a,b\n1,2"}), "zip")
        for contents in [{"../notes.txt": b"bad"}, {"script.exe": b"MZ"}, {"unknown.bin": b"MZ"}, {"inner.zip": b"PK"}, {"x.txt": b"\x00bad"}]:
            with self.assertRaises(ValidationError):
                validate_contents(archive(contents), "zip")

    def test_zip_bomb_expanded_size_ratio_and_member_count_rejected(self):
        with override_settings(PROJECT_FILE_ZIP_EXPANDED_BYTES=5):
            with self.assertRaises(ValidationError):
                validate_contents(archive({"long.txt": b"a" * 10}), "zip")
        with self.assertRaises(ValidationError):
            validate_contents(archive({"long.txt": b"a" * 100_000}), "zip")
        with self.assertRaises(ValidationError):
            validate_contents(archive({f"{n}.txt": b"a" for n in range(501)}), "zip")

    def test_office_structure_external_rels_macros_and_xml_entities_rejected(self):
        base = {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<document/>"}
        validate_contents(archive(base), "docx")
        for extra in [{"word/_rels/document.xml.rels": b'<Relationships><Relationship TargetMode="External" Target="https://example.com"/></Relationships>'},
            {"word/vbaProject.bin": b"macro"}, {"word/embeddings/object.bin": b"object"},
            {"word/document.xml": b'<!DOCTYPE foo [<!ENTITY x "y">]><document/>'}]:
            with self.assertRaises(ValidationError):
                validate_contents(archive({**base, **extra}), "docx")
        with self.assertRaises(ValidationError):
            validate_contents(archive(base), "xlsx")

    def test_configured_scanner_return_codes_and_timeout_fail_closed(self):
        with override_settings(PROJECT_FILES_REQUIRE_SCAN=True, PROJECT_FILES_CLAMSCAN="clamscan"):
            with patch("documents_store.storage.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertEqual(scan(Path("test.blob")), "clean")
                self.assertEqual(run.call_args.args[0], ["clamscan", "--no-summary", "--", "test.blob"])
            for code in [1, 2]:
                with patch("documents_store.storage.subprocess.run", return_value=subprocess.CompletedProcess([], code)), self.assertRaises(ValidationError):
                    scan(Path("test.blob"))
            with patch("documents_store.storage.subprocess.run", side_effect=subprocess.TimeoutExpired("clamscan", 45)), self.assertRaises(ValidationError):
                scan(Path("test.blob"))

    def test_production_deploy_checks_do_not_pretend_unavailable_scanner_exists(self):
        with override_settings(ENVIRONMENT="production", PROJECT_FILES_REQUIRE_SCAN=True, PROJECT_FILES_CLAMSCAN="missing-scanner-for-test"):
            self.assertIn("documents_store.E003", [item.id for item in private_upload_deploy_checks(None)])
