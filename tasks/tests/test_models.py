from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from tasks.models import ContentReport, Task, TaskAssignment, TaskComment
from tasks.tests.base import TaskDomainTestCase


class TaskModelTests(TaskDomainTestCase):
    def test_blocked_task_requires_meaningful_note(self):
        task = Task(
            project=self.project,
            created_by=self.owner,
            title="Resolve data migration",
            status=Task.Status.BLOCKED,
            blocker_note="no",
        )
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_done_state_and_completion_timestamp_must_match(self):
        missing_time = Task(
            project=self.project,
            created_by=self.owner,
            title="Complete deployment guide",
            status=Task.Status.DONE,
        )
        with self.assertRaises(ValidationError):
            missing_time.full_clean()

        open_with_time = Task(
            project=self.project,
            created_by=self.owner,
            title="Review security settings",
            completed_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            open_with_time.full_clean()

    def test_task_assignment_pair_is_unique(self):
        task = self.make_task()
        TaskAssignment.objects.create(task=task, user=self.member, assigned_by=self.owner)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskAssignment.objects.create(task=task, user=self.member, assigned_by=self.owner)

    def test_comment_is_plain_text_and_trimmed_by_validation(self):
        task = self.make_task()
        comment = TaskComment(task=task, author=self.member, body="  <script>alert(1)</script>  ")
        comment.full_clean()
        self.assertEqual(comment.body, "<script>alert(1)</script>")
        self.assertIn("<script>", comment.body)

    def test_other_report_requires_details(self):
        comment = TaskComment.objects.create(task=self.make_task(), author=self.member, body="Review me")
        report = ContentReport(
            comment=comment,
            reporter=self.owner,
            reason=ContentReport.Reason.OTHER,
        )
        with self.assertRaises(ValidationError):
            report.full_clean()
