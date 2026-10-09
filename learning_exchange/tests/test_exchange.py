import csv
import io
from datetime import timedelta
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import SimpleTestCase
from django.utils import timezone
from api.tests.base import APIDomainTestCase
from activity.models import ActivityEvent
from campus.models import TaskPlan
from projects.models import ProjectMembership
from projects.services import create_project
from tasks.models import Task
from learning_exchange import parser, services
from learning_exchange.models import ImportBatch, ImportPreview, ImportedAssignment


HEADER = "source_id,title,description,official_due_at,priority\n"
CSV = (HEADER + "assignment-1,Final report,Prepare a report,2026-11-15T17:00:00+11:00,high\n").encode()


class ParserTests(SimpleTestCase):
    def parse(self, content=CSV, source="generic", zone="Australia/Sydney"):
        return parser.parse(content, source=source, source_namespace="COMP1010", timezone_name=zone)

    def test_generic_offset_is_normalized_and_formula_text_is_literal(self):
        rows, _ = self.parse((HEADER + "one,=SUM(1),@literal,2026-11-15T17:00:00+11:00,high\n").encode())
        self.assertEqual(rows[0]["title"], "=SUM(1)")
        self.assertEqual(rows[0]["description"], "@literal")
        self.assertEqual(rows[0]["official_due_at"], "2026-11-15T06:00:00+00:00")
        self.assertEqual(rows[0]["errors"], [])

    def test_canvas_and_moodle_explicit_fixture_headers(self):
        for source, header in (("canvas", "Assignment ID,Assignment Name,Due Date"), ("moodle", "ID number,Item name,Due date")):
            with self.subTest(source=source):
                rows, ignored = self.parse((header + "\nx-1,Essay assignment,2026-11-15T17:00:00+11:00\n").encode(), source)
                self.assertEqual(rows[0]["source_id"], "x-1")
                self.assertEqual(rows[0]["priority"], "medium")
                self.assertEqual(ignored, [])

    def test_dst_nonexistent_and_ambiguous_local_times_rejected(self):
        for stamp in ("2026-10-04T02:30:00", "2026-04-05T02:30:00"):
            with self.subTest(stamp=stamp):
                rows, _ = self.parse((HEADER + f"one,Essay assignment,,{stamp},medium\n").encode())
                self.assertIn("daylight saving", rows[0]["errors"][0])

    def test_explicit_offset_resolves_repeated_local_time(self):
        self.assertEqual(parser.deadline("2026-04-05T02:30:00+11:00", "Australia/Sydney"), "2026-04-04T15:30:00+00:00")

    def test_naive_unique_time_uses_selected_profile_zone(self):
        self.assertEqual(parser.deadline("2026-11-15T17:00:00", "Australia/Sydney"), "2026-11-15T06:00:00+00:00")

    def test_date_only_and_invalid_due_priority_are_row_errors(self):
        rows, _ = self.parse((HEADER + "one,Essay assignment,,2026-11-15,super\n").encode())
        self.assertEqual(len(rows[0]["errors"]), 2)

    def test_duplicate_source_id_and_wrong_column_count_are_errors(self):
        rows, _ = self.parse((HEADER + "one,First assignment,,,\none,Second assignment\n").encode())
        self.assertIn("different number", rows[1]["errors"][0])
        self.assertIn("repeats", rows[1]["errors"][-1])

    def test_utf8_bom_quoted_multiline_and_unknown_column(self):
        rows, ignored = self.parse('\ufefftitle,description,unused\nChinese 作业,"Line one\nLine two",ignored\n'.encode())
        self.assertEqual(rows[0]["description"], "Line one\nLine two")
        self.assertEqual(ignored, ["unused"])
        self.assertTrue(rows[0]["source_id"].startswith("auto:"))

    def test_file_byte_row_and_header_limits(self):
        for content in (b"x" * (parser.MAX_BYTES + 1), b"\xff", b"", b"title,title\nabc,abc\n", b"bad\nabc\n", b"title\n" + b"Essay assignment\n" * 101, b'title\n"unclosed', b"title\nabc\x00\n"):
            with self.subTest(size=len(content)), self.assertRaises(ValidationError):
                self.parse(content)

    def test_zone_source_and_namespace_validation(self):
        for kw in ({"source": "remote"}, {"timezone_name": "No/SuchZone"}, {"source_namespace": "https://remote"}):
            data = {"source": "generic", "source_namespace": "manual", "timezone_name": "Australia/Sydney", **kw}
            with self.subTest(kw=kw), self.assertRaises(ValidationError):
                parser.parse(CSV, **data)


