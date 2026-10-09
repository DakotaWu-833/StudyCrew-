import json
from datetime import datetime, timedelta, timezone as utc
from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError
from api.tests.base import APIDomainTestCase
from accounts.readiness_services import personal_data_download
from campus import selectors, services
from campus.models import TaskPlan, ChecklistItem
from coordination.models import MeetingRecord
from coordination.services import save_meeting_record
from meetings.models import Meeting
from operations.models import ProjectPost, PostReply
from projects.models import ProjectMembership
from projects.services import create_project
from tasks.models import Task, TaskComment
from tasks.services import create_task, replace_assignees, update_task


class LaunchExtrasTests(APIDomainTestCase):
    def task(self, title="Launch task", **values):
        return create_task(actor=self.owner, project=self.project, data={"title": title, **values})

    def test_today_week_use_student_timezone_and_boundary(self):
        self.owner.profile.time_zone = "Australia/Sydney"; self.owner.profile.save()
        now = datetime(2026, 10, 1, 14, 30, tzinfo=utc.utc)  # Oct 2 in Sydney
        today = self.task("Today", due_at=now + timedelta(hours=1))
        yesterday = self.task("Yesterday", due_at=now - timedelta(hours=6))
        next_week = self.task("Outside week", due_at=now + timedelta(days=8))
        for task in (today, yesterday, next_week): replace_assignees(task=task, actor=self.owner, assignee_ids=[self.owner.pk])
        with patch("django.utils.timezone.now", return_value=now):
            self.assertEqual([str(row["id"]) for row in selectors.personal_todos(user=self.owner, due="today")["results"]], [str(today.pk)])
            self.assertEqual(len(selectors.personal_todos(user=self.owner, due="week")["results"]), 1)

    def test_copy_preserves_structure_but_clears_completion_attribution_and_dates(self):
        task = self.task(due_at=datetime(2026, 12, 1, tzinfo=utc.utc))
        services.save_task_plan(actor=self.owner, project_id=self.project.pk, task_id=task.pk,
            data={"tags": ["Research"], "estimate_hours": Decimal("3.50"), "reviewer": self.member.pk, "outcome_url": "https://example.com/work"})
        ChecklistItem.objects.create(task=task, text="Check sources", checked=True)
        replace_assignees(task=task, actor=self.owner, assignee_ids=[self.member.pk])
        copied = services.copy_task(actor=self.owner, project_id=self.project.pk, task_id=task.pk, title="Copied work")
        self.assertEqual(copied.academic_plan.tags, ["research"]); self.assertEqual(copied.academic_plan.estimate_hours, Decimal("3.50"))
        self.assertFalse(copied.assignees.exists()); self.assertIsNone(copied.due_at)
        self.assertFalse(copied.academic_checklist.get().checked); self.assertIsNone(copied.academic_plan.reviewer)
        self.assertEqual(copied.academic_plan.outcome_url, "")

    def test_bulk_is_atomic_and_direct_edit_cannot_bypass_official_deadline(self):
        first, second = self.task("First"), self.task("Second")
        official = datetime(2026, 12, 1, tzinfo=utc.utc)
        TaskPlan.objects.create(task=second, official_due_at=official)
        with self.assertRaises(ValidationError): services.bulk_update_tasks(actor=self.owner, project_id=self.project.pk,
            task_ids=[first.pk, second.pk], data={"priority": "urgent", "internal_due_at": official + timedelta(days=1)})
        self.assertFalse(Task.objects.filter(project=self.project, priority="urgent").exists())
        with self.assertRaises(ValidationError): update_task(task=second, actor=self.owner, data={"due_at": official + timedelta(days=1)})
        services.bulk_update_tasks(actor=self.owner, project_id=self.project.pk, task_ids=[first.pk, second.pk], data={"priority": "high", "assignees": [self.member.pk]})
        self.assertEqual(Task.objects.filter(project=self.project, priority="high", assignments__user=self.member).count(), 2)

    def test_search_all_domains_pagination_removed_content_and_lost_membership(self):
        task = self.task("needle task")
        TaskComment.objects.create(task=task, author=self.owner, body="needle comment")
        deleted = TaskComment.objects.create(task=task, author=self.owner, body="needle removed", deleted_at=datetime.now(utc.utc))
        meeting = Meeting.objects.create(project=self.project, organiser=self.owner, title="needle meeting",
            starts_at=datetime(2026, 9, 1, tzinfo=utc.utc), ends_at=datetime(2026, 9, 1, 1, tzinfo=utc.utc))
        MeetingRecord.objects.create(meeting=meeting, minutes="needle minutes")
        post = ProjectPost.objects.create(project=self.project, author=self.owner, title="needle discussion", body="Decision")
        PostReply.objects.create(post=post, author=self.member, body="needle reply")
        other = create_project(actor=self.outsider, name="needle secret")
        Task.objects.create(project=other, created_by=self.outsider, title="needle private")
        data = selectors.search(user=self.member, query="needle")
        for group in ("tasks", "meetings", "minutes", "comments", "discussions", "replies"): self.assertEqual(data["counts"][group], 1, group)
        self.assertNotIn(str(deleted.pk), json.dumps(data, default=str)); self.assertNotIn("needle private", json.dumps(data, default=str))
        Task.objects.bulk_create([Task(project=self.project, created_by=self.owner, title=f"needle item {index}") for index in range(30)])
        page = selectors.search(user=self.member, query="needle", page=2)
        self.assertEqual(page["counts"]["tasks"], 31); self.assertEqual(len(page["tasks"]), 6)
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=datetime.now(utc.utc))
        self.assertEqual(selectors.search(user=self.member, query="needle")["total"], 0)

    def test_stale_task_minutes_and_agreement_edits_preserve_current_data(self):
        task = self.task(); stale = task.updated_at
        update_task(task=task, actor=self.owner, data={"title": "Current title", "expected_updated_at": stale})
        with self.assertRaises(ValidationError): update_task(task=task, actor=self.member, data={"title": "Lost update", "expected_updated_at": stale})
        task.refresh_from_db(); self.assertEqual(task.title, "Current title")
        agreement = services.save_agreement(actor=self.owner, project_id=self.project.pk, body="Initial agreement", expected_revision=0)
        services.save_agreement(actor=self.owner, project_id=self.project.pk, body="Current agreement", expected_revision=agreement.revision)
        with self.assertRaises(ValidationError): services.save_agreement(actor=self.owner, project_id=self.project.pk, body="Lost agreement", expected_revision=1)
        meeting = Meeting.objects.create(project=self.project, organiser=self.owner, title="Past meeting",
            starts_at=datetime(2025, 1, 1, tzinfo=utc.utc), ends_at=datetime(2025, 1, 1, 1, tzinfo=utc.utc))
        record = save_meeting_record(actor=self.owner, meeting=meeting, minutes="First minutes", expected_version=0)
        save_meeting_record(actor=self.owner, meeting=meeting, minutes="Current minutes", expected_version=record.version)
        with self.assertRaises(ValidationError): save_meeting_record(actor=self.owner, meeting=meeting, minutes="Lost minutes", expected_version=record.version)
        record.refresh_from_db(); self.assertEqual(record.minutes, "Current minutes")

    def test_personal_export_includes_my_profile_posts_and_replies_without_others_identity(self):
        profile = self.owner.profile; profile.major = "Computer Science"; profile.skills = ["Python"]; profile.save()
        mine = ProjectPost.objects.create(project=self.project, author=self.owner, title="My discussion", body="My written record")
        other = ProjectPost.objects.create(project=self.project, author=self.member, title="Other discussion", body="Other private record")
        PostReply.objects.create(post=other, author=self.owner, body="My reply")
        data = json.loads(personal_data_download(self.owner))
        self.assertEqual(data["profile"]["major"], "Computer Science")
        self.assertEqual([row["id"] for row in data["records"]["operations.ProjectPost"]], [str(mine.pk)])
        text = json.dumps(data); self.assertIn("My reply", text); self.assertNotIn(self.member.email, text); self.assertNotIn("Other private record", text)

    def test_personal_export_of_former_member_withholds_subsequent_shared_edits(self):
        task = self.task()
        post = ProjectPost.objects.create(project=self.project, author=self.owner, title="Original post", body="Original text")
        ProjectMembership.objects.filter(project=self.project, user=self.owner).update(removed_at=datetime.now(utc.utc))
        Task.objects.filter(pk=task.pk).update(description="New remaining-team private text")
        ProjectPost.objects.filter(pk=post.pk).update(body="New manager private text")
        data = json.loads(personal_data_download(self.owner))
        text = json.dumps(data); self.assertNotIn("New remaining-team private text", text); self.assertNotIn("New manager private text", text)
        self.assertTrue(data["records"]["tasks.Task"][0]["content_withheld"])
