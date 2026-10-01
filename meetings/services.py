"""Transactional meeting write operations.

Views and API serializers should call these functions rather than duplicating
membership, audit, and notification rules.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Meeting, MeetingAttendance
from .policies import require_active_member, require_meeting_manager


class _Unset:
    pass


UNSET = _Unset()


def _require_writable_project(project) -> None:
    if project.archived_at is not None:
        raise ValidationError("Archived projects are read-only.")


def _require_writable_meeting(meeting: Meeting) -> None:
    _require_writable_project(meeting.project)
    if meeting.is_archived:
        raise ValidationError("Archived meetings are read-only.")


def _require_not_ended(meeting: Meeting, *, action: str) -> None:
    if meeting.ends_at <= timezone.now():
        raise ValidationError(f"Ended meetings cannot be {action}; archive the meeting instead.")


def _require_dates_not_before_today(**values) -> None:
    errors = {
        field_name: "Meeting dates cannot be earlier than today."
        for field_name, value in values.items()
        if value is not None
        and timezone.is_aware(value)
        and timezone.localdate(value) < timezone.localdate()
    }
    if errors:
        raise ValidationError(errors)


def _record_meeting_event(*, meeting: Meeting, actor, event_type: str, metadata=None):
    # Local import prevents activity and meeting model loading from forming a cycle.
    from activity.services import record_event

    return record_event(
        project=meeting.project,
        actor=actor,
        event_type=event_type,
        target_type="meeting",
        target_id=meeting.pk,
        metadata=metadata or {},
    )


def _notify_active_members(*, meeting: Meeting, actor, event) -> None:
    from activity.services import create_notification
    from projects.models import ProjectMembership

    memberships = (
        ProjectMembership.objects.filter(
            project=meeting.project,
            removed_at__isnull=True,
            user__is_active=True,
        )
        .exclude(user=actor)
        .select_related("user")
    )
    # The workspace currently has a project meeting-list route rather than a
    # meeting-detail route. Keep every notification target navigable.
    target_url = f"/app/projects/{meeting.project_id}/meetings/"
    for membership in memberships:
        create_notification(
            event=event,
            recipient=membership.user,
            notification_type="meeting_change",
            target_url=target_url,
        )


@transaction.atomic
def create_meeting(
    *,
    actor,
    project,
    title: str,
    starts_at,
    ends_at,
    location: str = "",
    agenda: str = "",
) -> Meeting:
    """Create a meeting for an active member and audit it atomically."""

    require_active_member(user=actor, project=project)
    _require_writable_project(project)
    meeting = Meeting(
        project=project,
        organiser=actor,
        title=title.strip(),
        starts_at=starts_at,
        ends_at=ends_at,
        location=location.strip(),
        agenda=agenda.strip(),
    )
    _require_dates_not_before_today(starts_at=starts_at, ends_at=ends_at)
    meeting.full_clean()
    meeting.save()
    event = _record_meeting_event(
        meeting=meeting,
        actor=actor,
        event_type="meeting_created",
        metadata={"title": meeting.title},
    )
    _notify_active_members(meeting=meeting, actor=actor, event=event)
    return meeting


@transaction.atomic
def update_meeting(
    *,
    meeting: Meeting,
    actor,
    title: Any = UNSET,
    starts_at: Any = UNSET,
    ends_at: Any = UNSET,
    location: Any = UNSET,
    agenda: Any = UNSET,
) -> Meeting:
    """Update allowed meeting fields after locking the current database row."""

    current = (
        Meeting.objects.select_for_update()
        .select_related("project")
        .get(pk=meeting.pk)
    )
    require_meeting_manager(user=actor, meeting=current)
    _require_writable_meeting(current)
    if current.is_cancelled:
        raise ValidationError("A cancelled meeting cannot be edited.")
    _require_not_ended(current, action="edited")

    supplied = {
        "title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "location": location,
        "agenda": agenda,
    }
    changed: list[str] = []
    for field_name, value in supplied.items():
        if value is UNSET:
            continue
        if field_name in {"title", "location", "agenda"} and isinstance(value, str):
            value = value.strip()
        if getattr(current, field_name) != value:
            setattr(current, field_name, value)
            changed.append(field_name)

    if not changed:
        return current

    changed_dates = {
        field_name: getattr(current, field_name)
        for field_name in changed
        if field_name in {"starts_at", "ends_at"}
    }
    if changed_dates:
        _require_dates_not_before_today(**changed_dates)

    current.full_clean()
    current.save(update_fields=changed + ["updated_at"])
    event = _record_meeting_event(
        meeting=current,
        actor=actor,
        event_type="meeting_updated",
        metadata={"changed_fields": sorted(changed)},
    )
    _notify_active_members(meeting=current, actor=actor, event=event)
    return current


@transaction.atomic
def cancel_meeting(*, meeting: Meeting, actor) -> Meeting:
    """Soft-cancel a meeting while retaining its attendance evidence."""

    current = (
        Meeting.objects.select_for_update()
        .select_related("project")
        .get(pk=meeting.pk)
    )
    require_meeting_manager(user=actor, meeting=current)
    _require_writable_meeting(current)
    if current.is_cancelled:
        raise ValidationError("Meeting is already cancelled.")
    _require_not_ended(current, action="cancelled")

    current.cancelled_at = timezone.now()
    current.full_clean()
    current.save(update_fields=["cancelled_at", "updated_at"])
    event = _record_meeting_event(
        meeting=current,
        actor=actor,
        event_type="meeting_cancelled",
    )
    _notify_active_members(meeting=current, actor=actor, event=event)
    return current


@transaction.atomic
def archive_meeting(*, meeting: Meeting, actor) -> Meeting:
    """Archive a cancelled or ended meeting while retaining all evidence."""

    current = (
        Meeting.objects.select_for_update()
        .select_related("project")
        .get(pk=meeting.pk)
    )
    require_meeting_manager(user=actor, meeting=current)
    _require_writable_project(current.project)
    if current.is_archived:
        return current

    archived_at = timezone.now()
    if not current.is_cancelled and current.ends_at > archived_at:
        raise ValidationError("Only a cancelled or ended meeting can be archived.")

    current.archived_at = archived_at
    current.full_clean()
    current.save(update_fields=["archived_at", "updated_at"])
    _record_meeting_event(
        meeting=current,
        actor=actor,
        event_type="meeting_archived",
    )
    return current


@transaction.atomic
def restore_meeting(*, meeting: Meeting, actor) -> Meeting:
    """Restore a previously archived record to the current meeting list."""

    current = (
        Meeting.objects.select_for_update()
        .select_related("project")
        .get(pk=meeting.pk)
    )
    require_meeting_manager(user=actor, meeting=current)
    _require_writable_project(current.project)
    if not current.is_archived:
        return current

    current.archived_at = None
    current.save(update_fields=["archived_at", "updated_at"])
    event = _record_meeting_event(
        meeting=current,
        actor=actor,
        event_type="meeting_restored",
    )
    _notify_active_members(meeting=current, actor=actor, event=event)
    return current


@transaction.atomic
def set_rsvp(
    *,
    meeting: Meeting,
    actor,
    response: str,
    availability_note: str = "",
) -> MeetingAttendance:
    """Create or update exactly one RSVP for an active project member."""

    current = (
        Meeting.objects.select_for_update()
        .select_related("project")
        .get(pk=meeting.pk)
    )
    require_active_member(user=actor, project=current.project)
    _require_writable_meeting(current)
    if current.is_cancelled:
        raise ValidationError("RSVPs are closed because this meeting is cancelled.")
    _require_not_ended(current, action="changed")
    if response not in MeetingAttendance.Response.values:
        raise ValidationError({"response": "Select a valid RSVP response."})

    attendance, _created = MeetingAttendance.objects.select_for_update().get_or_create(
        meeting=current,
        user=actor,
    )
    attendance.response = response
    attendance.availability_note = availability_note.strip()
    attendance.responded_at = timezone.now()
    attendance.full_clean()
    attendance.save(
        update_fields=["response", "availability_note", "responded_at"]
    )
    _record_meeting_event(
        meeting=current,
        actor=actor,
        event_type="meeting_rsvp",
        metadata={"response": response},
    )
    return attendance
