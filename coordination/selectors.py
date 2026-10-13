"""Reads preserve project membership boundaries, including bearer calendar feeds."""

from datetime import datetime, time, timedelta, timezone as datetime_timezone
from math import ceil
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from meetings.models import Meeting
from meetings.policies import can_manage_meeting
from projects.models import Project, ProjectMembership
from projects.policies import require_project_member
from tasks.models import Task

from .models import ContributionClaim, CoordinationEvent, MeetingRecord, SchedulingPoll, WeeklyAvailability


def member_identity(user):
    return {"id": str(user.pk), "display_name": user.profile.display_name}


def project_for_user(*, project_id, user):
    from django.shortcuts import get_object_or_404
    project = get_object_or_404(Project, pk=project_id)
    require_project_member(user, project)
    return project


def calendar_events(*, user, range_start, range_end, project=None):
    if range_end < range_start or range_end - range_start > timedelta(days=366):
        raise ValidationError("Choose a calendar range of at most 366 days.")
    zone = ZoneInfo(user.profile.time_zone)
    start = datetime.combine(range_start, time.min, tzinfo=zone).astimezone(datetime_timezone.utc)
    end = datetime.combine(range_end + timedelta(days=1), time.min, tzinfo=zone).astimezone(datetime_timezone.utc)
    projects = Project.objects.filter(memberships__user=user, memberships__removed_at__isnull=True, archived_at__isnull=True)
    if project:
        require_project_member(user, project)
        projects = projects.filter(pk=project.pk)
    meetings = Meeting.objects.filter(project__in=projects, starts_at__lt=end, ends_at__gt=start, archived_at__isnull=True).select_related("project")[:1001]
    from campus.models import Milestone, SubmissionPlan
    tasks = Task.objects.filter(project__in=projects, archived_at__isnull=True).filter(Q(due_at__gte=start, due_at__lt=end) | Q(academic_plan__official_due_at__gte=start, academic_plan__official_due_at__lt=end)).exclude(status="done").select_related("project", "academic_plan")
    if not project:
        tasks = tasks.filter(assignments__user=user).distinct()
    items = []
    for meeting in meetings:
        items.append({"id": str(meeting.id), "kind": "meeting", "title": meeting.title, "project_id": str(meeting.project_id), "project_name": meeting.project.name, "starts_at": meeting.starts_at.isoformat(), "ends_at": meeting.ends_at.isoformat(), "location": meeting.location, "description": meeting.agenda, "cancelled": bool(meeting.cancelled_at), "updated_at": meeting.updated_at.isoformat(), "url": f"/app/projects/{meeting.project_id}/coordination/"})
    def deadline_item(*, row, kind, title, due_at, project, description, url):
        return {"id": str(row.pk), "kind": kind, "title": title, "project_id": str(project.pk), "project_name": project.name, "starts_at": due_at.isoformat(), "ends_at": (due_at + timedelta(minutes=15)).isoformat(), "location": "", "description": description, "cancelled": False, "updated_at": row.updated_at.isoformat(), "url": url}

    for task in tasks[:1001]:
        plan = getattr(task, "academic_plan", None)
        official = plan.official_due_at if plan else None
        url = f"/app/projects/{task.project_id}/tasks/{task.id}/"
        if task.due_at and start <= task.due_at < end:
            label = "official and internal deadline" if official == task.due_at else "internal deadline"
            items.append(deadline_item(row=task, kind="task", title=f"{task.title} · {label}", due_at=task.due_at, project=task.project, description=task.description, url=url))
        if official and official != task.due_at and start <= official < end:
            items.append(deadline_item(row=plan, kind="task_official", title=f"{task.title} · recorded official deadline", due_at=official, project=task.project, description="Official deadline entered by the team; not synced from the university.", url=url))
    submissions = list(SubmissionPlan.objects.filter(project__in=projects).filter(Q(internal_due_at__gte=start, internal_due_at__lt=end) | Q(official_due_at__gte=start, official_due_at__lt=end)).select_related("project")[:1001])
    submission_due_pairs = {(row.project_id, instant) for row in submissions for instant in (row.internal_due_at, row.official_due_at) if instant}
    for item in projects.filter(due_at__gte=start, due_at__lt=end)[:1001]:
        if (item.pk, item.due_at) not in submission_due_pairs:
            items.append(deadline_item(row=item, kind="project", title=f"{item.name} · project deadline", due_at=item.due_at, project=item, description="Project deadline", url=f"/app/projects/{item.pk}/"))
    for submission in submissions:
        url = f"/app/projects/{submission.project_id}/plan/"
        if submission.internal_due_at and start <= submission.internal_due_at < end:
            combined = submission.internal_due_at == submission.official_due_at
            items.append(deadline_item(row=submission, kind="submission_official" if combined else "submission_internal", title="Official and internal submission deadline" if combined else "Internal submission deadline", due_at=submission.internal_due_at, project=submission.project, description="Submission preparation deadline entered by the team.", url=url))
        if submission.official_due_at and submission.official_due_at != submission.internal_due_at and start <= submission.official_due_at < end:
            items.append(deadline_item(row=submission, kind="submission_official", title="Recorded official submission deadline", due_at=submission.official_due_at, project=submission.project, description="Official submission deadline entered by the team; not synced from the university.", url=url))
    for milestone in Milestone.objects.filter(project__in=projects, done=False, due_at__gte=start, due_at__lt=end).select_related("project")[:1001]:
        items.append(deadline_item(row=milestone, kind="milestone", title=f"{milestone.title} · milestone deadline", due_at=milestone.due_at, project=milestone.project, description="Team milestone deadline", url=f"/app/projects/{milestone.project_id}/plan/"))
    items.sort(key=lambda item: (item["starts_at"], item["kind"], item["id"]))
    return {"range_start": range_start.isoformat(), "range_end": range_end.isoformat(), "time_zone": user.profile.time_zone, "events": items[:1000], "truncated": len(items) > 1000}


