from unittest.mock import patch

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings
from django.utils import timezone

from accounts.models import User
from activity.models import ActivityEvent
from integrations.reminder_email import ReminderDeliveryError
from projects.models import ProjectMembership
from tasks.models import TaskAssignment
from tasks.tests.base import TaskDomainTestCase
from tasks.workflows import send_task_reminder


SITE_URL = "https://studycrew.example/"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TaskReminderWorkflowTests(TaskDomainTestCase):
    def assign(self, task, *users):
        TaskAssignment.objects.bulk_create(
            [
                TaskAssignment(task=task, user=user, assigned_by=self.owner)
                for user in users
            ]
        )

    def test_owner_sends_separate_emails_only_to_current_eligible_assignees(self):
        task = self.make_task(due_at=timezone.now())
        removed = User.objects.create_user(
            email="removed@example.com",
            password=self.password,
            display_name="Removed Member",
        )
        inactive = User.objects.create_user(
            email="inactive@example.com",
            password=self.password,
            display_name="Inactive Member",
        )
        removed_membership = ProjectMembership.objects.create(
            project=self.project,
            user=removed,
            removed_at=timezone.now(),
        )
        ProjectMembership.objects.create(project=self.project, user=inactive)
        inactive.is_active = False
        inactive.save(update_fields=("is_active", "updated_at"))
        self.assertIsNotNone(removed_membership.removed_at)
        self.assign(task, self.owner, self.member, self.facilitator, removed, inactive)

        result = send_task_reminder(task=task, actor=self.owner, site_url=SITE_URL)

        self.assertEqual(result.recipient_count, 2)
        self.assertEqual(
            {tuple(message.to) for message in mail.outbox},
            {("member@example.com",), ("facilitator@example.com",)},
        )
        self.assertTrue(all(str(task.id) in message.body for message in mail.outbox))
        self.assertTrue(all("tasks/" in message.body for message in mail.outbox))
        event = ActivityEvent.objects.get(
            event_type=ActivityEvent.Type.TASK_REMINDER_SENT,
            target_id=task.id,
        )
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.metadata, {"recipient_count": 2})
        self.assertNotIn("@", str(event.metadata))

    def test_facilitator_can_send_but_member_and_outsider_cannot(self):
        task = self.make_task()
        self.assign(task, self.member)

        result = send_task_reminder(task=task, actor=self.facilitator, site_url=SITE_URL)
        self.assertEqual(result.recipient_count, 1)

        other_task = self.make_task(title="Second reminder target")
        self.assign(other_task, self.member)
        for actor in (self.member, self.outsider):
            with self.subTest(actor=actor.email), self.assertRaises(PermissionDenied):
                send_task_reminder(task=other_task, actor=actor, site_url=SITE_URL)
        self.assertFalse(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.Type.TASK_REMINDER_SENT,
                target_id=other_task.id,
            ).exists()
        )

    def test_archived_task_or_project_cannot_send(self):
        archived_task = self.make_task(archived_at=timezone.now())
        self.assign(archived_task, self.member)
        with self.assertRaises(ValidationError):
            send_task_reminder(task=archived_task, actor=self.owner, site_url=SITE_URL)

        active_task = self.make_task(title="Project archive reminder target")
        self.assign(active_task, self.member)
        self.project.archived_at = timezone.now()
        self.project.save(update_fields=("archived_at", "updated_at"))
        with self.assertRaises(ValidationError):
            send_task_reminder(task=active_task, actor=self.owner, site_url=SITE_URL)

        self.assertEqual(len(getattr(mail, "outbox", [])), 0)

    def test_empty_recipient_set_is_rejected(self):
        task = self.make_task()
        self.assign(task, self.owner)

        with self.assertRaisesMessage(
            ValidationError,
            "This task has no eligible assignees to notify.",
        ):
            send_task_reminder(task=task, actor=self.owner, site_url=SITE_URL)

        self.assertEqual(len(getattr(mail, "outbox", [])), 0)
        self.assertFalse(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.Type.TASK_REMINDER_SENT,
                target_id=task.id,
            ).exists()
        )

    def test_same_task_has_a_sixty_second_cooldown(self):
        task = self.make_task()
        self.assign(task, self.member)
        send_task_reminder(task=task, actor=self.owner, site_url=SITE_URL)

        with self.assertRaisesMessage(ValidationError, "less than 60 seconds ago"):
            send_task_reminder(task=task, actor=self.facilitator, site_url=SITE_URL)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.Type.TASK_REMINDER_SENT,
                target_id=task.id,
            ).count(),
            1,
        )

    @patch("tasks.workflows.deliver_reminder_emails")
    def test_delivery_failure_records_no_success_event(self, deliver):
        deliver.side_effect = ReminderDeliveryError("private SMTP detail")
        task = self.make_task()
        self.assign(task, self.member)

        with self.assertRaises(ReminderDeliveryError):
            send_task_reminder(task=task, actor=self.owner, site_url=SITE_URL)

        self.assertFalse(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.Type.TASK_REMINDER_SENT,
                target_id=task.id,
            ).exists()
        )
