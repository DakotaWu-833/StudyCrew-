"""Project authorisation policies shared by HTML and API views."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from .models import Project, ProjectMembership


PROJECT_MANAGER_ROLES = frozenset(
    {
        ProjectMembership.Role.OWNER,
        ProjectMembership.Role.FACILITATOR,
    }
)


def is_authenticated_active(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
    )


def active_membership(user, project: Project) -> ProjectMembership | None:
    if not is_authenticated_active(user):
        return None
    return (
        ProjectMembership.objects.active()
        .filter(project=project, user=user)
        .first()
    )


def is_project_member(user, project: Project) -> bool:
    return active_membership(user, project) is not None


def is_project_owner(user, project: Project) -> bool:
    membership = active_membership(user, project)
    return bool(membership and membership.role == ProjectMembership.Role.OWNER)


def is_project_manager(user, project: Project) -> bool:
    """Return whether the user may perform project-level coordination actions."""

    membership = active_membership(user, project)
    return bool(membership and membership.role in PROJECT_MANAGER_ROLES)


def require_project_member(user, project: Project) -> ProjectMembership:
    membership = active_membership(user, project)
    if membership is None:
        raise PermissionDenied("Current project membership is required.")
    return membership


def require_project_owner(user, project: Project) -> ProjectMembership:
    membership = require_project_member(user, project)
    if membership.role != ProjectMembership.Role.OWNER:
        raise PermissionDenied("Project owner permission is required.")
    return membership


def require_project_manager(user, project: Project) -> ProjectMembership:
    """Require an active owner or facilitator membership.

    This role is deliberately narrower than meeting management, which also
    permits a meeting's ordinary-member organiser to edit their own meeting.
    """

    membership = require_project_member(user, project)
    if membership.role not in PROJECT_MANAGER_ROLES:
        raise PermissionDenied("Project owner or facilitator permission is required.")
    return membership