def availability_for_project(*, user, project, week_start):
    require_project_member(user, project)
    if week_start.weekday() != 0:
        raise ValidationError({"week_start": "Choose the Monday of the week."})
    members = list(ProjectMembership.objects.filter(project=project, removed_at__isnull=True, user__is_active=True).select_related("user__profile"))
    patterns = {row.user_id: row for row in WeeklyAvailability.objects.filter(project=project, user_id__in=[row.user_id for row in members])}
    zone = ZoneInfo(user.profile.time_zone)
    cells = []
    for day in range(7):
        for minute in range(0, 1440, 30):
            at = datetime.combine(week_start + timedelta(days=day), time.min, tzinfo=zone) + timedelta(minutes=minute)
            available_ids = []
            for member in members:
                pattern = patterns.get(member.user_id)
                if not pattern:
                    continue
                local = at.astimezone(ZoneInfo(pattern.time_zone))
                local_end = (at.astimezone(datetime_timezone.utc) + timedelta(minutes=30)).astimezone(ZoneInfo(pattern.time_zone))
                local_minute, end_minute = local.hour * 60 + local.minute, local_end.hour * 60 + local_end.minute
                if local_end.date() > local.date():
                    end_minute = 1440
                if local_end.utcoffset() != local.utcoffset():
                    continue
                if any(slot["weekday"] == local.weekday() and slot["start_minute"] <= local_minute and slot["end_minute"] >= end_minute for slot in pattern.slots):
                    available_ids.append(str(member.user_id))
            cells.append({"weekday": day, "start_minute": minute, "starts_at": at.isoformat(), "available_ids": available_ids, "available_count": len(available_ids)})
    mine = patterns.get(user.pk)
    return {"week_start": week_start.isoformat(), "time_zone": user.profile.time_zone, "members": [dict(member_identity(row.user), role=row.role, shared_availability=row.user_id in patterns) for row in members], "mine": {"slots": mine.slots if mine else [], "time_zone": mine.time_zone if mine else user.profile.time_zone}, "cells": cells, "basis": "Self-reported recurring free time; confirm candidate dates in a poll. This is not a verified timetable."}


