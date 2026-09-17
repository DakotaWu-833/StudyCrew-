"""Task authorisation rules, independent from HTTP and serializers."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from projects.models import ProjectMembership
from projects.policies import active_membership as project_active_membership


def active_membership(*, project, user) -> ProjectMembership:
    membership = project_active_membership(user, project)
    if membership is None:
        raise PermissionDenied("You are not a current member of this project.")
    return membership


def can_moderate(*, project, user) -> bool:
    membership = active_membership(project=project, user=user)
    return membership.role in {
        ProjectMembership.Role.OWNER,
        ProjectMembership.Role.FACILITATOR,
    }


def require_task_transition_permission(*, task, user) -> None:
    membership = active_membership(project=task.project, user=user)
    if membership.role == ProjectMembership.Role.OWNER:
        return
    if not task.assignments.filter(user=user).exists():
        raise PermissionDenied("Only an assignee or project owner can change task status.")


def require_comment_change_permission(*, comment, user) -> bool:
    """Return whether the permitted change is a moderation action."""
    if comment.author_id == user.id:
        active_membership(project=comment.task.project, user=user)
        return False
    if can_moderate(project=comment.task.project, user=user):
        return True
    raise PermissionDenied("You cannot change this comment.")
