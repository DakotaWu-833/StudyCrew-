"""Stable write APIs for immutable activity evidence and notifications."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ActivityEvent, Notification, SiteAuditEvent
from .policies import require_notification_owner
from .selectors import notifications_for_user


def _require_active_user(user) -> None:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise PermissionDenied("An active authenticated user is required.")


def _normalise_target_id(target_id) -> UUID | None:
    if target_id in (None, ""):
        return None
    if isinstance(target_id, UUID):
        return target_id
    try:
        return UUID(str(target_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError({"target_id": "A valid UUID is required."}) from exc


def record_event(
    *,
    project,
    actor,
    event_type: str,
    target_type: str = "",
    target_id=None,
    metadata: Mapping | None = None,
) -> ActivityEvent:
    """Insert one immutable event; callers own the surrounding transaction."""

    _require_active_user(actor)
    event = ActivityEvent(
        project=project,
        actor=actor,
        event_type=event_type,
        target_type=target_type,
        target_id=_normalise_target_id(target_id),
        metadata=dict(metadata or {}),
    )
    event.full_clean()
    event.save(force_insert=True)
    return event


def create_notification(
    *,
    event: ActivityEvent,
    recipient,
    notification_type: str,
    target_url: str,
) -> Notification | None:
    """Create at most one notification per recipient/source event.

    Self-notifications are deliberately suppressed. Invitation notifications are
    allowed before the recipient becomes a project member.
    """

    _require_active_user(recipient)
    if recipient.pk == event.actor_id:
        return None
    if not target_url.startswith("/") or target_url.startswith("//") or "://" in target_url:
        raise ValidationError({"target_url": "Notification targets must be local paths."})

    candidate = Notification(
        recipient=recipient,
        project=event.project,
        source_event=event,
        notification_type=notification_type,
        target_url=target_url,
    )
    candidate.full_clean(validate_constraints=False)
    notification, _ = Notification.objects.get_or_create(
        recipient=recipient,
        source_event=event,
        defaults={
            "project": event.project,
            "notification_type": notification_type,
            "target_url": target_url,
        },
    )
    return notification


@transaction.atomic
def mark_notification_read(*, actor, notification_id) -> Notification:
    _require_active_user(actor)
    try:
        notification = (
            notifications_for_user(actor)
            .select_for_update(of=("self",))
            .get(id=notification_id)
        )
    except Notification.DoesNotExist as exc:
        raise PermissionDenied("The notification is unavailable.") from exc
    require_notification_owner(actor, notification)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=("read_at", "updated_at"))
    return notification


def record_site_audit(
    *,
    actor,
    action: str,
    target_type: str,
    target_id,
    metadata: Mapping | None = None,
) -> SiteAuditEvent:
    """Record a mutation performed through the limited custom site panel."""

    _require_active_user(actor)
    if not getattr(actor, "is_staff", False):
        raise PermissionDenied("Site moderator permission is required.")
    event = SiteAuditEvent(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=_normalise_target_id(target_id),
        metadata=dict(metadata or {}),
    )
    event.full_clean()
    event.save(force_insert=True)
    return event


# Descriptive alias retained for callers that prefer the model's full name.
record_site_audit_event = record_site_audit