def poll_data(poll, user):
    memberships = list(ProjectMembership.objects.filter(project=poll.project).select_related("user__profile"))
    names = {str(row.user_id): row.user.profile.display_name for row in memberships}
    active = {str(row.user_id) for row in memberships if row.removed_at is None and row.user.is_active}
    membership = require_project_member(user, poll.project)
    return {"id": str(poll.id), "title": poll.title, "agenda": poll.agenda, "location": poll.location, "closed_at": poll.closed_at, "meeting_id": str(poll.meeting_id) if poll.meeting_id else None, "can_manage": not poll.project.archived_at and (poll.creator_id == user.pk or membership.role in {"owner", "facilitator"}), "can_vote": not poll.project.archived_at and str(user.pk) in {item["user_id"] for item in poll.participants}, "participants": [dict(item, display_name=names.get(item["user_id"], "Former member"), active=item["user_id"] in active) for item in poll.participants], "options": [{"id": str(option.id), "starts_at": option.starts_at, "ends_at": option.ends_at, "votes": [{"user_id": str(vote.user_id), "response": vote.response} for vote in option.votes.all()]} for option in poll.options.all()]}


def meeting_data(meeting, user):
    record = MeetingRecord.objects.filter(meeting=meeting).prefetch_related("confirmations__user__profile", "attendance__user__profile", "attendance__recorded_by__profile", "actions__task").first()
    return {"id": str(meeting.pk), "title": meeting.title, "starts_at": meeting.starts_at, "ends_at": meeting.ends_at, "lifecycle_state": meeting.lifecycle_state, "can_manage": not meeting.project.archived_at and can_manage_meeting(user=user, meeting=meeting), "can_record": not meeting.project.archived_at and not meeting.is_archived and not meeting.is_cancelled and meeting.starts_at <= timezone.now(), "participants": record.participants if record else [], "record_id": str(record.pk) if record else None, "minutes": record.minutes if record else "", "decisions": record.decisions if record else "", "version": record.version if record else 0, "confirmations": [{"user": member_identity(row.user), "version": row.version, "current": row.version == record.version, "updated_at": row.updated_at} for row in record.confirmations.all()] if record else [], "attendance": [{"user": member_identity(row.user), "attended": row.attended, "note": row.note, "recorded_by": member_identity(row.recorded_by), "updated_at": row.updated_at} for row in record.attendance.all()] if record else [], "actions": [{"task_id": str(row.task_id), "title": row.task.title, "status": row.task.status, "due_at": row.task.due_at} for row in record.actions.all()] if record else [], "history": [{"id": str(row.id), "kind": row.kind, "actor": member_identity(row.actor), "metadata": row.metadata, "created_at": row.created_at} for row in CoordinationEvent.objects.filter(project=meeting.project, object_id=record.pk).select_related("actor__profile")[:50]] if record else []}


