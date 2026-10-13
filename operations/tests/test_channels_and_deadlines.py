from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from activity.models import ActivityEvent, Notification
from activity.services import create_notification, record_event
from campus.models import Milestone, SubmissionPlan, TaskPlan
from operations.models import OutboundMessage, UserAlert, UserBlock
from operations.services import message_eligible, schedule_academic_deadlines, schedule_reminders, update_preferences
from operations.worker import process_outbound, remove_stale_alerts
from tasks.models import Task, TaskAssignment
from .helpers import OperationsTestCase


class IndependentChannelTests(OperationsTestCase):
    def event(self):
        return record_event(project=self.project, actor=self.owner, event_type=ActivityEvent.Type.TASK_ASSIGNED,
            target_type=ActivityEvent.TargetType.TASK, target_id=self.task.pk)

    def notification(self):
        return create_notification(event=self.event(), recipient=self.member,
            notification_type=Notification.Type.TASK_ASSIGNMENT, target_url=f"/app/projects/{self.project.pk}/tasks/{self.task.pk}/")

    def test_email_only_preference_still_queues_and_sends_event_mail(self):
        update_preferences(self.member, {"in_app": False, "email": True})
        self.assertIsNone(self.notification())
        self.assertFalse(Notification.objects.filter(recipient=self.member).exists())
        message = OutboundMessage.objects.get(user=self.member)
        self.assertEqual(message.target_type, "event")
        self.assertTrue(message_eligible(message))
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["accepted"], 1)
        self.assertEqual(send.call_count, 1)

    def test_inapp_only_preference_creates_notification_without_email(self):
        update_preferences(self.member, {"in_app": True, "email": False})
        self.assertIsNotNone(self.notification())
        self.assertEqual(Notification.objects.filter(recipient=self.member).count(), 1)
        self.assertFalse(OutboundMessage.objects.filter(user=self.member).exists())

    def test_blocking_sender_after_event_enqueue_cancels_before_transport(self):
        self.notification()
        UserBlock.objects.create(user=self.member, blocked=self.owner)
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["cancelled"], 1)
        send.assert_not_called()

    def test_removing_assignment_after_event_enqueue_cancels_mail(self):
        self.notification()
        TaskAssignment.objects.filter(task=self.task, user=self.member).delete()
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["cancelled"], 1)
        send.assert_not_called()

    def test_category_optout_blocks_both_event_channels(self):
        update_preferences(self.member, {"assignments": False})
        self.assertIsNone(self.notification())
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(OutboundMessage.objects.exists())


