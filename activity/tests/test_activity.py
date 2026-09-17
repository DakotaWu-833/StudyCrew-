from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from activity.models import (
    ActivityEvent,
    ExportJob,
    ImmutableRecordError,
    Notification,
    SiteAuditEvent,
)
from activity.selectors import events_for_project, notifications_for_user
from activity.services import (
    create_notification,
    mark_notification_read,
    record_event,
    record_site_audit_event,
)
from projects.models import ProjectMembership
from projects.services import create_project


class ActivityDomainTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="owner@example.com",
            password="StrongPass!123",
            display_name="Owner",
        )
        self.member = user_model.objects.create_user(
            email="member@example.com",
            password="StrongPass!123",
            display_name="Member",
        )
        self.outsider = user_model.objects.create_user(
            email="outsider@example.com",
            password="StrongPass!123",
            display_name="Outsider",
        )
        self.moderator = user_model.objects.create_user(
            email="moderator@example.com",
            password="StrongPass!123",
            display_name="Moderator",
            is_staff=True,
        )
        self.project = create_project(actor=self.owner, name="Activity project")
        ProjectMembership.objects.create(project=self.project, user=self.member)

    def new_event(self, *, actor=None, project=None):
        return record_event(
            project=project or self.project,
            actor=actor or self.owner,
            event_type=ActivityEvent.Type.TASK_CREATED,
            target_type=ActivityEvent.TargetType.TASK,
            target_id=self.project.id,
            metadata={"title_length": 12},
        )

    def test_record_event_persists_typed_uuid_target_and_metadata(self):
        event = self.new_event()
        self.assertEqual(event.event_type, ActivityEvent.Type.TASK_CREATED)
        self.assertEqual(event.target_type, ActivityEvent.TargetType.TASK)
        self.assertEqual(event.target_id, self.project.id)
        self.assertEqual(event.metadata, {"title_length": 12})

    def test_event_rejects_incomplete_target_pair(self):
        with self.assertRaises(ValidationError):
            record_event(
                project=self.project,
                actor=self.owner,
                event_type=ActivityEvent.Type.TASK_CREATED,
                target_type=ActivityEvent.TargetType.TASK,
            )

    def test_event_rejects_unknown_type_and_sensitive_metadata(self):
        with self.assertRaises(ValidationError):
            record_event(
                project=self.project,
                actor=self.owner,
                event_type="invented_event",
            )
        with self.assertRaises(ValidationError):
            record_event(
                project=self.project,
                actor=self.owner,
                event_type=ActivityEvent.Type.TASK_UPDATED,
                metadata={"nested": {"token": "must-not-be-stored"}},
            )

    def test_event_rejects_inactive_actor_and_invalid_target_uuid(self):
        self.member.is_active = False
        self.member.save(update_fields=("is_active", "updated_at"))
        with self.assertRaises(PermissionDenied):
            record_event(
                project=self.project,
                actor=self.member,
                event_type=ActivityEvent.Type.TASK_CREATED,
            )
        with self.assertRaises(ValidationError):
            record_event(
                project=self.project,
                actor=self.owner,
                event_type=ActivityEvent.Type.TASK_CREATED,
                target_type=ActivityEvent.TargetType.TASK,
                target_id="not-a-uuid",
            )

    def test_event_is_immutable_via_instance_and_queryset(self):
        event = self.new_event()
        event.event_type = ActivityEvent.Type.TASK_UPDATED
        with self.assertRaises(ImmutableRecordError):
            event.save()
        with self.assertRaises(ImmutableRecordError):
            event.delete()
        with self.assertRaises(ImmutableRecordError):
            ActivityEvent.objects.filter(pk=event.pk).update(metadata={})
        with self.assertRaises(ImmutableRecordError):
            ActivityEvent.objects.filter(pk=event.pk).delete()

    def test_activity_selector_enforces_membership_and_project_scope(self):
        event = self.new_event(actor=self.member)
        visible = events_for_project(user=self.member, project=self.project)
        self.assertIn(event, visible)
        with self.assertRaises(PermissionDenied):
            events_for_project(user=self.outsider, project=self.project)

    def test_notification_deduplicates_and_suppresses_self_notification(self):
        event = self.new_event()
        first = create_notification(
            event=event,
            recipient=self.member,
            notification_type=Notification.Type.TASK_ASSIGNMENT,
            target_url=f"/projects/{self.project.id}/tasks/{self.project.id}/",
        )
        second = create_notification(
            event=event,
            recipient=self.member,
            notification_type=Notification.Type.TASK_ASSIGNMENT,
            target_url="/ignored-on-deduplication/",
        )
        self.assertEqual(first.id, second.id)
        self.assertEqual(Notification.objects.filter(recipient=self.member).count(), 1)
        self.assertIsNone(
            create_notification(
                event=event,
                recipient=self.owner,
                notification_type=Notification.Type.TASK_ASSIGNMENT,
                target_url="/self/",
            )
        )

    def test_notification_uses_event_project_and_rejects_external_target(self):
        event = self.new_event()
        with self.assertRaises(ValidationError):
            create_notification(
                event=event,
                recipient=self.member,
                notification_type=Notification.Type.TASK_ASSIGNMENT,
                target_url="https://evil.example/",
            )

    def test_only_recipient_can_mark_notification_read(self):
        event = self.new_event()
        notification = create_notification(
            event=event,
            recipient=self.member,
            notification_type=Notification.Type.TASK_ASSIGNMENT,
            target_url="/tasks/",
        )
        with self.assertRaises(PermissionDenied):
            mark_notification_read(actor=self.outsider, notification_id=notification.id)
        notification.refresh_from_db()
        self.assertIsNone(notification.read_at)

        marked = mark_notification_read(actor=self.member, notification_id=notification.id)
        first_read_at = marked.read_at
        marked_again = mark_notification_read(actor=self.member, notification_id=notification.id)
        self.assertEqual(marked_again.read_at, first_read_at)

    def test_notification_selector_never_leaks_another_inbox(self):
        event = self.new_event()
        notification = create_notification(
            event=event,
            recipient=self.member,
            notification_type=Notification.Type.COMMENT_MENTION,
            target_url="/comments/",
        )
        self.assertEqual(list(notifications_for_user(self.member)), [notification])
        self.assertEqual(list(notifications_for_user(self.outsider)), [])
        self.assertEqual(list(notifications_for_user(AnonymousUser())), [])
        self.assertEqual(list(notifications_for_user(self.member, unread_only=True)), [notification])

    def test_notification_selector_hides_project_links_after_membership_removal(self):
        event = self.new_event()
        notification = create_notification(
            event=event,
            recipient=self.member,
            notification_type=Notification.Type.TASK_ASSIGNMENT,
            target_url="/app/tasks/example/",
        )
        self.assertEqual(list(notifications_for_user(self.member)), [notification])

        membership = ProjectMembership.objects.get(project=self.project, user=self.member)
        membership.removed_at = timezone.now()
        membership.save(update_fields=("removed_at",))

        self.assertEqual(list(notifications_for_user(self.member)), [])
        with self.assertRaises(PermissionDenied):
            mark_notification_read(actor=self.member, notification_id=notification.id)
        notification.refresh_from_db()
        self.assertIsNone(notification.read_at)

    def test_archived_project_notification_remains_available_as_read_only_history(self):
        event = self.new_event()
        notification = create_notification(
            event=event,
            recipient=self.member,
            notification_type=Notification.Type.MEETING_CHANGE,
            target_url="/app/meetings/example/",
        )
        self.project.archived_at = timezone.now()
        self.project.save(update_fields=("archived_at", "updated_at"))

        self.assertEqual(list(notifications_for_user(self.member)), [notification])
        marked = mark_notification_read(actor=self.member, notification_id=notification.id)
        self.assertIsNotNone(marked.read_at)

    def test_notification_selector_keeps_safe_invitation_inbox_for_non_member(self):
        event = record_event(
            project=self.project,
            actor=self.owner,
            event_type=ActivityEvent.Type.INVITATION_CREATED,
            target_type=ActivityEvent.TargetType.INVITATION,
            target_id=self.project.id,
        )
        notification = create_notification(
            event=event,
            recipient=self.outsider,
            notification_type=Notification.Type.INVITATION,
            target_url="/app/invitations/",
        )

        self.assertEqual(list(notifications_for_user(self.outsider)), [notification])
        marked = mark_notification_read(actor=self.outsider, notification_id=notification.id)
        self.assertIsNotNone(marked.read_at)

    def test_site_audit_requires_staff_and_is_immutable(self):
        with self.assertRaises(PermissionDenied):
            record_site_audit_event(
                actor=self.owner,
                action=SiteAuditEvent.Action.USER_DISABLED,
                target_type="user",
                target_id=self.member.id,
            )
        event = record_site_audit_event(
            actor=self.moderator,
            action=SiteAuditEvent.Action.USER_DISABLED,
            target_type="user",
            target_id=self.member.id,
            metadata={"reason_code": "policy"},
        )
        with self.assertRaises(ImmutableRecordError):
            event.delete()
        with self.assertRaises(ImmutableRecordError):
            SiteAuditEvent.objects.filter(pk=event.pk).update(metadata={})

        report_event = record_site_audit_event(
            actor=self.moderator,
            action=SiteAuditEvent.Action.CONTENT_REPORT_RESOLVED,
            target_type="content_report",
            target_id=self.project.id,
        )
        self.assertEqual(report_event.action, "content_report_resolved")

    def test_mark_read_hides_missing_notification_and_notification_type_is_validated(self):
        with self.assertRaises(PermissionDenied):
            mark_notification_read(actor=self.member, notification_id=self.project.id)
        event = self.new_event()
        with self.assertRaises(ValidationError):
            create_notification(
                event=event,
                recipient=self.member,
                notification_type="invented_notification",
                target_url="/safe/",
            )

    def test_export_job_validates_range_and_ready_state(self):
        too_long = ExportJob(
            project=self.project,
            requested_by=self.member,
            format=ExportJob.Format.CSV,
            range_start=date(2025, 1, 1),
            range_end=date(2026, 1, 3),
        )
        with self.assertRaises(ValidationError):
            too_long.full_clean()

        incomplete_ready = ExportJob(
            project=self.project,
            requested_by=self.member,
            format=ExportJob.Format.PDF,
            range_start=date.today() - timedelta(days=7),
            range_end=date.today(),
            status=ExportJob.Status.READY,
            completed_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            incomplete_ready.full_clean()
