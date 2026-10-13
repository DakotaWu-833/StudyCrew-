"""Meeting workflows that coordinate domain evidence with email delivery."""

from __future__ import annotations

from datetime import UTC, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from activity.models import ActivityEvent
from activity.services import record_event
from integrations.reminder_email import ReminderDeliveryResult, deliver_reminder_emails
from meetings.models import Meeting
from projects.models import ProjectMembership
from projects.policies import require_project_manager


REMINDER_COOLDOWN = timedelta(seconds=60)


def _display_name(user) -> str:
    profile = getattr(user, "profile", None)
    return getattr(profile, "display_name", "") or user.email


def _format_instant(value) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


@transaction.atomic
def send_meeting_reminder(
    *,
    meeting: Meeting,
    actor,
    site_url: str,
) -> ReminderDeliveryResult:
    """Email current project members about one future scheduled meeting."""

    current = (
        Meeting.objects.select_for_update()
        .select_related("project")
        .get(pk=meeting.pk)
    )
    require_project_manager(actor, current.project)
    if current.project.archived_at is not None:
        raise ValidationError("Archived projects are read-only.")
    if current.archived_at is not None:
        raise ValidationError("Archived meetings cannot send reminders.")
    if current.cancelled_at is not None:
        raise ValidationError("Cancelled meetings cannot send reminders.")
    if current.ends_at <= timezone.now():
        raise ValidationError("Ended meetings cannot send reminders.")

    recently_sent = ActivityEvent.objects.filter(
        project=current.project,
        event_type=ActivityEvent.Type.MEETING_REMINDER_SENT,
        target_type=ActivityEvent.TargetType.MEETING,
        target_id=current.id,
        occurred_at__gt=timezone.now() - REMINDER_COOLDOWN,
    ).exists()
    if recently_sent:
        raise ValidationError("A reminder for this meeting was sent less than 60 seconds ago.")

    recipient_emails = list(
        ProjectMembership.objects.active()
        .filter(
            project=current.project,
            user__is_active=True,
            user__email_verified_at__isnull=False,
        )
        .exclude(user=actor)
        .order_by("user__email")
        .values_list("user__email", flat=True)
    )
    if not recipient_emails:
        raise ValidationError("This meeting has no eligible project members to notify.")

    meeting_url = f"{site_url.rstrip('/')}/app/projects/{current.project_id}/meetings/"
    message = (
        f"{_display_name(actor)} sent a StudyCrew meeting reminder.\n\n"
        f"Project: {current.project.name}\n"
        f"Meeting: {current.title}\n"
        f"Starts: {_format_instant(current.starts_at)}\n"
        f"Ends: {_format_instant(current.ends_at)}\n"
        f"Location: {current.location or 'To be confirmed'}\n\n"
        "Open the meeting schedule in StudyCrew:\n"
        f"{meeting_url}\n"
    )
    delivery = deliver_reminder_emails(
        subject="[StudyCrew] Meeting reminder",
        message=message,
        recipient_emails=recipient_emails,
        project=current.project,
        target_type="meeting",
        target_id=current.id,
        target_revision=current.starts_at.isoformat(),
        category="meeting_reminder",
    )
    record_event(
        project=current.project,
        actor=actor,
        event_type=ActivityEvent.Type.MEETING_REMINDER_SENT,
        target_type=ActivityEvent.TargetType.MEETING,
        target_id=current.id,
        metadata={"recipient_count": delivery.recipient_count, **({"delivery_status": "queued"} if delivery.delivery_status == "queued" else {})},
    )
    return delivery