class LearningExchangeTests(APIDomainTestCase):
    def preview(self, content=CSV, **kw):
        return services.preview(actor=kw.pop("actor", self.owner), project_id=kw.pop("project_id", self.project.id),
            content=content, source="generic", source_namespace=kw.pop("source_namespace", "COMP1010"), **kw)

    def confirm(self, item, **kw):
        return services.confirm(actor=kw.pop("actor", self.owner), project_id=kw.pop("project_id", self.project.id),
            preview_id=item["preview_id"], confirmed=True, **kw)

    def test_validated_preview_has_no_tasks_then_confirmation_creates_task_plan_and_activity(self):
        item = self.preview()
        self.assertTrue(item["valid"])
        self.assertFalse(Task.objects.exists())
        result = self.confirm(item)
        task = Task.objects.get()
        self.assertEqual(task.title, "Final report")
        self.assertEqual(task.due_at, TaskPlan.objects.get(task=task).official_due_at)
        self.assertEqual(ActivityEvent.objects.filter(project=self.project, event_type="task_created", target_id=task.id).count(), 1)
        self.assertEqual(result["batch"]["imported_count"], 1)

    def test_one_invalid_row_blocks_whole_file_without_any_preview_mutation(self):
        item = self.preview(CSV + b"two,x,,invalid,medium\n")
        self.assertFalse(item["valid"])
        self.assertIsNone(item["preview_id"])
        self.assertFalse(Task.objects.exists())
        self.assertFalse(ImportPreview.objects.exists())

    def test_confirm_is_idempotent_same_preview_and_reuploaded_batch(self):
        item = self.preview()
        first = self.confirm(item)
        self.assertTrue(self.confirm(item)["replayed"])
        second = self.preview()
        self.assertEqual(second["skip_count"], 1)
        repeated = self.confirm(second)
        self.assertTrue(repeated["replayed"])
        self.assertEqual(first["batch"]["id"], repeated["batch"]["id"])
        self.assertEqual(Task.objects.count(), 1)

    def test_changed_source_id_content_is_skipped_and_never_overwrites(self):
        self.confirm(self.preview())
        item = self.preview(CSV.replace(b"Final report", b"Changed report"))
        self.assertEqual(item["rows"][0]["action"], "skip")
        self.confirm(item)
        self.assertEqual(Task.objects.get().title, "Final report")
        batch = ImportBatch.objects.order_by("-created_at").first()
        self.assertEqual(batch.skipped_count, 1)
        self.assertIn("Changed report", services.csv_export(actor=self.owner, project_id=self.project.id, batch_id=batch.id))

    def test_source_namespace_is_explicit_isolation(self):
        self.confirm(self.preview())
        self.confirm(self.preview(source_namespace="COMP2020"))
        self.assertEqual(Task.objects.count(), 2)

    def test_stale_preview_after_different_import_requires_new_preview(self):
        old = self.preview()
        self.confirm(self.preview(CSV + b"assignment-2,Second report,,,medium\n"))
        with self.assertRaisesMessage(ValidationError, "changed since"):
            self.confirm(old)
        self.assertEqual(Task.objects.count(), 2)

    def test_expired_preview_requires_new_preview(self):
        item = self.preview()
        ImportPreview.objects.filter(pk=item["preview_id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaisesMessage(ValidationError, "expired"):
            self.confirm(item)
        self.assertFalse(Task.objects.exists())

    def test_member_cannot_preview_confirm_but_can_export_own_project(self):
        item = self.preview()
        for action in (lambda: self.preview(actor=self.member), lambda: self.confirm(item, actor=self.member)):
            with self.assertRaises(PermissionDenied): action()
        self.assertIn("title", services.csv_export(actor=self.member, project_id=self.project.id))

    def test_other_manager_cannot_confirm_someone_elses_preview(self):
        item = self.preview()
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(role="facilitator")
        with self.assertRaises(Http404): self.confirm(item, actor=self.member)

    def test_removed_members_outsiders_and_other_project_batches_cannot_read(self):
        batch = self.confirm(self.preview())["batch"]
        other = create_project(actor=self.owner, name="Other project", description="")
        with self.assertRaises(Http404): services.csv_export(actor=self.owner, project_id=other.id, batch_id=batch["id"])
        with self.assertRaises(Http404): services.overview(actor=self.outsider, project_id=self.project.id)
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
        with self.assertRaises(Http404): services.csv_export(actor=self.member, project_id=self.project.id)

    def test_permission_and_archived_project_rechecked_at_confirmation(self):
        item = self.preview()
        self.project.archived_at = timezone.now()
        self.project.save(update_fields=("archived_at",))
        with self.assertRaisesMessage(ValidationError, "read-only"): self.confirm(item)
        with self.assertRaisesMessage(ValidationError, "read-only"): self.preview()
        self.assertFalse(Task.objects.exists())

    def test_requires_explicit_confirmation(self):
        item = self.preview()
        with self.assertRaises(ValidationError): services.confirm(actor=self.owner, project_id=self.project.id, preview_id=item["preview_id"], confirmed=False)

    def test_task_failure_rolls_back_entire_batch_and_activity(self):
        item = self.preview(CSV + b"assignment-2,Second report,,,medium\n")
        real_create = services.create_task
        count = 0
        def fail_second(**kwargs):
            nonlocal count
            count += 1
            if count == 2: raise ValidationError("Test failure")
            return real_create(**kwargs)
        with patch.object(services, "create_task", side_effect=fail_second), self.assertRaises(ValidationError): self.confirm(item)
        self.assertFalse(Task.objects.exists())
        self.assertFalse(ImportBatch.objects.exists())
        self.assertFalse(ImportedAssignment.objects.exists())
        self.assertFalse(ActivityEvent.objects.filter(project=self.project, event_type="task_created").exists())

    def test_csv_formula_protection_and_batch_snapshot_distinct_from_current(self):
        item = self.preview((HEADER + "one,=SUM(1),@literal,,high\n").encode())
        batch = self.confirm(item)["batch"]
        task = Task.objects.get()
        task.title = "Edited later"; task.save()
        snapshot = list(csv.DictReader(io.StringIO(services.csv_export(actor=self.owner, project_id=self.project.id, batch_id=batch["id"]))))
        current = list(csv.DictReader(io.StringIO(services.csv_export(actor=self.owner, project_id=self.project.id))))
        self.assertEqual(snapshot[0]["title"], "'=SUM(1)")
        self.assertEqual(snapshot[0]["description"], "'@literal")
        self.assertEqual(current[0]["title"], "Edited later")

    def test_api_upload_confirm_and_download_contract(self):
        self.authenticate()
        base = f"/api/v1/learning-exchange/projects/{self.project.id}/"
        uploaded = self.client.post(base + "preview/", {"file": SimpleUploadedFile("assignments.csv", CSV, "text/csv"), "source_namespace": "COMP1010"}, format="multipart")
        self.assertEqual(uploaded.status_code, 200, uploaded.data)
        imported = self.client.post(base + "import/", {"preview_id": uploaded.data["preview_id"], "confirmed": True}, format="json")
        self.assertEqual(imported.status_code, 200, imported.data)
        downloaded = self.client.get(base + "export/")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded["Cache-Control"], "private, no-store")
        self.assertIn(b"Final report", downloaded.content)
        self.assertEqual(self.client.get("/api/v1/learning-exchange/sample/").status_code, 200)

    def test_preview_limit_and_history_pagination(self):
        for _ in range(20): self.preview()
        with self.assertRaisesMessage(ValidationError, "limit"): self.preview()
        with self.assertRaises(ValidationError): services.overview(actor=self.owner, project_id=self.project.id, page=0)

    def test_api_multiple_files_rejected_before_reading_closed_partial_upload(self):
        self.authenticate()
        response = self.client.post(f"/api/v1/learning-exchange/projects/{self.project.id}/preview/", {
            "file": [SimpleUploadedFile("one.csv", CSV, "text/csv"), SimpleUploadedFile("two.csv", CSV, "text/csv")],
        }, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ImportPreview.objects.exists())
        self.assertFalse(Task.objects.exists())

    def test_personal_export_withholds_former_project_content_and_closure_removes_previews(self):
        from learning_exchange.account_hooks import export_learning, close_learning
        self.confirm(self.preview())
        self.preview()
        self.assertEqual(export_learning(self.owner)["learning_imports"][0]["rows"][0]["title"], "Final report")
        ProjectMembership.objects.filter(project=self.project, user=self.owner).update(removed_at=timezone.now())
        exported = export_learning(self.owner)
        self.assertTrue(exported["learning_imports"][0]["content_withheld"])
        self.assertNotIn("rows", exported["learning_previews"][0])
        close_learning(self.owner)
        self.assertFalse(ImportPreview.objects.exists())
        self.assertEqual(ImportBatch.objects.count(), 1)