def claims_for_project(*, user, project, range_start=None, range_end=None, page=1):
    membership = require_project_member(user, project)
    from activity.insights import contribution_insights, _utc_window
    range_end = range_end or timezone.localdate()
    range_start = range_start or range_end - timedelta(days=30)
    insights = contribution_insights(user=user, project=project, range_start=range_start, range_end=range_end, include_former=True)
    fact_counts = {str(row["user_id"]): row for row in insights["members"]}
    starts_at, ends_at = _utc_window(user=user, range_start=range_start, range_end=range_end)
    query = ContributionClaim.objects.filter(project=project).select_related("author__profile", "task").prefetch_related("contributors__user__profile", "reviews__reviewer__profile")
    count = query.count()
    pages = max(1, ceil(count / 25))
    page = min(page, pages)
    rows = query[(page - 1) * 25:page * 25]
    superseded_ids = set(ContributionClaim.objects.filter(project=project, supersedes__isnull=False).values_list("supersedes_id", flat=True))
    members = list(ProjectMembership.objects.filter(project=project).select_related("user__profile").order_by("joined_at"))
    claims = []
    for claim in rows:
        contributors = list(claim.contributors.all())
        reviews = list(claim.reviews.all())
        latest = reviews[0] if reviews else None
        superseded = claim.pk in superseded_ids
        if claim.withdrawn_at:
            status = "withdrawn"
        elif superseded:
            status = "superseded"
        elif any(row.response != "confirmed" for row in contributors):
            status = "awaiting_collaborators"
        elif latest:
            status = "team_confirmed" if latest.outcome == "confirmed" else "changes_requested"
        else:
            status = "self_reported"
        claims.append({"id": str(claim.id), "author": member_identity(claim.author), "title": claim.title, "statement": claim.statement, "artifact_url": claim.artifact_url, "task_id": str(claim.task_id) if claim.task_id else None, "task_title": claim.task.title if claim.task else "", "supersedes_id": str(claim.supersedes_id) if claim.supersedes_id else None, "created_at": claim.created_at, "status": status, "can_review": not project.archived_at and claim.author_id != user.pk and membership.role in {"owner", "facilitator"} and all(row.user_id != user.pk for row in contributors) and status not in {"withdrawn", "superseded"}, "can_respond": not project.archived_at and any(row.user_id == user.pk for row in contributors) and status not in {"withdrawn", "superseded"}, "can_withdraw": not project.archived_at and claim.author_id == user.pk and not claim.withdrawn_at, "can_revise": not project.archived_at and claim.author_id == user.pk and not superseded, "contributors": [{"user": member_identity(row.user), "response": row.response} for row in contributors], "reviews": [{"reviewer": member_identity(row.reviewer), "outcome": row.outcome, "note": row.note, "created_at": row.created_at} for row in reviews]})
    actual = {}
    from .models import AttendanceRecord
    for row in AttendanceRecord.objects.filter(record__meeting__project=project, record__meeting__cancelled_at__isnull=True, record__meeting__starts_at__gte=starts_at, record__meeting__starts_at__lt=ends_at, attended=True).values("user_id"):
        key = str(row["user_id"])
        actual[key] = actual.get(key, 0) + 1
    return {"range_start": range_start, "range_end": range_end, "claims": claims, "truncated": False, "page": page, "pages": pages, "count": count, "members": [dict(member_identity(row.user), role=row.role, active=row.removed_at is None and row.user.is_active, joined_at=row.joined_at, removed_at=row.removed_at, recorded_attendance=actual.get(str(row.user_id), 0), system_events=fact_counts[str(row.user_id)]["total_events"], tasks_marked_done=fact_counts[str(row.user_id)]["completed_tasks"], comments_created=fact_counts[str(row.user_id)]["comments"], accepted_rsvps=fact_counts[str(row.user_id)]["accepted_meetings"]) for row in members], "basis": "System actions, member statements and independent team review are separate evidence sources. RSVP is intent to attend and excludes cancelled meetings. Tasks marked done counts distinct tasks for which that member recorded a done transition during the selected range; it is not a measure of ownership, quality, effort or completed workload. Recorded attendance is entered by a meeting manager and may be corrected. No score or ranking is inferred."}


EVIDENCE_EXPORT_LIMITS = {"claims": 1000, "meetings": 500, "reviews": 10000, "events": 5000}
EVIDENCE_BASIS = (
    "System actions, self-reported contribution statements and independent team reviews "
    "are different evidence sources. A done transition does not prove authorship, quality "
    "or effort. Accepted RSVP is intention and excludes cancelled meetings. Actual "
    "attendance is a manager-recorded observation with corrections, not independent "
    "verification. No score, ranking or grade is inferred."
)


