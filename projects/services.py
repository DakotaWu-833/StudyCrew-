"""Explicit transaction services for project and membership workflows."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from activity.models import ActivityEvent, Notification
from activity.services import create_notification, record_event

from .exceptions import (
    DuplicateInvitation,
    ExistingMember,
    InvalidRole,
    InvitationExpired,
    InvitationNotFound,
    InvitationUnavailable,
    MembershipNotFound,
    SoleOwnerViolation,
)
from .models import Project, ProjectInvitation, ProjectMembership, normalise_email


INVITATION_LIFETIME = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class InvitationDispatch:
    """The saved invitation and its one-time token for the delivery boundary."""

    invitation: ProjectInvitation
    token: str


def _require_active_user(user) -> None:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise PermissionDenied("An active authenticated user is required.")


def _token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _locked_project(project: Project) -> Project:
    return Project.objects.select_for_update().get(pk=project.pk)


def _locked_active_membership(*, project: Project, user) -> ProjectMembership:
    try:
        return ProjectMembership.objects.select_for_update().get(
            project=project,
            user=user,
            removed_at__isnull=True,
        )
    except ProjectMembership.DoesNotExist as exc:
        raise PermissionDenied("Current project membership is required.") from exc


def _locked_owner(*, project: Project, user) -> ProjectMembership:
    membership = _locked_active_membership(project=project, user=user)
    if membership.role != ProjectMembership.Role.OWNER:
        raise PermissionDenied("Project owner permission is required.")
    return membership


def _require_writable_project(
    project: Project,
    *,
    error_type: type[Exception] = ValidationError,
) -> None:
    if project.archived_at is not None:
        raise error_type("The project has been archived and is read-only.")


def _save_invitation_status(
    invitation: ProjectInvitation,
    *,
    status: str,
    responded_at=None,
) -> None:
    invitation.status = status
    invitation.responded_at = responded_at or timezone.now()
    invitation.save(update_fields=("status", "responded_at", "updated_at"))


@transaction.atomic
def create_project(
    *,
    actor,
    name: str,
    description: str = "",
    due_at=None,
) -> Project:
    """Create a project, its sole owner membership, and its first event."""

    _require_active_user(actor)
    project = Project(
        name=name.strip(),
        description=description.strip(),
        due_at=due_at,
        created_by=actor,
    )
    project.full_clean()
    project.save(force_insert=True)

    membership = ProjectMembership(
        project=project,
        user=actor,
        role=ProjectMembership.Role.OWNER,
    )
    membership.full_clean()
    membership.save(force_insert=True)

    record_event(
        project=project,
        actor=actor,
        event_type=ActivityEvent.Type.PROJECT_CREATED,
        target_type=ActivityEvent.TargetType.PROJECT,
        target_id=project.id,
    )
    return project


@transaction.atomic
def update_project(*, project: Project, actor, data: Mapping) -> Project:
    """Update owner-controlled project fields and record one factual event."""

    _require_active_user(actor)
    project = _locked_project(project)
    _locked_owner(project=project, user=actor)
    _require_writable_project(project)

    allowed_fields = ("name", "description", "due_at")
    changed_fields: list[str] = []
    for field_name in allowed_fields:
        if field_name not in data:
            continue
        value = data[field_name]
        if field_name in ("name", "description") and isinstance(value, str):
            value = value.strip()
        if getattr(project, field_name) != value:
            setattr(project, field_name, value)
            changed_fields.append(field_name)

    if not changed_fields:
        return project
    project.full_clean()
    project.save(update_fields=(*changed_fields, "updated_at"))
    record_event(
        project=project,
        actor=actor,
        event_type=ActivityEvent.Type.PROJECT_UPDATED,
        target_type=ActivityEvent.TargetType.PROJECT,
        target_id=project.id,
        metadata={"changed_fields": sorted(changed_fields)},
    )
    return project


@transaction.atomic
def archive_project(*, project: Project, actor, at=None) -> Project:
    """Soft-archive a project without deleting its collaboration evidence."""

    _require_active_user(actor)
    at = at or timezone.now()
    project = _locked_project(project)
    _locked_owner(project=project, user=actor)
    if project.archived_at is not None:
        return project
    project.archived_at = at
    project.save(update_fields=("archived_at", "updated_at"))
    ProjectInvitation.objects.pending().filter(project=project).update(
        status=ProjectInvitation.Status.CANCELLED,
        responded_at=at,
        updated_at=at,
    )
    record_event(
        project=project,
        actor=actor,
        event_type=ActivityEvent.Type.PROJECT_ARCHIVED,
        target_type=ActivityEvent.TargetType.PROJECT,
        target_id=project.id,
    )
    return project


@transaction.atomic
def invite_member(
    *,
    actor,
    project: Project,
    invited_email: str,
    at=None,
) -> InvitationDispatch:
    """Create a seven-day, single-use invitation and notify an existing user."""

    _require_active_user(actor)
    at = at or timezone.now()
    project = _locked_project(project)
    _locked_owner(project=project, user=actor)
    _require_writable_project(project)
    email = normalise_email(invited_email)
    if not email:
        raise ValidationError({"invited_email": "An email address is required."})

    user_model = get_user_model()
    invitee = user_model.objects.filter(email__iexact=email).first()
    if invitee and ProjectMembership.objects.active().filter(
        project=project,
        user=invitee,
    ).exists():
        raise ExistingMember("This user is already a project member.")

    stale = list(
        ProjectInvitation.objects.select_for_update()
        .pending()
        .filter(project=project, invited_email__iexact=email)
    )
    for invitation in stale:
        if invitation.expires_at <= at:
            _save_invitation_status(
                invitation,
                status=ProjectInvitation.Status.EXPIRED,
                responded_at=at,
            )
            record_event(
                project=project,
                actor=actor,
                event_type=ActivityEvent.Type.INVITATION_EXPIRED,
                target_type=ActivityEvent.TargetType.INVITATION,
                target_id=invitation.id,
            )
        else:
            raise DuplicateInvitation("A pending invitation already exists for this email.")

    raw_token = secrets.token_urlsafe(32)
    invitation = ProjectInvitation(
        project=project,
        invited_email=email,
        invited_by=actor,
        token_hash=_token_digest(raw_token),
        expires_at=at + INVITATION_LIFETIME,
    )
    invitation.full_clean()
    invitation.save(force_insert=True)

    source_event = record_event(
        project=project,
        actor=actor,
        event_type=ActivityEvent.Type.INVITATION_CREATED,
        target_type=ActivityEvent.TargetType.INVITATION,
        target_id=invitation.id,
    )
    if invitee and invitee.is_active:
        create_notification(
            event=source_event,
            recipient=invitee,
            notification_type=Notification.Type.INVITATION,
            target_url=f"/app/invitations/{invitation.id}/",
        )
    return InvitationDispatch(invitation=invitation, token=raw_token)


def _lock_invitation(raw_token: str) -> ProjectInvitation:
    if not raw_token:
        raise InvitationNotFound("The invitation is unavailable.")
    try:
        return (
            ProjectInvitation.objects.select_for_update()
            .select_related("project", "invited_by")
            .get(token_hash=_token_digest(raw_token))
        )
    except ProjectInvitation.DoesNotExist as exc:
        raise InvitationNotFound("The invitation is unavailable.") from exc


def _lock_invitation_by_id(invitation_id) -> ProjectInvitation:
    """Lock an in-app invitation identified by its unguessable UUID."""

    try:
        return (
            ProjectInvitation.objects.select_for_update()
            .select_related("project", "invited_by")
            .get(pk=invitation_id)
        )
    except (ProjectInvitation.DoesNotExist, ValueError, TypeError) as exc:
        raise InvitationNotFound("The invitation is unavailable.") from exc


def _require_matching_invitee(*, actor, invitation: ProjectInvitation) -> None:
    if normalise_email(actor.email) != invitation.invited_email:
        raise PermissionDenied("This invitation was issued to another email address.")


def _expire_invitation(
    *,
    invitation: ProjectInvitation,
    actor,
    at,
) -> None:
    _save_invitation_status(
        invitation,
        status=ProjectInvitation.Status.EXPIRED,
        responded_at=at,
    )
    record_event(
        project=invitation.project,
        actor=actor,
        event_type=ActivityEvent.Type.INVITATION_EXPIRED,
        target_type=ActivityEvent.TargetType.INVITATION,
        target_id=invitation.id,
    )


def _accept_locked_invitation(*, actor, invitation: ProjectInvitation, at):
    _require_matching_invitee(actor=actor, invitation=invitation)
    _require_writable_project(invitation.project, error_type=InvitationUnavailable)
    if invitation.status != ProjectInvitation.Status.PENDING:
        raise InvitationUnavailable("The invitation has already been resolved.")
    if invitation.expires_at <= at:
        _expire_invitation(invitation=invitation, actor=actor, at=at)
        return None, True

    membership = (
        ProjectMembership.objects.select_for_update()
        .filter(project=invitation.project, user=actor)
        .first()
    )
    if membership and membership.removed_at is None:
        raise ExistingMember("This user is already a project member.")
    if membership is None:
        membership = ProjectMembership(
            project=invitation.project,
            user=actor,
            role=ProjectMembership.Role.MEMBER,
            joined_at=at,
        )
        membership.full_clean()
        membership.save(force_insert=True)
    else:
        membership.role = ProjectMembership.Role.MEMBER
        membership.joined_at = at
        membership.removed_at = None
        membership.full_clean()
        membership.save(update_fields=("role", "joined_at", "removed_at"))

    _save_invitation_status(
        invitation,
        status=ProjectInvitation.Status.ACCEPTED,
        responded_at=at,
    )
    record_event(
        project=invitation.project,
        actor=actor,
        event_type=ActivityEvent.Type.MEMBER_JOINED,
        target_type=ActivityEvent.TargetType.MEMBERSHIP,
        target_id=membership.id,
    )
    return membership, False


def _accept_with_loader(*, actor, loader, at=None) -> ProjectMembership:
    _require_active_user(actor)
    at = at or timezone.now()
    with transaction.atomic():
        membership, expired = _accept_locked_invitation(
            actor=actor,
            invitation=loader(),
            at=at,
        )
    if expired:
        raise InvitationExpired("The invitation has expired.")
    return membership


def accept_invitation(*, actor, raw_token: str, at=None) -> ProjectMembership:
    """Accept a matching bearer token and activate exactly one membership."""

    return _accept_with_loader(actor=actor, loader=lambda: _lock_invitation(raw_token), at=at)


def accept_invitation_by_id(*, actor, invitation_id, at=None) -> ProjectMembership:
    """Accept a matching invitation from the authenticated in-app inbox."""

    return _accept_with_loader(
        actor=actor,
        loader=lambda: _lock_invitation_by_id(invitation_id),
        at=at,
    )


def _decline_with_loader(*, actor, loader, at=None) -> ProjectInvitation:
    _require_active_user(actor)
    at = at or timezone.now()
    expired = False

    with transaction.atomic():
        invitation = loader()
        _require_matching_invitee(actor=actor, invitation=invitation)
        _require_writable_project(invitation.project, error_type=InvitationUnavailable)
        if invitation.status != ProjectInvitation.Status.PENDING:
            raise InvitationUnavailable("The invitation has already been resolved.")
        if invitation.expires_at <= at:
            _expire_invitation(invitation=invitation, actor=actor, at=at)
            expired = True
        else:
            _save_invitation_status(
                invitation,
                status=ProjectInvitation.Status.DECLINED,
                responded_at=at,
            )
            record_event(
                project=invitation.project,
                actor=actor,
                event_type=ActivityEvent.Type.INVITATION_DECLINED,
                target_type=ActivityEvent.TargetType.INVITATION,
                target_id=invitation.id,
            )

    if expired:
        raise InvitationExpired("The invitation has expired.")
    return invitation


def decline_invitation(*, actor, raw_token: str, at=None) -> ProjectInvitation:
    """Decline a matching bearer token without creating a membership."""

    return _decline_with_loader(
        actor=actor,
        loader=lambda: _lock_invitation(raw_token),
        at=at,
    )


def decline_invitation_by_id(*, actor, invitation_id, at=None) -> ProjectInvitation:
    """Decline a matching invitation from the authenticated in-app inbox."""

    return _decline_with_loader(
        actor=actor,
        loader=lambda: _lock_invitation_by_id(invitation_id),
        at=at,
    )


@transaction.atomic
def cancel_invitation(*, actor, invitation: ProjectInvitation, at=None) -> ProjectInvitation:
    _require_active_user(actor)
    at = at or timezone.now()
    invitation = (
        ProjectInvitation.objects.select_for_update()
        .select_related("project")
        .get(pk=invitation.pk)
    )
    _locked_owner(project=invitation.project, user=actor)
    _require_writable_project(invitation.project, error_type=InvitationUnavailable)
    if invitation.status != ProjectInvitation.Status.PENDING:
        raise InvitationUnavailable("Only a pending invitation can be cancelled.")
    _save_invitation_status(
        invitation,
        status=ProjectInvitation.Status.CANCELLED,
        responded_at=at,
    )
    record_event(
        project=invitation.project,
        actor=actor,
        event_type=ActivityEvent.Type.INVITATION_CANCELLED,
        target_type=ActivityEvent.TargetType.INVITATION,
        target_id=invitation.id,
    )
    return invitation


@transaction.atomic
def change_member_role(
    *,
    actor,
    project: Project,
    member,
    role: str,
) -> ProjectMembership:
    """Change an active non-owner between member and facilitator."""

    _require_active_user(actor)
    if role not in (ProjectMembership.Role.MEMBER, ProjectMembership.Role.FACILITATOR):
        raise InvalidRole("Use transfer_ownership() to assign the owner role.")
    project = _locked_project(project)
    _locked_owner(project=project, user=actor)
    _require_writable_project(project)
    try:
        membership = ProjectMembership.objects.select_for_update().get(
            project=project,
            user=member,
            removed_at__isnull=True,
        )
    except ProjectMembership.DoesNotExist as exc:
        raise MembershipNotFound("The active project membership was not found.") from exc
    if membership.role == ProjectMembership.Role.OWNER:
        raise SoleOwnerViolation("Transfer ownership before changing the owner's role.")
    if membership.role == role:
        return membership

    previous_role = membership.role
    membership.role = role
    membership.full_clean()
    membership.save(update_fields=("role",))
    record_event(
        project=project,
        actor=actor,
        event_type=ActivityEvent.Type.MEMBER_ROLE_CHANGED,
        target_type=ActivityEvent.TargetType.MEMBERSHIP,
        target_id=membership.id,
        metadata={"previous_role": previous_role, "new_role": role},
    )
    return membership


@transaction.atomic
def remove_member(*, actor, project: Project, member, at=None) -> ProjectMembership:
    """Soft-remove an active non-owner and immediately revoke project access."""

    _require_active_user(actor)
    at = at or timezone.now()
    project = _locked_project(project)
    _locked_owner(project=project, user=actor)
    _require_writable_project(project)
    try:
        membership = ProjectMembership.objects.select_for_update().get(
            project=project,
            user=member,
            removed_at__isnull=True,
        )
    except ProjectMembership.DoesNotExist as exc:
        raise MembershipNotFound("The active project membership was not found.") from exc
    if membership.role == ProjectMembership.Role.OWNER:
        raise SoleOwnerViolation("The sole owner cannot be removed.")

    membership.removed_at = at
    membership.save(update_fields=("removed_at",))
    # Assignments describe current responsibility, so revoke them with access.
    # Historical assignment changes remain available in the activity ledger.
    assignments = member.task_assignments.filter(
        task__project=project,
    )
    removed_assignment_count = assignments.count()
    assignments.delete()
    record_event(
        project=project,
        actor=actor,
        event_type=ActivityEvent.Type.MEMBER_REMOVED,
        target_type=ActivityEvent.TargetType.MEMBERSHIP,
        target_id=membership.id,
        metadata={"removed_assignment_count": removed_assignment_count},
    )
    return membership


@transaction.atomic
def transfer_ownership(
    *,
    actor,
    project: Project,
    new_owner,
    previous_owner_role: str = ProjectMembership.Role.FACILITATOR,
) -> tuple[ProjectMembership, ProjectMembership]:
    """Atomically demote the owner and promote one active member."""

    _require_active_user(actor)
    if previous_owner_role not in (
        ProjectMembership.Role.MEMBER,
        ProjectMembership.Role.FACILITATOR,
    ):
        raise InvalidRole("The previous owner must become a member or facilitator.")
    project = _locked_project(project)
    current_owner = _locked_owner(project=project, user=actor)
    _require_writable_project(project)
    if new_owner.pk == actor.pk:
        raise SoleOwnerViolation("The selected user is already the project owner.")
    try:
        incoming = ProjectMembership.objects.select_for_update().get(
            project=project,
            user=new_owner,
            removed_at__isnull=True,
        )
    except ProjectMembership.DoesNotExist as exc:
        raise MembershipNotFound("The new owner must be an active project member.") from exc

    current_owner.role = previous_owner_role
    current_owner.save(update_fields=("role",))
    incoming.role = ProjectMembership.Role.OWNER
    incoming.full_clean()
    incoming.save(update_fields=("role",))
    record_event(
        project=project,
        actor=actor,
        event_type=ActivityEvent.Type.OWNERSHIP_TRANSFERRED,
        target_type=ActivityEvent.TargetType.MEMBERSHIP,
        target_id=incoming.id,
        metadata={
            "previous_owner_id": str(current_owner.user_id),
            "new_owner_id": str(incoming.user_id),
            "previous_owner_role": previous_owner_role,
        },
    )
    return current_owner, incoming
