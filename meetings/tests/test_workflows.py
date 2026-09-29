from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from activity.models import ActivityEvent
from integrations.reminder_email import ReminderDeliveryError
from meetings.models import Meeting
from meetings.workflows import send_meeting_reminder
from projects.models import Project, ProjectMembership


PASSWORD = "Correct-Horse-7-Battery!"
SITE_URL = "https://studycrew.example/"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MeetingReminderWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            email="meeting-owner@example.com",
            password=PASSWORD,
            display_name="Meeting Owner",
        )
        cls.facilitator = User.objects.create_user(
            email="meeting-facilitator@example.com",
            password=PASSWORD,
            display_name="Meeting Facilitator",
        )
        cls.organiser = User.objects.create_user(
            email="meeting-organiser@example.com",
            password=PASSWORD,
            display_name="Meeting Organiser",
        )
        cls.member = User.objects.create_user(
            email="meeting-member@example.com",
            password=PASSWORD,
            display_name="Meeting Member",
        )
        cls.outsider = User.objects.create_user(
            email="meeting-outsider@example.com",
            password=PASSWORD,
            display_name="Meeting Outsider",
        )
        cls.project = Project.objects.create(
            name="Meeting reminder project",
            created_by=cls.owner,
        )
        for user, role in (
            (cls.owner, ProjectMembership.Role.OWNER),
            (cls.facilitator, ProjectMembership.Role.FACILITATOR),
            (cls.organiser, ProjectMembership.Role.MEMBER),
            (cls.member, ProjectMembership.Role.MEMBER),
        ):
            ProjectMembership.objects.create(project=cls.project, user=user, role=role)

    def make_meeting(self, **overrides):
        starts_at = timezone.now() + timedelta(days=2)
        values = {
            "project": self.project,
            "organiser": self.organiser,
            "title": "Iteration planning",
            "starts_at": starts_at,
            "ends_at": starts_at + timedelta(hours=1),
            "location": "Library room 2",
        }
        values.update(overrides)
        return Meeting.objects.create(**values)

    def test_owner_sends_separate_emails_only_to_current_active_members(self):
        removed = User.objects.create_user(
            email="meeting-removed@example.com",
            password=PASSWORD,
        )
        inactive = User.objects.create_user(
            email="meeting-inactive@example.com",
            password=PASSWORD,
        )
        ProjectMembership.objects.create(
            project=self.project,
            user=removed,
            removed_at=timezone.now(),
        )
        ProjectMembership.objects.create(project=self.project, user=inactive)
        inactive.is_active = False
        inactive.save(update_fields=("is_active", "updated_at"))
        meeting = self.make_meeting()

        result = send_meeting_reminder(
            meeting=meeting,
            actor=self.owner,
            site_url=SITE_URL,
        )

        self.assertEqual(result.recipient_count, 3)
        self.assertEqual(
            {tuple(message.to) for message in mail.outbox},
            {
                ("meeting-facilitator@example.com",),
                ("meeting-organiser@example.com",),
                ("meeting-member@example.com",),
            },
        )
        self.assertTrue(all("/meetings/" in message.body for message in mail.outbox))
        event = ActivityEvent.objects.get(
            event_type=ActivityEvent.Type.MEETING_REMINDER_SENT,
            target_id=meeting.id,
        )
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.metadata, {"recipient_count": 3})
        self.assertNotIn("@", str(event.metadata))

    def test_facilitator_can_send_but_ordinary_organiser_and_outsider_cannot(self):
        meeting = self.make_meeting()
        result = send_meeting_reminder(
            meeting=meeting,
            actor=self.facilitator,
            site_url=SITE_URL,
        )
        self.assertEqual(result.recipient_count, 3)

        other = self.make_meeting(title="Permission boundary meeting")
        for actor in (self.organiser, self.outsider):
            with self.subTest(actor=actor.email), self.assertRaises(PermissionDenied):
                send_meeting_reminder(meeting=other, actor=actor, site_url=SITE_URL)
        self.assertFalse(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.Type.MEETING_REMINDER_SENT,
                target_id=other.id,
            ).exists()
        )

    def test_cancelled_ended_archived_and_archived_project_states_are_rejected(self):
        now = timezone.now()
        cancelled = self.make_meeting(cancelled_at=now)
        ended = self.make_meeting(
            title="Ended meeting",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
        )
        archived = self.make_meeting(
            title="Archived meeting",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
            archived_at=now,
        )
        for meeting in (cancelled, ended, archived):
            with self.subTest(meeting=meeting.title), self.assertRaises(ValidationError):
                send_meeting_reminder(
                    meeting=meeting,
                    actor=self.owner,
                    site_url=SITE_URL,
                )

        active = self.make_meeting(title="Archived project meeting")
        self.project.archived_at = now
        self.project.save(update_fields=("archived_at", "updated_at"))
        with self.assertRaises(ValidationError):
            send_meeting_reminder(meeting=active, actor=self.owner, site_url=SITE_URL)
        self.assertEqual(len(getattr(mail, "outbox", [])), 0)

    def test_same_meeting_has_a_sixty_second_cooldown(self):
        meeting = self.make_meeting()
        send_meeting_reminder(meeting=meeting, actor=self.owner, site_url=SITE_URL)

        with self.assertRaisesMessage(ValidationError, "less than 60 seconds ago"):
            send_meeting_reminder(
                meeting=meeting,
                actor=self.facilitator,
                site_url=SITE_URL,
            )

        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.Type.MEETING_REMINDER_SENT,
                target_id=meeting.id,
            ).count(),
            1,
        )

    def test_solo_project_has_no_eligible_recipient(self):
        solo_owner = User.objects.create_user(email="solo@example.com", password=PASSWORD)
        solo_project = Project.objects.create(name="Solo project", created_by=solo_owner)
        ProjectMembership.objects.create(
            project=solo_project,
            user=solo_owner,
            role=ProjectMembership.Role.OWNER,
        )
        starts_at = timezone.now() + timedelta(days=1)
        meeting = Meeting.objects.create(
            project=solo_project,
            organiser=solo_owner,
            title="Solo meeting",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
        )

        with self.assertRaisesMessage(
            ValidationError,
            "This meeting has no eligible project members to notify.",
        ):
            send_meeting_reminder(
                meeting=meeting,
                actor=solo_owner,
                site_url=SITE_URL,
            )

    @patch("meetings.workflows.deliver_reminder_emails")
    def test_delivery_failure_records_no_success_event(self, deliver):
        deliver.side_effect = ReminderDeliveryError("private SMTP detail")
        meeting = self.make_meeting()

        with self.assertRaises(ReminderDeliveryError):
            send_meeting_reminder(
                meeting=meeting,
                actor=self.owner,
                site_url=SITE_URL,
            )

        self.assertFalse(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.Type.MEETING_REMINDER_SENT,
                target_id=meeting.id,
            ).exists()
        )
