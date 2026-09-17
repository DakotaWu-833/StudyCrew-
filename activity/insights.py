"""Contribution insight queries derived from immutable evidence and current RSVP rows."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db.models import Count, Q

from activity.models import ActivityEvent
from activity.policies import require_project_activity_access
from meetings.models import MeetingAttendance
from projects.models import ProjectMembership


def validate_date_range(range_start: date, range_end: date) -> None:
    if not isinstance(range_start, date) or not isinstance(range_end, date):
        raise ValidationError("A valid start and end date are required.")
    if range_end < range_start:
        raise ValidationError({"range_end": "End date cannot precede start date."})
    if range_end - range_start > timedelta(days=366):
        raise ValidationError({"range_end": "Date range cannot exceed 366 days."})


def _utc_window(*, user, range_start: date, range_end: date) -> tuple[datetime, datetime]:
    try:
        preferred_zone = ZoneInfo(user.profile.time_zone)
    except (AttributeError, ZoneInfoNotFoundError):
        preferred_zone = ZoneInfo("UTC")
    local_start = datetime.combine(range_start, time.min, tzinfo=preferred_zone)
    local_end = datetime.combine(range_end + timedelta(days=1), time.min, tzinfo=preferred_zone)
    return (
        local_start.astimezone(datetime_timezone.utc),
        local_end.astimezone(datetime_timezone.utc),
    )


def contribution_insights(
    *,
    user,
    project,
    range_start: date,
    range_end: date,
    event_type: str = "",
) -> dict:
    """Return factual per-member totals and a drill-down event queryset.

    Zero-activity current members are included. `event_type` narrows the event
    list and total-event column; completed-task, comment, and accepted-meeting
    columns remain stable factual measures for the selected date range.
    """

    require_project_activity_access(user, project)
    validate_date_range(range_start, range_end)
    if event_type and event_type not in ActivityEvent.Type.values:
        raise ValidationError({"event_type": "Unknown activity type."})
    starts_at, ends_at = _utc_window(
        user=user,
        range_start=range_start,
        range_end=range_end,
    )
    base_events = ActivityEvent.objects.filter(
        project=project,
        occurred_at__gte=starts_at,
        occurred_at__lt=ends_at,
    )
    listed_events = base_events
    if event_type:
        listed_events = listed_events.filter(event_type=event_type)

    listed_counts = {
        row["actor_id"]: row["total"]
        for row in listed_events.values("actor_id").annotate(total=Count("id"))
    }
    completed_counts = {
        row["actor_id"]: row["total"]
        for row in base_events.filter(
            event_type=ActivityEvent.Type.TASK_STATUS_CHANGED,
            metadata__to="done",
        )
        .values("actor_id")
        .annotate(total=Count("target_id", distinct=True))
    }
    comment_counts = {
        row["actor_id"]: row["total"]
        for row in base_events.filter(event_type=ActivityEvent.Type.COMMENT_CREATED)
        .values("actor_id")
        .annotate(total=Count("id"))
    }
    meeting_counts = {
        row["user_id"]: row["total"]
        for row in MeetingAttendance.objects.filter(
            meeting__project=project,
            meeting__starts_at__gte=starts_at,
            meeting__starts_at__lt=ends_at,
            response=MeetingAttendance.Response.ACCEPTED,
        )
        .values("user_id")
        .annotate(total=Count("id"))
    }

    memberships = (
        ProjectMembership.objects.active()
        .filter(project=project)
        .select_related("user", "user__profile")
        .order_by("user__profile__display_name", "user__email")
    )
    members = []
    for membership in memberships:
        member = membership.user
        display_name = getattr(getattr(member, "profile", None), "display_name", member.email)
        members.append(
            {
                "user_id": member.id,
                "display_name": display_name,
                "role": membership.role,
                "total_events": listed_counts.get(member.id, 0),
                "completed_tasks": completed_counts.get(member.id, 0),
                "comments": comment_counts.get(member.id, 0),
                "accepted_meetings": meeting_counts.get(member.id, 0),
            }
        )

    return {
        "range_start": range_start,
        "range_end": range_end,
        "event_type": event_type,
        "members": members,
        "events": listed_events.select_related("actor", "actor__profile"),
    }
