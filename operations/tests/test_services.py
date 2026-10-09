from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.utils import timezone

from operations.models import NotificationPreference, OutboundMessage, ProjectMute, RateBucket, SuppressedAddress, UserAlert, UserBlock
from operations.services import (
    channel_enabled, consume_rate, enqueue_email, message_eligible, quiet_until,
    schedule_reminders, update_preferences,
)
from projects.models import ProjectInvitation
from meetings.models import MeetingAttendance
from .helpers import OperationsTestCase


class NotificationServiceTests(OperationsTestCase):
    def test_preferences_apply_global_category_project_mute_and_sender_block(self):
        self.assertTrue(channel_enabled(self.member, "task_due", self.project))
        update_preferences(self.member, {"task_reminders": False})
        self.assertFalse(channel_enabled(self.member, "task_due", self.project))
        self.assertTrue(channel_enabled(self.member, "meeting_reminder", self.project))
        ProjectMute.objects.create(user=self.member, project=self.project, muted=True)
        self.assertFalse(channel_enabled(self.member, "meeting_reminder", self.project))
        self.assertTrue(channel_enabled(self.member, "meeting_reminder"))
        UserBlock.objects.create(user=self.member, blocked=self.owner)
        self.assertFalse(channel_enabled(self.member, "invitation", actor=self.owner))

    def test_quiet_hours_require_complete_nonzero_window(self):
        for values in ({"quiet_start": time(22)}, {"quiet_end": time(8)}, {"quiet_start": time(8), "quiet_end": time(8)}):
            with self.assertRaises(ValidationError):
                update_preferences(self.member, values)
        self.assertIsNone(NotificationPreference.objects.get_or_create(user=self.member)[0].quiet_start)

    def test_overnight_quiet_window_uses_users_iana_timezone(self):
        self.member.profile.time_zone = "Australia/Sydney"
        self.member.profile.save(update_fields=["time_zone"])
        update_preferences(self.member, {"quiet_start": time(22), "quiet_end": time(8)})
        instant = datetime(2026, 10, 1, 13, 0, tzinfo=dt_timezone.utc)  # 23:00 Sydney
        self.assertEqual(quiet_until(self.member, instant), datetime(2026, 10, 1, 22, 0, tzinfo=dt_timezone.utc))
        outside = datetime(2026, 10, 2, 2, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(quiet_until(self.member, outside), outside)

    def test_daytime_quiet_window_ends_today(self):
        self.member.profile.time_zone = "UTC"
        self.member.profile.save(update_fields=["time_zone"])
        update_preferences(self.member, {"quiet_start": time(12), "quiet_end": time(14)})
        instant = datetime(2026, 10, 1, 13, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(quiet_until(self.member, instant), datetime(2026, 10, 1, 14, 0, tzinfo=dt_timezone.utc))

    def test_fixed_window_rate_limits_are_persistent_and_secret_keyed(self):
        self.assertTrue(consume_rate("support", "raw-identity", limit=2, seconds=60))
        self.assertTrue(consume_rate("support", "raw-identity", limit=2, seconds=60))
        self.assertFalse(consume_rate("support", "raw-identity", limit=2, seconds=60))
        row = RateBucket.objects.get()
        self.assertEqual(row.count, 2)
        self.assertEqual(len(row.key), 64)
        self.assertNotIn("raw-identity", row.key)
        RateBucket.objects.update(window_started_at=timezone.now() - timedelta(minutes=2))
        self.assertTrue(consume_rate("support", "raw-identity", limit=2, seconds=60))
        row.refresh_from_db()
        self.assertEqual(row.count, 1)

    def test_queue_deduplicates_and_rejects_suppressed_unverified_or_changed_address(self):
        args = {"recipient": self.member.email.upper(), "subject": "Reminder", "body": "Detail", "key": "same", "user": self.member}
        first = enqueue_email(**args)
        second = enqueue_email(**args)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(OutboundMessage.objects.count(), 1)
        self.assertIsNone(enqueue_email(**{**args, "recipient": "different@example.com", "key": "different"}))
        SuppressedAddress.objects.create(email=self.member.email, reason="bounce")
        self.assertIsNone(enqueue_email(**{**args, "key": "suppressed"}))

    def test_queued_task_rechecks_membership_project_and_assignment(self):
        message = self.message()
        self.assertTrue(message_eligible(message))
        self.membership.removed_at = timezone.now()
        self.membership.save(update_fields=["removed_at"])
        self.assertFalse(message_eligible(message))
        self.membership.removed_at = None
        self.membership.save(update_fields=["removed_at"])
        self.project.archived_at = timezone.now()
        self.project.save(update_fields=["archived_at"])
        message.project.refresh_from_db()
        self.assertFalse(message_eligible(message))

    def test_task_deadline_change_completion_and_unassignment_cancel_old_reminders(self):
        from tasks.models import TaskAssignment
        message = self.message()
        self.task.due_at += timedelta(hours=1)
        self.task.save(update_fields=["due_at"])
        self.assertFalse(message_eligible(message))
        self.task.due_at -= timedelta(hours=1)
        self.task.save(update_fields=["due_at"])
        TaskAssignment.objects.filter(task=self.task, user=self.member).delete()
        self.assertFalse(message_eligible(message))

    def test_meeting_cancellation_decline_and_reschedule_cancel_reminders(self):
        message = OutboundMessage.objects.create(user=self.member, project=self.project,
            recipient=self.member.email, subject="Meeting", body="Detail", deduplication_key="meeting",
            category="meeting_reminder", target_type="meeting", target_id=self.meeting.pk,
            target_revision=self.meeting.starts_at.isoformat())
        self.assertTrue(message_eligible(message))
        MeetingAttendance.objects.create(meeting=self.meeting, user=self.member, response="declined")
        self.assertFalse(message_eligible(message))
        MeetingAttendance.objects.filter(meeting=self.meeting, user=self.member).delete()
        self.meeting.cancelled_at = timezone.now()
        self.meeting.save(update_fields=["cancelled_at"])
        self.assertFalse(message_eligible(message))

    def test_invitation_delivery_requires_still_pending_invitation_and_respects_block(self):
        invitation = ProjectInvitation.objects.create(project=self.project, invited_by=self.owner,
            invited_email=self.member.email, token_hash="a" * 64, expires_at=timezone.now() + timedelta(days=1))
        message = OutboundMessage.objects.create(user=self.member, project=self.project,
            recipient=self.member.email, subject="Invite", body="Detail", deduplication_key="invite",
            category="invitation", target_type="invitation", target_id=invitation.pk)
        self.assertTrue(message_eligible(message))
        UserBlock.objects.create(user=self.member, blocked=self.owner)
        self.assertFalse(message_eligible(message))
        UserBlock.objects.all().delete()
        invitation.status, invitation.responded_at = "cancelled", timezone.now()
        invitation.save(update_fields=["status", "responded_at"])
        self.assertFalse(message_eligible(message))

    def test_disabling_digest_cancels_already_queued_summary(self):
        update_preferences(self.member, {"digest": "daily"})
        message = OutboundMessage.objects.create(user=self.member, recipient=self.member.email,
            subject="Summary", body="Prepared later", deduplication_key="digest", category="service", target_type="digest")
        self.assertTrue(message_eligible(message))
        update_preferences(self.member, {"digest": "off"})
        self.assertFalse(message_eligible(message))

    def test_scheduling_is_idempotent_and_only_targets_active_assignees_and_attendees(self):
        MeetingAttendance.objects.create(meeting=self.meeting, user=self.member, response="declined")
        schedule_reminders()
        first = OutboundMessage.objects.count()
        schedule_reminders()
        self.assertEqual(OutboundMessage.objects.count(), first)
        self.assertEqual(OutboundMessage.objects.filter(user=self.member, target_type="task").count(), 1)
        self.assertFalse(OutboundMessage.objects.filter(user=self.member, target_type="meeting").exists())
        self.assertFalse(OutboundMessage.objects.filter(user=self.outsider).exists())
        self.assertEqual(UserAlert.objects.filter(user=self.member, target_type="task").count(), 1)
