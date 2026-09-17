"""Authorisation-aware reads for evidence and notification inboxes."""

from django.db.models import Exists, OuterRef, Q

from projects.models import ProjectMembership

from .models import ActivityEvent, Notification
from .policies import require_project_activity_access


def events_for_project(*, user, project):
    require_project_activity_access(user, project)
    return ActivityEvent.objects.filter(project=project).select_related("actor")


def notifications_for_user(user, *, unread_only: bool = False):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return Notification.objects.none()
    active_membership = ProjectMembership.objects.filter(
        project_id=OuterRef("project_id"),
        user=user,
        removed_at__isnull=True,
    )
    queryset = (
        Notification.objects.filter(recipient=user)
        .annotate(_has_active_project_membership=Exists(active_membership))
        .filter(
            Q(notification_type=Notification.Type.INVITATION)
            | Q(_has_active_project_membership=True)
        )
        .select_related("project", "source_event")
    )
    return queryset.filter(read_at__isnull=True) if unread_only else queryset
