"""Task workflows that coordinate domain evidence with email delivery."""

from __future__ import annotations

from datetime import UTC, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from activity.models import ActivityEvent
from activity.services import record_event
from integrations.reminder_email import ReminderDeliveryResult, deliver_reminder_emails
from projects.models import ProjectMembership
from projects.policies import require_project_manager
from tasks.models import Task


REMINDER_COOLDOWN = timedelta(seconds=60)


def _display_name(user) -> str:
    profile = getattr(user, "profile", None)
    return getattr(profile, "display_name", "") or user.email


def _format_instant(value) -> str:
    if value is None:
        return "No due date"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


@transaction.atomic
def send_task_reminder(
    *,
    task: Task,
    actor,
    site_url: str,
) -> ReminderDeliveryResult:
    """Email the task's current eligible assignees and append one audit event."""

    current = (
        Task.objects.select_for_update()
        .select_related("project")
        .get(pk=task.pk)
    )
    require_project_manager(actor, current.project)
    if current.project.archived_at is not None:
        raise ValidationError("Archived projects are read-only.")
    if current.archived_at is not None:
        raise ValidationError("Archived tasks cannot send reminders.")

    recently_sent = ActivityEvent.objects.filter(
        project=current.project,
        event_type=ActivityEvent.Type.TASK_REMINDER_SENT,
        target_type=ActivityEvent.TargetType.TASK,
        target_id=current.id,
        occurred_at__gt=timezone.now() - REMINDER_COOLDOWN,
    ).exists()
    if recently_sent:
        raise ValidationError("A reminder for this task was sent less than 60 seconds ago.")

    recipient_emails = list(
        ProjectMembership.objects.active()
        .filter(
            project=current.project,
            user__is_active=True,
            user__email_verified_at__isnull=False,
            user__task_assignments__task=current,
        )
        .exclude(user=actor)
        .order_by("user__email")
        .values_list("user__email", flat=True)
        .distinct()
    )
    if not recipient_emails:
        raise ValidationError("This task has no eligible assignees to notify.")

    task_url = (
        f"{site_url.rstrip('/')}/app/projects/{current.project_id}/"
        f"tasks/{current.id}/"
    )
    message = (
        f"{_display_name(actor)} sent a StudyCrew task reminder.\n\n"
        f"Project: {current.project.name}\n"
        f"Task: {current.title}\n"
        f"Status: {current.get_status_display()}\n"
        f"Priority: {current.get_priority_display()}\n"
        f"Due: {_format_instant(current.due_at)}\n\n"
        "Open the task in StudyCrew:\n"
        f"{task_url}\n"
    )
    delivery = deliver_reminder_emails(
        subject="[StudyCrew] Task reminder",
        message=message,
        recipient_emails=recipient_emails,
        project=current.project,
        target_type="task",
        target_id=current.id,
        target_revision=current.due_at.isoformat() if current.due_at else "",
        category="task_due",
    )
    record_event(
        project=current.project,
        actor=actor,
        event_type=ActivityEvent.Type.TASK_REMINDER_SENT,
        target_type=ActivityEvent.TargetType.TASK,
        target_id=current.id,
        metadata={"recipient_count": delivery.recipient_count, **({"delivery_status": "queued"} if delivery.delivery_status == "queued" else {})},
    )
    return delivery
