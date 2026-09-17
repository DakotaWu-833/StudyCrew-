"""Project authorisation policies shared by HTML and API views."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from .models import Project, ProjectMembership


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
