"""Contribution insight queries derived from immutable evidence and current RSVP rows."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncDate

from activity.models import ActivityEvent
from activity.policies import require_project_activity_access
from meetings.models import MeetingAttendance
from projects.models import ProjectMembership
from tasks.models import Task, TaskAssignment

INSIGHT_TIMELINE_PAGE_SIZE = 5


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


def _work_charts(*, project, user, range_start: date, range_end: date, starts_at, ends_at) -> dict:
    """Build bounded, uncapped work charts from task records, not the event preview."""

    try:
        local_zone = ZoneInfo(user.profile.time_zone)
    except (AttributeError, ZoneInfoNotFoundError):
        local_zone = ZoneInfo("UTC")

    project_tasks = Task.objects.filter(project=project)
    current_tasks = project_tasks.filter(archived_at__isnull=True)
    status_counts = dict(
        current_tasks.values("status").annotate(total=Count("id")).values_list("status", "total")
    )
    priority_counts = dict(
        current_tasks.values("priority").annotate(total=Count("id")).values_list("priority", "total")
    )
    open_tasks = current_tasks.exclude(status=Task.Status.DONE)

    memberships = list(
        ProjectMembership.objects.active()
        .filter(project=project)
        .select_related("user", "user__profile")
        .order_by("user__profile__display_name", "user__email")
    )
    assignment_rows = (
        TaskAssignment.objects.filter(
            task__project=project,
            task__archived_at__isnull=True,
        ).exclude(task__status=Task.Status.DONE)
        .values("user_id")
        .annotate(total=Count("task_id"))
    )
    assignment_counts = {row["user_id"]: row["total"] for row in assignment_rows}
    assigned_task_count = (
        TaskAssignment.objects.filter(
            task__project=project,
            task__archived_at__isnull=True,
        ).exclude(task__status=Task.Status.DONE)
        .values("task_id")
        .distinct()
        .count()
    )
    open_task_count = open_tasks.count()

    created_counts = {
        row["day"]: row["total"]
        for row in project_tasks.filter(created_at__gte=starts_at, created_at__lt=ends_at)
        .annotate(day=TruncDate("created_at", tzinfo=local_zone))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    }
    cycle_time = ExpressionWrapper(
        F("completed_at") - F("created_at"), output_field=DurationField()
    )
    completion_rows = (
        project_tasks.filter(
            status=Task.Status.DONE,
            completed_at__gte=starts_at,
            completed_at__lt=ends_at,
        )
        .annotate(day=TruncDate("completed_at", tzinfo=local_zone), cycle_time=cycle_time)
        .values("day")
        .annotate(total=Count("id"), average_cycle_time=Avg("cycle_time"))
        .order_by("day")
    )
    completions = {}
    for row in completion_rows:
        average = row["average_cycle_time"]
        completions[row["day"]] = {
            "count": row["total"],
            "average_hours": round(average.total_seconds() / 3600, 1) if average is not None else None,
        }

    status_labels = dict(Task.Status.choices)
    priority_labels = dict(Task.Priority.choices)
    daily_dates = (range_end - range_start).days + 1

    return {
        "task_status": [
            {"key": value, "label": status_labels[value], "count": status_counts.get(value, 0)}
            for value in Task.Status.values
        ],
        "task_priority": [
            {"key": value, "label": priority_labels[value], "count": priority_counts.get(value, 0)}
            for value in Task.Priority.values
        ],
        "task_assignees": [
            {
                "key": str(membership.user_id),
                "label": getattr(
                    getattr(membership.user, "profile", None),
                    "display_name",
                    membership.user.email,
                ),
                "count": assignment_counts.get(membership.user_id, 0),
            }
            for membership in memberships
        ]
        + [{"key": "unassigned", "label": "Unassigned", "count": open_task_count - assigned_task_count}],
        "tasks_created": [
            {
                "date": (range_start + timedelta(days=offset)).isoformat(),
                "count": created_counts.get(range_start + timedelta(days=offset), 0),
            }
            for offset in range(daily_dates)
        ],
        "completion_cycle": [
            {
                "date": (range_start + timedelta(days=offset)).isoformat(),
                "count": completions.get(range_start + timedelta(days=offset), {}).get("count", 0),
                "average_hours": completions.get(range_start + timedelta(days=offset), {}).get("average_hours"),
            }
            for offset in range(daily_dates)
        ],
    }


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
    list and total-event column. This service returns the complete event
    queryset so evidence exports are never affected by presentation pagination.
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
        "events": listed_events.select_related("actor", "actor__profile").order_by(
            "-occurred_at", "-id"
        ),
        "charts": _work_charts(
            project=project,
            user=user,
            range_start=range_start,
            range_end=range_end,
            starts_at=starts_at,
            ends_at=ends_at,
        ),
    }


def activity_timeline_page(
    *,
    user,
    project,
    range_start: date,
    range_end: date,
    event_type: str = "",
    search: str = "",
    member_id=None,
    page: int = 1,
) -> dict:
    """Return one bounded timeline page without recomputing contribution charts."""

    require_project_activity_access(user, project)
    validate_date_range(range_start, range_end)
    if event_type and event_type not in ActivityEvent.Type.values:
        raise ValidationError({"event_type": "Unknown activity type."})

    starts_at, ends_at = _utc_window(user=user, range_start=range_start, range_end=range_end)
    events = ActivityEvent.objects.filter(
        project=project,
        occurred_at__gte=starts_at,
        occurred_at__lt=ends_at,
    )
    if event_type:
        events = events.filter(event_type=event_type)
    if member_id:
        events = events.filter(actor_id=member_id)
    search = search.strip()
    if search:
        events = events.filter(
            Q(actor__profile__display_name__icontains=search)
            | Q(event_type__icontains=search)
            | Q(target_type__icontains=search)
        )

    events_total = events.count()
    events_pages = max(1, ceil(events_total / INSIGHT_TIMELINE_PAGE_SIZE))
    events_page = min(page, events_pages)
    event_offset = (events_page - 1) * INSIGHT_TIMELINE_PAGE_SIZE
    page_events = list(
        events.select_related("actor", "actor__profile")
        .order_by("-occurred_at", "-id")[
            event_offset : event_offset + INSIGHT_TIMELINE_PAGE_SIZE
        ]
    )
    return {
        "events": page_events,
        "events_total": events_total,
        "events_page": events_page,
        "events_pages": events_pages,
        "events_page_size": INSIGHT_TIMELINE_PAGE_SIZE,
    }
