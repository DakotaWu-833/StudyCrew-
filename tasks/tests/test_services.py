from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from activity.models import ActivityEvent, Notification, SiteAuditEvent
from projects.models import Project, ProjectMembership
from tasks.models import ContentReport, Task, TaskAssignment, TaskComment
from tasks.services import (
    archive_task,
    create_comment,
    create_task,
    delete_comment,
    replace_assignees,
    report_comment,
    resolve_report,
    transition_task,
    update_comment,
    update_task,
)
from tasks.tests.base import TaskDomainTestCase


class TaskServiceTests(TaskDomainTestCase):
    def test_create_task_records_exactly_one_event(self):
        task = create_task(
            project=self.project,
            actor=self.member,
            data={"title": "Draft final report", "priority": Task.Priority.HIGH},
        )
        self.assertEqual(task.priority, Task.Priority.HIGH)
        event = ActivityEvent.objects.get(target_id=task.id)
        self.assertEqual(event.event_type, ActivityEvent.Type.TASK_CREATED)
        self.assertEqual(event.actor, self.member)

    def test_nonmember_cannot_create_task_and_nothing_is_partially_saved(self):
        before_tasks = Task.objects.count()
        before_events = ActivityEvent.objects.count()
        with self.assertRaises(PermissionDenied):
            create_task(project=self.project, actor=self.outsider, data={"title": "Hidden task"})
        self.assertEqual(Task.objects.count(), before_tasks)
        self.assertEqual(ActivityEvent.objects.count(), before_events)

    def test_noop_update_creates_no_event(self):
        task = self.make_task()
        update_task(task=task, actor=self.member, data={"title": task.title})
        self.assertFalse(ActivityEvent.objects.filter(target_id=task.id).exists())

    def test_update_and_archive_are_retained_and_audited(self):
        task = self.make_task()
        update_task(task=task, actor=self.member, data={"title": "Prepare polished demonstration"})
        archive_task(task=task, actor=self.member)
        task.refresh_from_db()
        self.assertIsNotNone(task.archived_at)
        self.assertEqual(
            set(ActivityEvent.objects.filter(target_id=task.id).values_list("event_type", flat=True)),
            {ActivityEvent.Type.TASK_UPDATED, ActivityEvent.Type.TASK_ARCHIVED},
        )

    def test_replace_assignees_is_atomic_and_notifies_new_users(self):
        task = self.make_task()
        replace_assignees(
            task=task,
            actor=self.owner,
            assignee_ids=[self.member.id, self.facilitator.id],
        )
        self.assertEqual(TaskAssignment.objects.filter(task=task).count(), 2)
        self.assertEqual(Notification.objects.filter(source_event__target_id=task.id).count(), 2)

        replace_assignees(task=task, actor=self.owner, assignee_ids=[self.member.id])
        self.assertEqual(list(task.assignees.values_list("id", flat=True)), [self.member.id])

        before = set(task.assignees.values_list("id", flat=True))
        with self.assertRaises(ValidationError):
            replace_assignees(
                task=task,
                actor=self.owner,
                assignee_ids=[self.member.id, self.outsider.id],
            )
        self.assertEqual(set(task.assignees.values_list("id", flat=True)), before)

    def test_assignee_can_block_complete_and_reopen_task(self):
        task = self.make_task()
        TaskAssignment.objects.create(task=task, user=self.member, assigned_by=self.owner)
        with self.assertRaises(ValidationError):
            transition_task(task=task, actor=self.member, status=Task.Status.BLOCKED, blocker_note="")

        transition_task(
            task=task,
            actor=self.member,
            status=Task.Status.BLOCKED,
            blocker_note="Waiting for tutor feedback",
        )
        transition_task(task=task, actor=self.member, status=Task.Status.DONE)
        self.assertIsNotNone(task.completed_at)
        transition_task(task=task, actor=self.member, status=Task.Status.IN_PROGRESS)
        self.assertIsNone(task.completed_at)
        self.assertEqual(task.blocker_note, "")

    def test_unassigned_member_cannot_transition_but_owner_can(self):
        task = self.make_task()
        with self.assertRaises(PermissionDenied):
            transition_task(task=task, actor=self.member, status=Task.Status.IN_PROGRESS)
        transition_task(task=task, actor=self.owner, status=Task.Status.IN_PROGRESS)
        self.assertEqual(task.status, Task.Status.IN_PROGRESS)

    def test_comment_mentions_are_explicit_and_deduplicated(self):
        task = self.make_task()
        comment = create_comment(
            task=task,
            actor=self.member,
            body="Could you review this?",
            mentioned_user_ids=[self.owner.id, self.facilitator.id],
        )
        self.assertEqual(comment.body, "Could you review this?")
        self.assertEqual(Notification.objects.filter(source_event__target_id=comment.id).count(), 2)
        with self.assertRaises(ValidationError):
            create_comment(
                task=task,
                actor=self.member,
                body="Outside mention",
                mentioned_user_ids=[self.outsider.id],
            )

    def test_author_and_facilitator_comment_permissions(self):
        task = self.make_task()
        comment = create_comment(task=task, actor=self.member, body="Initial comment")
        with self.assertRaises(PermissionDenied):
            update_comment(comment=comment, actor=self.outsider, body="Tampered")
        update_comment(comment=comment, actor=self.member, body="Edited by author")
        update_comment(comment=comment, actor=self.facilitator, body="Moderated text")
        self.assertEqual(comment.moderated_by, self.facilitator)
        delete_comment(comment=comment, actor=self.owner)
        self.assertIsNotNone(comment.deleted_at)

    def test_archived_tasks_reject_comments(self):
        task = self.make_task(archived_at=timezone.now())
        with self.assertRaises(ValidationError):
            create_comment(task=task, actor=self.member, body="Too late")

    def test_archived_task_rejects_existing_comment_changes_and_reports(self):
        task = self.make_task()
        comment = TaskComment.objects.create(task=task, author=self.member, body="Retained evidence")
        task.archived_at = timezone.now()
        task.save(update_fields=("archived_at", "updated_at"))

        with self.assertRaises(ValidationError):
            update_comment(comment=comment, actor=self.member, body="Changed too late")
        with self.assertRaises(ValidationError):
            delete_comment(comment=comment, actor=self.member)
        with self.assertRaises(ValidationError):
            report_comment(
                comment=comment,
                actor=self.owner,
                reason=ContentReport.Reason.SPAM,
            )

        comment.refresh_from_db()
        self.assertEqual(comment.body, "Retained evidence")
        self.assertIsNone(comment.deleted_at)
        self.assertFalse(ContentReport.objects.filter(comment=comment).exists())

    def test_archived_tasks_reject_detail_and_assignee_changes(self):
        task = self.make_task(archived_at=timezone.now())

        with self.assertRaises(ValidationError):
            update_task(task=task, actor=self.member, data={"title": "Changed too late"})
        with self.assertRaises(ValidationError):
            replace_assignees(
                task=task,
                actor=self.member,
                assignee_ids=[self.member.id],
            )

        task.refresh_from_db()
        self.assertNotEqual(task.title, "Changed too late")
        self.assertFalse(task.assignments.exists())

    def test_archived_project_blocks_task_and_comment_writes(self):
        task = self.make_task()
        original_title = task.title
        comment = TaskComment.objects.create(task=task, author=self.member, body="Historical note")
        self.project.archived_at = timezone.now()
        self.project.save(update_fields=("archived_at", "updated_at"))
        task_count = Task.objects.count()

        with self.assertRaises(ValidationError):
            create_task(project=self.project, actor=self.owner, data={"title": "New work"})
        with self.assertRaises(ValidationError):
            update_task(task=task, actor=self.owner, data={"title": "Changed work"})
        with self.assertRaises(ValidationError):
            archive_task(task=task, actor=self.owner)
        with self.assertRaises(ValidationError):
            replace_assignees(task=task, actor=self.owner, assignee_ids=[self.member.id])
        with self.assertRaises(ValidationError):
            transition_task(task=task, actor=self.owner, status=Task.Status.DONE)
        with self.assertRaises(ValidationError):
            create_comment(task=task, actor=self.owner, body="New historical note")
        with self.assertRaises(ValidationError):
            update_comment(comment=comment, actor=self.member, body="Changed historical note")
        with self.assertRaises(ValidationError):
            delete_comment(comment=comment, actor=self.member)
        with self.assertRaises(ValidationError):
            report_comment(
                comment=comment,
                actor=self.owner,
                reason=ContentReport.Reason.SPAM,
            )

        task.refresh_from_db()
        comment.refresh_from_db()
        self.assertEqual(Task.objects.count(), task_count)
        self.assertEqual(task.title, original_title)
        self.assertIsNone(task.archived_at)
        self.assertEqual(task.status, Task.Status.TODO)
        self.assertEqual(comment.body, "Historical note")
        self.assertIsNone(comment.deleted_at)

    def test_report_resolution_requires_narrow_permission_and_is_audited(self):
        comment = TaskComment.objects.create(task=self.make_task(), author=self.member, body="Reportable")
        report = report_comment(
            comment=comment,
            actor=self.owner,
            reason=ContentReport.Reason.SPAM,
        )
        with self.assertRaises(PermissionDenied):
            resolve_report(
                report=report,
                actor=self.owner,
                outcome=ContentReport.Status.RESOLVED,
                resolution_note="Reviewed",
            )

        permission = Permission.objects.get(codename="moderate_reports")
        self.facilitator.is_staff = True
        self.facilitator.save(update_fields=("is_staff",))
        self.facilitator.user_permissions.add(permission)
        resolve_report(
            report=report,
            actor=self.facilitator,
            outcome=ContentReport.Status.RESOLVED,
            resolution_note="Confirmed",
            remove_comment=True,
        )
        report.refresh_from_db()
        comment.refresh_from_db()
        self.assertEqual(report.status, ContentReport.Status.RESOLVED)
        self.assertIsNotNone(comment.deleted_at)
        self.assertTrue(SiteAuditEvent.objects.filter(target_id=report.id).exists())