def evidence_export_data(*, user, project, range_start, range_end):
    """Complete bounded snapshot for an authorised current member.

    Claims include their whole retained history irrespective of the date filter.
    Meetings and their record history follow meeting start dates in the viewer's
    time zone. Limits raise a validation error; this function never truncates.
    Only public-to-team identity fields are selected, and bearer subscriptions
    are deliberately absent. This returns ordinary JSON values, not QuerySets.
    """
    import json
    from collections import defaultdict
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db.models import Count
    from activity.insights import contribution_insights, _utc_window
    from .models import AttendanceRecord, ClaimReview, MeetingSeries

    require_project_member(user, project)
    insights = contribution_insights(user=user, project=project, range_start=range_start, range_end=range_end, include_former=True)
    starts_at, ends_at = _utc_window(user=user, range_start=range_start, range_end=range_end)
    fact_counts = {str(row["user_id"]): row for row in insights["members"]}

    def bounded(query, limit_key):
        if query.count() > EVIDENCE_EXPORT_LIMITS[limit_key]:
            raise ValidationError({"export": f"The complete {limit_key} dataset exceeds the {EVIDENCE_EXPORT_LIMITS[limit_key]}-record export limit. Choose a smaller meeting range, or contact support for a complete larger project archive."})
        return query

    memberships = list(ProjectMembership.objects.filter(project=project).select_related("user__profile").order_by("joined_at", "id"))
    identities = {str(row.user_id): member_identity(row.user) for row in memberships}
    actual_counts = {str(row["user_id"]): row["count"] for row in AttendanceRecord.objects.filter(record__meeting__project=project, record__meeting__starts_at__gte=starts_at, record__meeting__starts_at__lt=ends_at, record__meeting__cancelled_at__isnull=True, attended=True).values("user_id").annotate(count=Count("id"))}
    member_rows = []
    for row in memberships:
        facts = fact_counts[str(row.user_id)]
        member_rows.append(dict(member_identity(row.user), role=row.role, active=row.removed_at is None and row.user.is_active, joined_at=row.joined_at, removed_at=row.removed_at, system_events=facts["total_events"], tasks_marked_done=facts["completed_tasks"], comments_created=facts["comments"], accepted_rsvps=facts["accepted_meetings"], recorded_attendance=actual_counts.get(str(row.user_id), 0)))

    claim_query = bounded(ContributionClaim.objects.filter(project=project), "claims")
    bounded(ClaimReview.objects.filter(claim__project=project), "reviews")
    claim_rows = list(claim_query.select_related("author__profile", "task").prefetch_related("contributors__user__profile", "reviews__reviewer__profile"))
    superseded_ids = {row.supersedes_id for row in claim_rows if row.supersedes_id}
    claim_history = defaultdict(list)
    claim_events = bounded(CoordinationEvent.objects.filter(project=project, object_id__in=[row.pk for row in claim_rows]).select_related("actor__profile"), "events")
    safe_metadata_keys = {"version", "minutes", "decisions", "participants", "user_id", "from", "to", "note", "task_id", "meeting_id", "occurrence_ids", "interval_days", "outcome", "response", "supersedes_id", "block_count"}

    def event_row(row):
        return {"id": str(row.pk), "object_id": str(row.object_id), "actor": member_identity(row.actor), "kind": row.kind, "metadata": {key: value for key, value in row.metadata.items() if key in safe_metadata_keys}, "created_at": row.created_at}

    for row in claim_events:
        claim_history[row.object_id].append(event_row(row))
    claims = []
    for row in claim_rows:
        collaborators, reviews = list(row.contributors.all()), list(row.reviews.all())
        latest = reviews[0] if reviews else None
        status = ("withdrawn" if row.withdrawn_at else "superseded" if row.pk in superseded_ids else "awaiting_collaborators" if any(item.response != "confirmed" for item in collaborators) else "team_confirmed" if latest and latest.outcome == "confirmed" else "changes_requested" if latest else "self_reported")
        claims.append({"id": str(row.pk), "author": member_identity(row.author), "title": row.title, "statement": row.statement, "artifact_url": row.artifact_url, "task_id": str(row.task_id) if row.task_id else None, "task_title": row.task.title if row.task else "", "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None, "created_at": row.created_at, "withdrawn_at": row.withdrawn_at, "status": status, "contributors": [{"user": member_identity(item.user), "response": item.response, "updated_at": item.updated_at} for item in collaborators], "reviews": [{"reviewer": member_identity(item.reviewer), "outcome": item.outcome, "note": item.note, "created_at": item.created_at} for item in reviews], "history": claim_history[row.pk]})

    meeting_query = bounded(Meeting.objects.filter(project=project, starts_at__gte=starts_at, starts_at__lt=ends_at), "meetings")
    meetings = list(meeting_query.order_by("starts_at", "id"))
    meeting_ids = {row.pk for row in meetings}
    records = {row.meeting_id: row for row in MeetingRecord.objects.filter(meeting_id__in=meeting_ids).prefetch_related("confirmations__user__profile", "attendance__user__profile", "attendance__recorded_by__profile", "actions__task__assignments__user__profile")}
    evidence_objects = meeting_ids | {row.pk for row in records.values()}
    poll_ids = set(SchedulingPoll.objects.filter(meeting_id__in=meeting_ids).values_list("pk", flat=True))
    evidence_objects.update(poll_ids)
    from .models import PollOption
    evidence_objects.update(PollOption.objects.filter(poll_id__in=poll_ids).values_list("pk", flat=True))
    for series in MeetingSeries.objects.filter(original__project=project):
        if series.original_id in meeting_ids or {str(value) for value in meeting_ids}.intersection(series.occurrence_ids):
            evidence_objects.add(series.pk)
    meeting_events = [event_row(row) for row in bounded(CoordinationEvent.objects.filter(project=project, object_id__in=evidence_objects).select_related("actor__profile"), "events")]
    meeting_rows = []
    for row in meetings:
        record = records.get(row.pk)
        meeting_rows.append({"id": str(row.pk), "title": row.title, "starts_at": row.starts_at, "ends_at": row.ends_at, "cancelled_at": row.cancelled_at, "archived_at": row.archived_at, "lifecycle_state": row.lifecycle_state, "record_id": str(record.pk) if record else None, "version": record.version if record else 0, "minutes": record.minutes if record else "", "decisions": record.decisions if record else "", "participants": [dict(item, user=identities.get(item["user_id"], {"id": item["user_id"], "display_name": "Former member"})) for item in record.participants] if record else [], "confirmations": [{"user": member_identity(item.user), "version": item.version, "current": item.version == record.version, "updated_at": item.updated_at} for item in record.confirmations.all()] if record else [], "attendance": [{"user": member_identity(item.user), "attended": item.attended, "note": item.note, "recorded_by": member_identity(item.recorded_by), "updated_at": item.updated_at} for item in record.attendance.all()] if record else [], "actions": [{"task_id": str(item.task_id), "title": item.task.title, "status": item.task.status, "due_at": item.task.due_at, "assignees": [member_identity(assignment.user) for assignment in item.task.assignments.all()]} for item in record.actions.all()] if record else []})
    result = {"schema_version": 1, "range_start": range_start, "range_end": range_end, "time_zone": user.profile.time_zone, "basis": EVIDENCE_BASIS, "claim_scope": "All retained contribution statements, revisions, collaborator responses and independent reviews across the project history; not filtered by the selected dates.", "meeting_scope": "Meetings whose start falls in the selected dates in the requesting member's time zone, together with their complete retained record and correction history.", "members": member_rows, "claims": claims, "meetings": meeting_rows, "coordination_events": meeting_events, "limits": EVIDENCE_EXPORT_LIMITS, "truncated": False}
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))
