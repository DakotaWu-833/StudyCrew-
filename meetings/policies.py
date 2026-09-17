"""Explicit meeting authorisation rules shared by services and selectors."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from .models import Meeting


MANAGER_ROLES = frozenset({"owner", "facilitator"})


def active_membership_for(*, user, project):
    """Return the active membership or ``None`` without trusting caller input."""

    # Reuse the project boundary so disabled users and removed memberships have
    # identical behaviour in every domain.
    from projects.policies import active_membership

    return active_membership(user, project)


def require_active_member(*, user, project):
    membership = active_membership_for(user=user, project=project)
    if membership is None:
        raise PermissionDenied("You must be an active project member.")
    return membership


def can_manage_meeting(*, user, meeting: Meeting) -> bool:
    membership = active_membership_for(user=user, project=meeting.project)
    if membership is None:
        return False
    role = str(getattr(membership, "role", "")).lower()
    return meeting.organiser_id == user.pk or role in MANAGER_ROLES


def require_meeting_manager(*, user, meeting: Meeting):
    membership = require_active_member(user=user, project=meeting.project)
    role = str(getattr(membership, "role", "")).lower()
    if meeting.organiser_id != user.pk and role not in MANAGER_ROLES:
        raise PermissionDenied(
            "Only the organiser, a facilitator, or the project owner may manage this meeting."
        )
    return membership
