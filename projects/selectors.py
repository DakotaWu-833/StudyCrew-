"""Authorisation-aware read queries for the projects domain."""

from __future__ import annotations

import hashlib

from .models import Project, ProjectInvitation, ProjectMembership, normalise_email
from .policies import is_authenticated_active, require_project_member


def projects_for_user(user, *, include_archived: bool = False):
    queryset = Project.objects.for_user(user)
    return queryset if include_archived else queryset.active()


def project_for_user(*, user, project_id, include_archived: bool = False) -> Project:
    return projects_for_user(user, include_archived=include_archived).get(id=project_id)


def memberships_for_project(*, user, project: Project, include_removed: bool = False):
    require_project_member(user, project)
    queryset = ProjectMembership.objects.filter(project=project).select_related("user")
    return queryset if include_removed else queryset.active()


def pending_invitations_for_user(user):
    if not is_authenticated_active(user):
        return ProjectInvitation.objects.none()
    return ProjectInvitation.objects.usable().filter(
        invited_email=normalise_email(user.email),
        project__archived_at__isnull=True,
    ).select_related("project", "invited_by")


def invitation_for_token(raw_token: str) -> ProjectInvitation:
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return ProjectInvitation.objects.select_related("project", "invited_by").get(
        token_hash=digest
    )
