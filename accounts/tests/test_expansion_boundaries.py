"""New collaboration features respect the existing account lifecycle boundary."""
import json
import tempfile
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import override_settings
from django.utils import timezone

from api.tests.base import APIDomainTestCase
from accounts.models import User
from accounts.readiness_services import close_account, personal_data_download
from documents_store import services as files
from documents_store.models import ProjectDocument
from learning_exchange import services as learning
from learning_exchange.models import ImportPreview
from projects.models import ProjectMembership
from projects.services import archive_project
from recruiting import services as recruiting
from recruiting.models import Application


class ExpansionAccountBoundaryTests(APIDomainTestCase):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = override_settings(MEDIA_ROOT=folder.name, PROJECT_FILES_REQUIRE_SCAN=False)
        settings.enable(); self.addCleanup(settings.disable)

    def opening(self):
        return recruiting.publish(actor=self.owner, data={"project": self.project.pk,
            "title": "Recruiting", "university": "Example University", "course": "COMP",
            "term": "Semester 2", "description": "Private team needs a collaborator",
            "capacity": 2, "publish_consent": True, "expires_at": timezone.now() + timedelta(days=30)})

    def test_former_member_personal_download_hides_new_file_and_import_content(self):
        document = files.upload(actor=self.owner, project_id=self.project.pk,
            upload=SimpleUploadedFile("brief.txt", b"original", content_type="text/plain"), values={"title": "Original"})
        preview = learning.preview(actor=self.owner, project_id=self.project.pk,
            content=b"source_id,title\na1,Assignment secret\n", source="generic", source_namespace="COMP")
        learning.confirm(actor=self.owner, project_id=self.project.pk, preview_id=preview["preview_id"], confirmed=True)
        # Simulate an ownership handover followed by leaving; remaining members
        # may edit shared content without giving its original creator access.
        ProjectMembership.objects.filter(project=self.project, user=self.owner).update(removed_at=timezone.now())
        ProjectDocument.objects.filter(pk=document.pk).update(title="New private team edits")
        payload = json.loads(personal_data_download(user=self.owner))
        exported_file = payload["records"]["documents_store.personal"][0]
        self.assertTrue(exported_file["content_withheld"])
        self.assertNotIn("title", exported_file)
        imports = payload["records"]["learning_exchange.personal"]["learning_imports"]
        self.assertTrue(imports[0]["content_withheld"])
        self.assertNotIn("rows", imports[0])

    def test_closure_retires_public_card_files_and_pending_previews(self):
        card = self.opening()
        recruiting.apply(actor=self.outsider, listing_id=card.pk, message="I would like to join")
        doc = files.upload(actor=self.member, project_id=self.project.pk,
            upload=SimpleUploadedFile("notes.txt", b"private notes", content_type="text/plain"), values={"title": "Notes"})
        preview = learning.preview(actor=self.owner, project_id=self.project.pk,
            content=b"source_id,title\na1,Assignment\n", source="generic", source_namespace="COMP")
        archive_project(project=self.project, actor=self.owner)
        close_account(user=self.member, confirmation="CLOSE MY ACCOUNT")
        doc.refresh_from_db(); self.assertIsNotNone(doc.removed_at)
        with self.assertRaises(Http404): files.open_download(user=self.owner, project_id=self.project.pk, document_id=doc.pk)
        close_account(user=self.owner, confirmation="CLOSE MY ACCOUNT")
        card.refresh_from_db(); self.assertEqual(card.description, "")
        self.assertEqual(card.status, "closed")
        self.assertEqual(Application.objects.get(recruitment=card).status, "cancelled")
        self.assertFalse(ImportPreview.objects.filter(pk=preview["preview_id"]).exists())

    def test_cached_identity_cannot_apply_or_approve_after_closure(self):
        card = self.opening()
        pending = recruiting.apply(actor=self.outsider, listing_id=card.pk, message="Before closing")
        # The request's User object predates the committed account closure.
        User.objects.filter(pk=self.outsider.pk).update(is_active=False, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied): recruiting.decide(actor=self.owner, application_id=pending.pk, decision="approve")
        self.assertFalse(ProjectMembership.objects.active().filter(project=self.project, user=self.outsider).exists())
        with self.assertRaises(PermissionDenied): recruiting.apply(actor=self.outsider, listing_id=card.pk, message="Stale request")

    def test_cached_closed_manager_cannot_create_import_preview(self):
        User.objects.filter(pk=self.owner.pk).update(is_active=False, closed_at=timezone.now())
        with self.assertRaises((PermissionDenied, Http404)):
            learning.preview(actor=self.owner, project_id=self.project.pk,
                content=b"source_id,title\na1,Assignment\n", source="generic", source_namespace="COMP")
        self.assertFalse(ImportPreview.objects.exists())

    def test_export_includes_own_version_of_another_authors_document(self):
        document = files.upload(actor=self.owner, project_id=self.project.pk,
            upload=SimpleUploadedFile("brief.txt", b"original", content_type="text/plain"), values={"title": "Brief"})
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(role="facilitator")
        files.upload(actor=self.member, project_id=self.project.pk, document_id=document.pk,
            upload=SimpleUploadedFile("revised.txt", b"my revision", content_type="text/plain"), values={"expected_revision": 1})
        payload = json.loads(personal_data_download(self.member))
        documents = payload["records"]["documents_store.personal"]
        self.assertEqual(len(documents), 1)
        self.assertEqual([item["filename"] for item in documents[0]["versions"]], ["revised.txt"])

    def test_utf16_office_entity_is_rejected_before_parsing(self):
        from documents_store.storage import _xml
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            _xml('<!DOCTYPE foo [<!ENTITY secret "hidden">]><document>&secret;</document>'.encode("utf-16"))