class AcademicDeadlineTests(OperationsTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.plan = TaskPlan.objects.create(task=self.task, official_due_at=self.now + timedelta(hours=4))
        self.submission = SubmissionPlan.objects.create(project=self.project,
            internal_due_at=self.now + timedelta(hours=2), official_due_at=self.now + timedelta(hours=3))
        self.milestone = Milestone.objects.create(project=self.project, title="Final review", due_at=self.now + timedelta(hours=5))
        self.project.due_at = self.now + timedelta(hours=6)
        self.project.save(update_fields=["due_at"])

    def test_deadlines_are_deduplicated_and_task_official_recipients_are_assignees(self):
        schedule_academic_deadlines(self.now)
        count = OutboundMessage.objects.count()
        schedule_academic_deadlines(self.now)
        self.assertEqual(OutboundMessage.objects.count(), count)
        self.assertEqual(OutboundMessage.objects.filter(target_type="task_official").count(), 1)
        self.assertEqual(OutboundMessage.objects.get(target_type="task_official").user_id, self.member.pk)
        self.assertEqual(OutboundMessage.objects.filter(target_type="submission").count(), 4)
        self.assertEqual(OutboundMessage.objects.filter(target_type="milestone").count(), 2)
        self.assertEqual(OutboundMessage.objects.filter(target_type="project_deadline").count(), 2)
        self.assertFalse(OutboundMessage.objects.filter(user=self.outsider).exists())

    def test_matching_task_internal_and_official_dates_produce_one_task_reminder(self):
        self.plan.official_due_at = self.task.due_at
        self.plan.save(update_fields=["official_due_at"])
        schedule_reminders(self.now)
        self.assertFalse(OutboundMessage.objects.filter(target_type="task_official").exists())
        self.assertEqual(OutboundMessage.objects.filter(user=self.member, target_type="task").count(), 1)

    def test_completed_and_unassigned_task_invalidates_queued_official_deadline_and_alert(self):
        schedule_academic_deadlines(self.now)
        message = OutboundMessage.objects.get(target_type="task_official")
        self.assertTrue(message_eligible(message))
        Task.objects.filter(pk=self.task.pk).update(status="done", completed_at=self.now)
        self.assertFalse(message_eligible(message))
        remove_stale_alerts()
        self.assertFalse(UserAlert.objects.filter(target_type="task_official").exists())
        Task.objects.filter(pk=self.task.pk).update(status="todo", completed_at=None)
        TaskAssignment.objects.filter(task=self.task, user=self.member).delete()
        self.assertFalse(message_eligible(message))

    def test_submission_receipt_and_changed_dates_cancel_pending_deadlines(self):
        schedule_academic_deadlines(self.now)
        messages = list(OutboundMessage.objects.filter(target_type="submission"))
        self.assertTrue(all(message_eligible(message) for message in messages))
        self.submission.submitted_at = self.now
        self.submission.save(update_fields=["submitted_at"])
        self.assertTrue(all(not message_eligible(message) for message in messages))
        remove_stale_alerts()
        self.assertFalse(UserAlert.objects.filter(target_type="submission").exists())
        self.submission.submitted_at = None
        self.submission.internal_due_at += timedelta(hours=1)
        self.submission.official_due_at += timedelta(hours=1)
        self.submission.save(update_fields=["submitted_at", "internal_due_at", "official_due_at"])
        self.assertTrue(all(not message_eligible(message) for message in messages))

    def test_milestone_completion_and_project_archival_cancel_pending_mail_and_alerts(self):
        schedule_academic_deadlines(self.now)
        milestone = OutboundMessage.objects.filter(target_type="milestone").first()
        self.milestone.done = True
        self.milestone.save(update_fields=["done"])
        self.assertFalse(message_eligible(milestone))
        remove_stale_alerts()
        self.assertFalse(UserAlert.objects.filter(target_type="milestone").exists())
        self.project.archived_at = self.now
        self.project.save(update_fields=["archived_at"])
        with patch("operations.worker.send_outbound_message") as send:
            result = process_outbound()
        send.assert_not_called()
        self.assertEqual(result["cancelled"], OutboundMessage.objects.count())

    def test_changed_project_and_official_task_deadlines_cancel_old_revision(self):
        schedule_academic_deadlines(self.now)
        official = OutboundMessage.objects.get(target_type="task_official")
        project_message = OutboundMessage.objects.filter(target_type="project_deadline").first()
        self.plan.official_due_at += timedelta(hours=1)
        self.plan.save(update_fields=["official_due_at"])
        self.project.due_at += timedelta(hours=1)
        self.project.save(update_fields=["due_at"])
        project_message.project.refresh_from_db()
        self.assertFalse(message_eligible(official))
        self.assertFalse(message_eligible(project_message))

    def test_opted_out_task_reminders_and_outside_window_do_not_queue_deadlines(self):
        update_preferences(self.member, {"task_reminders": False})
        update_preferences(self.owner, {"task_reminders": False})
        schedule_academic_deadlines(self.now)
        self.assertFalse(OutboundMessage.objects.exists())
        self.assertFalse(UserAlert.objects.exists())
        update_preferences(self.owner, {"task_reminders": True})
        self.project.due_at = self.now + timedelta(days=2)
        self.project.save(update_fields=["due_at"])
        self.milestone.due_at = self.now - timedelta(days=8)
        self.milestone.save(update_fields=["due_at"])
        self.submission.internal_due_at, self.submission.official_due_at = None, None
        self.submission.save(update_fields=["internal_due_at", "official_due_at"])
        schedule_academic_deadlines(self.now)
        self.assertFalse(OutboundMessage.objects.exists())
