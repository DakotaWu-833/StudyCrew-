"""Narrow site-moderation operations used by the custom control centre."""

from __future__ import annotations

from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from activity.models import SiteAuditEvent
from activity.services import record_site_audit
from accounts.policies import is_site_moderator, require_site_moderator

def _invalidate_sessions(user) -> int:
    deleted = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        if session.get_decoded().get("_auth_user_id") == str(user.pk):
            session.delete()
            deleted += 1
    return deleted


@transaction.atomic
def set_user_active(*, actor, target, active: bool):
    """Suspend or restore a non-superuser and record the limited admin action."""

    require_site_moderator(actor)
    target = type(target).objects.select_for_update().get(pk=target.pk)
    if target.pk == actor.pk:
        raise ValidationError("You cannot change your own account status.")
    if target.is_superuser:
        raise PermissionDenied("Superuser accounts cannot be managed here.")
    if active and getattr(target, "closed_at", None):
        raise ValidationError("Closed accounts cannot be restored through moderation controls.")
    if target.is_active == active:
        return target
    target.is_active = active
    target.save(update_fields=("is_active", "updated_at"))
    invalidated_sessions = 0 if active else _invalidate_sessions(target)
    record_site_audit(
        actor=actor,
        action=(
            SiteAuditEvent.Action.USER_ENABLED
            if active
            else SiteAuditEvent.Action.USER_DISABLED
        ),
        target_type="user",
        target_id=target.id,
        metadata={"sessions_invalidated": invalidated_sessions},
    )
    return target
