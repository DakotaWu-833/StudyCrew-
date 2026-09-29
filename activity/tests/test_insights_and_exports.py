from datetime import date, datetime, timedelta, timezone as datetime_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from activity.exports import _render_pdf, export_file_for_user, request_export
from activity.insights import activity_timeline_page, contribution_insights
from activity.models import ActivityEvent, ExportJob
from activity.services import record_event
from meetings.models import Meeting, MeetingAttendance
from projects.models import Project, ProjectMembership
from tasks.models import Task, TaskAssignment


class InsightsAndExportTests(TestCase):
    password = "Strong!Passphrase42"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(
            email="insight-owner@example.com", password=cls.password, display_name="Owner"
        )
        cls.member = User.objects.create_user(
            email="insight-member@example.com", password=cls.password, display_name="Member"
        )
        cls.outsider = User.objects.create_user(
            email="insight-outsider@example.com", password=cls.password, display_name="Outsider"
        )
        cls.project = Project.objects.create(name="Insight project", created_by=cls.owner)
        ProjectMembership.objects.create(
            project=cls.project, user=cls.owner, role=ProjectMembership.Role.OWNER
        )
        ProjectMembership.objects.create(project=cls.project, user=cls.member)

    def setUp(self):
        # Insight ranges are interpreted in the requesting user's preferred
        # zone, so derive the fixture date in that same zone. This remains
        # stable around UTC/local-midnight boundaries.
        self.today = timezone.localdate(
            timezone.now(), ZoneInfo(self.member.profile.time_zone)
        )

    def test_insights_include_zero_activity_members_and_factual_counts(self):
        record_event(
            project=self.project,
            actor=self.owner,
            event_type=ActivityEvent.Type.COMMENT_CREATED,
            target_type=ActivityEvent.TargetType.COMMENT,
            target_id=self.project.id,
        )
        record_event(
            project=self.project,
            actor=self.owner,
            event_type=ActivityEvent.Type.TASK_STATUS_CHANGED,
            target_type=ActivityEvent.TargetType.TASK,
            target_id=self.project.id,
            metadata={"from": "in_progress", "to": "done"},
        )
        meeting = Meeting.objects.create(
            project=self.project,
            organiser=self.owner,
            title="Accepted planning meeting",
            starts_at=datetime.combine(
                self.today, datetime.min.time(), tzinfo=datetime_timezone.utc
            )
            + timedelta(hours=12),
            ends_at=datetime.combine(
                self.today, datetime.min.time(), tzinfo=datetime_timezone.utc
            )
            + timedelta(hours=13),
        )
        MeetingAttendance.objects.create(
            meeting=meeting,
            user=self.owner,
            response=MeetingAttendance.Response.ACCEPTED,
            responded_at=timezone.now(),
        )

        result = contribution_insights(
            user=self.member,
            project=self.project,
            range_start=self.today,
            range_end=self.today,
        )
        by_id = {row["user_id"]: row for row in result["members"]}
        self.assertEqual(by_id[self.owner.id]["total_events"], 2)
        self.assertEqual(by_id[self.owner.id]["completed_tasks"], 1)
        self.assertEqual(by_id[self.owner.id]["comments"], 1)
        self.assertEqual(by_id[self.owner.id]["accepted_meetings"], 1)
        self.assertEqual(by_id[self.member.id]["total_events"], 0)

    def test_insights_charts_use_complete_task_data_and_selected_local_dates(self):
        local_start = datetime.combine(
            self.today, datetime.min.time(), tzinfo=ZoneInfo(self.member.profile.time_zone)
        )
        created_at = (local_start + timedelta(hours=8)).astimezone(datetime_timezone.utc)
        completed_at = created_at + timedelta(hours=2)
        todo = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Unassigned planning task",
            priority=Task.Priority.LOW,
        )
        in_progress = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Shared research task",
            status=Task.Status.IN_PROGRESS,
            priority=Task.Priority.HIGH,
        )
        done = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Finished task",
            status=Task.Status.DONE,
            priority=Task.Priority.MEDIUM,
            completed_at=completed_at,
        )
        archived = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Archived blocked task",
            status=Task.Status.BLOCKED,
            priority=Task.Priority.URGENT,
            blocker_note="Waiting on review",
        )
        Task.objects.filter(id__in=(todo.id, in_progress.id, done.id, archived.id)).update(
            created_at=created_at
        )
        Task.objects.filter(pk=done.pk).update(completed_at=completed_at, created_at=created_at)
        Task.objects.filter(pk=archived.pk).update(archived_at=created_at)
        TaskAssignment.objects.create(task=in_progress, user=self.owner, assigned_by=self.owner)
        TaskAssignment.objects.create(task=in_progress, user=self.member, assigned_by=self.owner)

        result = contribution_insights(
            user=self.member,
            project=self.project,
            range_start=self.today,
            range_end=self.today,
        )
        charts = result["charts"]
        self.assertEqual(
            [(row["key"], row["count"]) for row in charts["task_status"]],
            [("todo", 1), ("in_progress", 1), ("blocked", 0), ("done", 1)],
        )
        self.assertEqual(
            {row["key"]: row["count"] for row in charts["task_priority"]},
            {"low": 1, "medium": 1, "high": 1, "urgent": 0},
        )
        self.assertEqual(
            [(row["label"], row["count"]) for row in charts["task_assignees"]],
            [("Member", 1), ("Owner", 1), ("Unassigned", 1)],
        )
        self.assertEqual(charts["tasks_created"], [{"date": self.today.isoformat(), "count": 4}])
        self.assertEqual(
            charts["completion_cycle"],
            [{"date": self.today.isoformat(), "count": 1, "average_hours": 2.0}],
        )

    def test_timeline_search_member_filter_and_page_apply_to_full_event_query(self):
        local_start = datetime.combine(
            self.today, datetime.min.time(), tzinfo=ZoneInfo(self.member.profile.time_zone)
        )
        for offset in range(12):
            is_task = offset % 2 == 0
            actor = self.member if offset % 3 == 0 else self.owner
            ActivityEvent.objects.create(
                project=self.project,
                actor=actor,
                event_type=(
                    ActivityEvent.Type.TASK_CREATED
                    if is_task
                    else ActivityEvent.Type.COMMENT_CREATED
                ),
                target_type=(
                    ActivityEvent.TargetType.TASK
                    if is_task
                    else ActivityEvent.TargetType.COMMENT
                ),
                target_id=self.project.id,
                occurred_at=(local_start + timedelta(hours=10, seconds=offset)).astimezone(
                    datetime_timezone.utc
                ),
            )

        task_page = activity_timeline_page(
            user=self.member,
            project=self.project,
            range_start=self.today,
            range_end=self.today,
            search="TASK",
            page=2,
        )
        self.assertEqual(task_page["events_total"], 6)
        self.assertEqual(task_page["events_pages"], 2)
        self.assertEqual(task_page["events_page"], 2)
        self.assertEqual(len(task_page["events"]), 1)
        self.assertEqual(task_page["events"][0].event_type, ActivityEvent.Type.TASK_CREATED)

        member_events = activity_timeline_page(
            user=self.member,
            project=self.project,
            range_start=self.today,
            range_end=self.today,
            member_id=self.member.id,
            search="member",
            page=99,
        )
        self.assertEqual(member_events["events_total"], 4)
        self.assertEqual(member_events["events_page"], 1)
        self.assertEqual(member_events["events_pages"], 1)
        self.assertEqual(len(member_events["events"]), 4)
        self.assertTrue(all(event.actor_id == self.member.id for event in member_events["events"]))

    def test_insight_range_and_event_filter_are_validated(self):
        with self.assertRaises(ValidationError):
            contribution_insights(
                user=self.owner,
                project=self.project,
                range_start=self.today,
                range_end=self.today + timedelta(days=367),
            )
        with self.assertRaises(ValidationError):
            contribution_insights(
                user=self.owner,
                project=self.project,
                range_start=self.today,
                range_end=self.today,
                event_type="not-real",
            )
        with self.assertRaises(PermissionDenied):
            contribution_insights(
                user=self.outsider,
                project=self.project,
                range_start=self.today,
                range_end=self.today,
            )

    def test_csv_and_pdf_exports_are_created_and_authorised(self):
        with TemporaryDirectory() as temporary_media, override_settings(MEDIA_ROOT=temporary_media):
            for export_format, prefix in ((ExportJob.Format.CSV, b"\xef\xbb\xbf"), (ExportJob.Format.PDF, b"%PDF")):
                job = request_export(
                    actor=self.owner,
                    project=self.project,
                    export_format=export_format,
                    range_start=self.today,
                    range_end=self.today,
                )
                self.assertEqual(job.status, ExportJob.Status.READY)
                path = export_file_for_user(job=job, user=self.owner)
                self.assertTrue(path.read_bytes().startswith(prefix))
                with self.assertRaises(PermissionDenied):
                    export_file_for_user(job=job, user=self.member)

    def test_csv_export_neutralises_spreadsheet_formulas(self):
        self.project.name = "=HYPERLINK(\"https://example.invalid\")"
        self.project.save(update_fields=("name", "updated_at"))
        self.owner.profile.display_name = "+cmd|' /C calc'!A0"
        self.owner.profile.save(update_fields=("display_name", "updated_at"))

        with TemporaryDirectory() as temporary_media, override_settings(MEDIA_ROOT=temporary_media):
            job = request_export(
                actor=self.owner,
                project=self.project,
                export_format=ExportJob.Format.CSV,
                range_start=self.today,
                range_end=self.today,
            )
            payload = export_file_for_user(job=job, user=self.owner).read_text(
                encoding="utf-8-sig"
            )

        self.assertIn("'\u003dHYPERLINK", payload)
        self.assertIn("'\u002bcmd", payload)

    def test_pdf_wraps_without_dropping_member_totals_or_event_target(self):
        long_name = "EvidenceReviewer" * 5
        self.owner.profile.display_name = long_name
        self.owner.profile.save(update_fields=("display_name", "updated_at"))
        record_event(
            project=self.project,
            actor=self.owner,
            event_type=ActivityEvent.Type.COMMENT_CREATED,
            target_type=ActivityEvent.TargetType.COMMENT,
            target_id=self.project.id,
        )
        insights = contribution_insights(
            user=self.owner,
            project=self.project,
            range_start=self.today,
            range_end=self.today,
        )

        with patch("activity.exports.canvas.Canvas") as canvas_class:
            _render_pdf(project=self.project, insights=insights)

        drawn = "".join(
            call.args[2] for call in canvas_class.return_value.drawString.call_args_list
        )
        self.assertIn(long_name, drawn)
        self.assertIn("acceptedmeetings", drawn.replace(" ", ""))
        self.assertIn(str(self.project.id), drawn)

    def test_expired_and_tampered_export_paths_are_rejected(self):
        with TemporaryDirectory() as temporary_media, override_settings(MEDIA_ROOT=temporary_media):
            job = request_export(
                actor=self.owner,
                project=self.project,
                export_format=ExportJob.Format.CSV,
                range_start=self.today,
                range_end=self.today,
            )
            job.expires_at = timezone.now() - timedelta(seconds=1)
            job.save(update_fields=("expires_at",))
            with self.assertRaises(ValidationError):
                export_file_for_user(job=job, user=self.owner)
            job.status = ExportJob.Status.READY
            job.expires_at = timezone.now() + timedelta(hours=1)
            job.storage_key = "../../outside.csv"
            job.save(update_fields=("status", "expires_at", "storage_key"))
            with self.assertRaises(PermissionDenied):
                export_file_for_user(job=job, user=self.owner)

    def test_export_failure_is_retained_without_leaking_exception(self):
        with TemporaryDirectory() as temporary_media, override_settings(MEDIA_ROOT=temporary_media):
            with self.assertLogs("activity.exports", level="ERROR"):
                with self.settings(MEDIA_ROOT=Path(temporary_media) / "missing" / "\0invalid"):
                    job = request_export(
                        actor=self.owner,
                        project=self.project,
                        export_format=ExportJob.Format.CSV,
                        range_start=self.today,
                        range_end=self.today,
                    )
            self.assertEqual(job.status, ExportJob.Status.FAILED)
            self.assertNotIn("invalid", job.error_message.lower())
