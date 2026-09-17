"""Authorised meeting read operations and non-blocking advisories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from django.db.models import Count, QuerySet

from .models import Meeting
from .policies import require_active_member


AUSTRALIA_SYDNEY = ZoneInfo("Australia/Sydney")


@dataclass(frozen=True, slots=True)
class HolidayAdvisory:
    meeting_date: date
    available: bool
    is_public_holiday: bool | None
    holiday_name: str | None
    source: str
    message: str


def meetings_for_project(*, project, user, include_cancelled: bool = True) -> QuerySet[Meeting]:
    require_active_member(user=user, project=project)
    meetings = Meeting.objects.filter(project=project).select_related("organiser")
    if not include_cancelled:
        meetings = meetings.filter(cancelled_at__isnull=True)
    return meetings


def meeting_for_member(*, meeting_id, user) -> Meeting:
    meeting = Meeting.objects.select_related("project", "organiser").get(pk=meeting_id)
    require_active_member(user=user, project=meeting.project)
    return meeting


def attendance_counts(*, meeting: Meeting, user) -> dict[str, int]:
    require_active_member(user=user, project=meeting.project)
    rows = meeting.attendances.values("response").annotate(total=Count("id"))
    counts = {choice: 0 for choice in meeting.attendances.model.Response.values}
    counts.update({row["response"]: row["total"] for row in rows})
    return counts


def meeting_holiday_advisory(*, meeting: Meeting) -> HolidayAdvisory:
    """Return an Australian holiday hint; external failure remains informational."""

    from integrations.nager_date import get_australian_public_holidays

    meeting_date = meeting.starts_at.astimezone(AUSTRALIA_SYDNEY).date()
    result = get_australian_public_holidays(meeting_date.year)
    if not result.available:
        return HolidayAdvisory(
            meeting_date=meeting_date,
            available=False,
            is_public_holiday=None,
            holiday_name=None,
            source=result.source,
            message="Public-holiday information is temporarily unavailable.",
        )

    holiday = next((item for item in result.holidays if item.date == meeting_date), None)
    if holiday is None:
        return HolidayAdvisory(
            meeting_date=meeting_date,
            available=True,
            is_public_holiday=False,
            holiday_name=None,
            source=result.source,
            message="No Australian public holiday falls on this date.",
        )
    return HolidayAdvisory(
        meeting_date=meeting_date,
        available=True,
        is_public_holiday=True,
        holiday_name=holiday.name,
        source=result.source,
        message=f"This meeting falls on {holiday.name}.",
    )
