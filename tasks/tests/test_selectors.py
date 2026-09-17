from django.core.exceptions import PermissionDenied, ValidationError
from datetime import timedelta

from django.utils import timezone

from projects.models import Project, ProjectMembership
from tasks.models import Task, TaskAssignment
from tasks.selectors import comment_for_member, task_for_member, tasks_for_project
from tasks.tests.base import TaskDomainTestCase


class TaskSelectorTests(TaskDomainTestCase):
    def test_search_filters_combine_and_do_not_cross_projects(self):
        matching = self.make_task(
            title="Write security report",
            description="Document the HTTPS setup",
            priority=Task.Priority.HIGH,
            due_at=timezone.now() + timedelta(days=1),
        )
        TaskAssignment.objects.create(task=matching, user=self.member, assigned_by=self.owner)
        self.make_task(title="Prepare interface mock-up", priority=Task.Priority.LOW)

        other_project = Project.objects.create(name="Private project", created_by=self.outsider)
        ProjectMembership.objects.create(
            project=other_project,
            user=self.outsider,
            role=ProjectMembership.Role.OWNER,
        )
        Task.objects.create(
            project=other_project,
            created_by=self.outsider,
            title="Write security report elsewhere",
            priority=Task.Priority.HIGH,
        )

        results = tasks_for_project(
            project=self.project,
            user=self.member,
            query="security",
            status=Task.Status.TODO,
            priority=Task.Priority.HIGH,
            assignee_id=self.member.id,
            due="upcoming",
        )
        self.assertEqual(list(results), [matching])

    def test_archived_tasks_are_hidden_by_default(self):
        archived = self.make_task(title="Old task", archived_at=timezone.now())
        self.assertNotIn(archived, tasks_for_project(project=self.project, user=self.member))
        self.assertIn(
            archived,
            tasks_for_project(project=self.project, user=self.member, include_archived=True),
        )

    def test_invalid_filter_is_rejected(self):
        with self.assertRaises(ValidationError):
            tasks_for_project(project=self.project, user=self.member, status="anything")

        with self.assertRaises(ValidationError):
            tasks_for_project(project=self.project, user=self.member, priority="anything")

        with self.assertRaises(ValidationError):
            tasks_for_project(project=self.project, user=self.member, due="anything")

    def test_nonmember_cannot_query_project_tasks(self):
        with self.assertRaises(PermissionDenied):
            tasks_for_project(project=self.project, user=self.outsider)

    def test_single_task_lookup_enforces_membership_and_archive_visibility(self):
        task = self.make_task(title="Visible task")
        self.assertEqual(task_for_member(task_id=task.id, user=self.member), task)

        with self.assertRaises(PermissionDenied):
            task_for_member(task_id=task.id, user=self.outsider)
        with self.assertRaises(Task.DoesNotExist):
            task_for_member(task_id="00000000-0000-0000-0000-000000000000", user=self.member)

        task.archived_at = timezone.now()
        task.save(update_fields=("archived_at",))
        with self.assertRaises(Task.DoesNotExist):
            task_for_member(task_id=task.id, user=self.member)
        self.assertEqual(
            task_for_member(task_id=task.id, user=self.member, include_archived=True),
            task,
        )

    def test_single_comment_lookup_enforces_membership_and_delete_visibility(self):
        from tasks.models import TaskComment

        task = self.make_task(title="Commented task")
        comment = TaskComment.objects.create(task=task, author=self.member, body="Visible comment")
        self.assertEqual(comment_for_member(comment_id=comment.id, user=self.member), comment)

        with self.assertRaises(PermissionDenied):
            comment_for_member(comment_id=comment.id, user=self.outsider)
        with self.assertRaises(TaskComment.DoesNotExist):
            comment_for_member(
                comment_id="00000000-0000-0000-0000-000000000000",
                user=self.member,
            )

        comment.deleted_at = timezone.now()
        comment.save(update_fields=("deleted_at",))
        with self.assertRaises(TaskComment.DoesNotExist):
            comment_for_member(comment_id=comment.id, user=self.member)
        self.assertEqual(
            comment_for_member(
                comment_id=comment.id,
                user=self.member,
                include_deleted=True,
            ),
            comment,
        )

    def test_due_filters_cover_overdue_upcoming_and_no_due_date(self):
        now = timezone.now()
        overdue = self.make_task(title="Overdue task", due_at=now - timedelta(days=1))
        done_overdue = self.make_task(
            title="Completed overdue task",
            due_at=now - timedelta(days=1),
            status=Task.Status.DONE,
            completed_at=now,
        )
        upcoming = self.make_task(title="Upcoming task", due_at=now + timedelta(days=1))
        undated = self.make_task(title="Undated task", due_at=None)

        self.assertEqual(
            list(tasks_for_project(project=self.project, user=self.member, due="overdue")),
            [overdue],
        )
        self.assertIn(
            upcoming,
            tasks_for_project(project=self.project, user=self.member, due="upcoming"),
        )
        self.assertEqual(
            list(tasks_for_project(project=self.project, user=self.member, due="none")),
            [undated],
        )
        self.assertNotIn(
            done_overdue,
            tasks_for_project(project=self.project, user=self.member, due="overdue"),
        )
