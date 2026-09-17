"""Authorisation policies for activity feeds and notifications."""

from django.core.exceptions import PermissionDenied

from projects.policies import is_project_member

from .models import Notification


def can_view_project_activity(user, project) -> bool:
    return is_project_member(user, project)


def require_project_activity_access(user, project) -> None:
    if not can_view_project_activity(user, project):
        raise PermissionDenied("Current project membership is required.")


def can_read_notification(user, notification: Notification) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and notification.recipient_id == user.pk
    )


def require_notification_owner(user, notification: Notification) -> None:
    if not can_read_notification(user, notification):
        raise PermissionDenied("This notification belongs to another user.")
