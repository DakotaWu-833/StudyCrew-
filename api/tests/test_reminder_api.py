from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from django.utils import timezone

from accounts.models import User
from activity.models import ActivityEvent
from api.tests.base import APIDomainTestCase
from integrations.reminder_email import ReminderDeliveryError
from meetings.models import Meeting
from projects.models import ProjectMembership
from tasks.models import Task, TaskAssignment


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ReminderAPITests(APIDomainTestCase):
    def setUp(self):
        super().setUp()
        mail.outbox = []
        self.facilitator = User.objects.create_user(
            email="api-facilitator@example.com",
            password=self.password,
            display_name="API Facilitator",
        )
        ProjectMembership.objects.create(
            project=self.project,
            user=self.facilitator,
            role=ProjectMembership.Role.FACILITATOR,
        )
        self.task = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Prepare acceptance evidence",
            due_at=timezone.now() + timedelta(days=3),
        )
        TaskAssignment.objects.create(
            task=self.task,
            user=self.member,
            assigned_by=self.owner,
        )
        self.meeting = Meeting.objects.create(
            project=self.project,
            organiser=self.member,
            title="Acceptance rehearsal",
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=1),
            location="Engineering room 2",
        )

    def test_owner_can_email_current_task_assignees(self):
        self.authenticate(self.owner)

        response = self.client.post(
            f"/api/v1/tasks/{self.task.id}/send-reminder/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["recipient_count"], 1)
        self.assertIn("sent_at", response.json())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.member.email])
        self.assertIn(str(self.task.id), mail.outbox[0].body)
        event = ActivityEvent.objects.get(event_type=ActivityEvent.Type.TASK_REMINDER_SENT)
        self.assertEqual(event.metadata, {"recipient_count": 1})

    def test_facilitator_can_email_current_meeting_members_individually(self):
        self.authenticate(self.facilitator)

        response = self.client.post(
            f"/api/v1/meetings/{self.meeting.id}/send-reminder/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["recipient_count"], 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertCountEqual([message.to for message in mail.outbox], [[self.owner.email], [self.member.email]])
        self.assertTrue(all(len(message.to) == 1 for message in mail.outbox))

    def test_member_organiser_cannot_send_meeting_email(self):
        self.authenticate(self.member)

        response = self.client.post(
            f"/api/v1/meetings/{self.meeting.id}/send-reminder/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.Type.MEETING_REMINDER_SENT
            ).exists()
        )

    def test_reminder_action_rejects_caller_supplied_recipients(self):
        self.authenticate(self.owner)

        response = self.client.post(
            f"/api/v1/tasks/{self.task.id}/send-reminder/",
            {"recipient_emails": [self.outsider.email]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("recipient_emails", response.json()["error"]["fields"])
        self.assertEqual(mail.outbox, [])

        null_body = self.client.generic(
            "POST",
            f"/api/v1/tasks/{self.task.id}/send-reminder/",
            "null",
            content_type="application/json",
        )
        self.assertEqual(null_body.status_code, 400)

    def test_delivery_error_is_a_safe_503_without_false_audit_event(self):
        self.authenticate(self.owner)

        with patch(
            "tasks.workflows.deliver_reminder_emails",
            side_effect=ReminderDeliveryError("smtp-password-secret"),
        ):
            response = self.client.post(
                f"/api/v1/tasks/{self.task.id}/send-reminder/",
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("smtp-password-secret", response.content.decode())
        self.assertFalse(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.Type.TASK_REMINDER_SENT
            ).exists()
        )

    def test_second_reminder_within_cooldown_is_rejected(self):
        self.authenticate(self.owner)
        url = f"/api/v1/tasks/{self.task.id}/send-reminder/"

        self.assertEqual(self.client.post(url, {}, format="json").status_code, 200)
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 1)

    def test_cross_project_user_cannot_use_reminder_endpoint(self):
        self.authenticate(self.outsider)

        response = self.client.post(
            f"/api/v1/tasks/{self.task.id}/send-reminder/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(mail.outbox, [])
