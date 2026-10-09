"""Local scheduling and time tracking with project access and user-first locks."""
from calendar import monthrange
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from campus.models import ChecklistItem, TaskPlan
from projects.models import Project, ProjectMembership
from projects.policies import require_project_member
from tasks.models import Task
from tasks.services import create_task, replace_assignees
from .models import RecurringOccurrence, RecurringTask, TimeEntry

MAX_SECONDS = 86400


def _note(note):
    value = note.strip()
    if len(value) > 500:
        raise ValidationError({"note": "Notes must contain at most 500 characters."})
    return value


def _actor(actor):
    fresh = get_user_model().objects.select_for_update().get(pk=actor.pk)
    if not fresh.is_active or fresh.closed_at:
        raise PermissionDenied("This account cannot change project data.")
    return fresh


def _task(*, actor, project_id, task_id, write=False):
    if not get_user_model().objects.filter(pk=actor.pk, is_active=True, closed_at__isnull=True).exists():
        raise PermissionDenied("This account cannot access project data.")
    project = get_object_or_404(Project.objects.select_for_update() if write else Project.objects.all(), pk=project_id)
    require_project_member(actor, project)
    tasks = Task.objects.select_for_update() if write else Task.objects.all()
    task = get_object_or_404(tasks.select_related("project"), pk=task_id, project=project)
    if write and (project.archived_at or task.archived_at):
        raise ValidationError("Archived projects and tasks are read-only.")
    return task


def local_instant(wall, zone):
    """Keep local schedule time: first fold for repeats, shift gaps forward."""
    first = wall.replace(tzinfo=zone, fold=0)
    roundtrip = first.astimezone(datetime_timezone.utc).astimezone(zone)
    if roundtrip.replace(tzinfo=None) != wall:
        first = roundtrip
    return first.astimezone(datetime_timezone.utc)


def occurrence_due(schedule, index):
    anchor = datetime.fromisoformat(schedule.start_local)
    if schedule.frequency == "weekly":
        wall = anchor + timedelta(weeks=schedule.interval * index)
    else:
        absolute_month = anchor.year * 12 + anchor.month - 1 + schedule.interval * index
        year, month = divmod(absolute_month, 12)
        wall = anchor.replace(year=year, month=month + 1, day=min(anchor.day, monthrange(year, month + 1)[1]))
    if wall.date() > schedule.until_date or index >= schedule.occurrence_limit:
        return None
    return local_instant(wall, ZoneInfo(schedule.timezone_name))


def schedule_row(schedule):
    return {"id": str(schedule.id), "author_id": str(schedule.author_id), "frequency": schedule.frequency,
        "interval": schedule.interval, "timezone_name": schedule.timezone_name, "start_local": schedule.start_local,
        "until_date": schedule.until_date, "occurrence_limit": schedule.occurrence_limit, "lead_days": schedule.lead_days,
        "generated_count": schedule.next_index, "next_run_at": schedule.next_run_at,
        "next_due_at": occurrence_due(schedule, schedule.next_index) if not schedule.stopped_at else None,
        "stopped_at": schedule.stopped_at, "stop_reason": schedule.stop_reason,
        "created_at": schedule.created_at, "updated_at": schedule.updated_at}


def entry_row(entry):
    return {"id": str(entry.id), "started_at": entry.started_at, "ended_at": entry.ended_at,
        "seconds": entry.seconds, "source": entry.source, "note": entry.note, "cancelled_at": entry.cancelled_at,
        "corrected_at": entry.corrected_at, "capped": entry.capped, "updated_at": entry.updated_at}


@transaction.atomic
def create_schedule(*, actor, project_id, task_id, frequency, interval, timezone_name, start_local, until_date, occurrence_limit, lead_days=7):
    actor = _actor(actor)
    task = _task(actor=actor, project_id=project_id, task_id=task_id, write=True)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", start_local):
        raise ValidationError({"start_local": "Choose a local date and time without a UTC offset."})
    try:
        zone = ZoneInfo(timezone_name)
        start = datetime.fromisoformat(start_local)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValidationError("Choose an IANA timezone and valid first local deadline.") from None
    if start.tzinfo is not None or start.microsecond:
        raise ValidationError({"start_local": "Use a local date and time without an offset or fractional seconds."})
    if frequency not in ("weekly", "monthly") or not 1 <= interval <= 12 or not 1 <= occurrence_limit <= 520 or not 0 <= lead_days <= 30:
        raise ValidationError("Choose a valid recurrence frequency, interval, count and lead time.")
    first_due = local_instant(start, zone)
    today = timezone.localdate(timezone=zone)
    maximum = today.replace(year=today.year + 10, day=min(today.day, monthrange(today.year + 10, today.month)[1]))
    if first_due < timezone.now() - timedelta(minutes=1) or not start.date() <= until_date <= maximum:
        raise ValidationError("Start with a future deadline and end within ten years.")
    if RecurringTask.objects.filter(source_task=task, stopped_at__isnull=True).exists():
        raise ValidationError("This task already has an active schedule. Stop it before creating another.")
    if RecurringTask.objects.filter(project=task.project, stopped_at__isnull=True).count() >= 100 or RecurringTask.objects.filter(author=actor, stopped_at__isnull=True).count() >= 20:
        raise ValidationError("Active schedule limit reached (100 per project, 20 per person).")
    plan = getattr(task, "academic_plan", None)
    snapshot = {"title": task.title, "description": task.description, "priority": task.priority,
        "assignees": [str(value) for value in task.assignments.values_list("user_id", flat=True)],
        "acceptance": plan.acceptance if plan else "", "tags": plan.tags if plan else [],
        "estimate_hours": str(plan.estimate_hours) if plan and plan.estimate_hours is not None else None,
        "checklist": list(task.academic_checklist.values_list("text", flat=True))}
    schedule = RecurringTask.objects.create(project=task.project, source_task=task, author=actor,
        frequency=frequency, interval=interval, timezone_name=zone.key, start_local=start.isoformat(timespec="seconds"),
        until_date=until_date, occurrence_limit=occurrence_limit, lead_days=lead_days, snapshot=snapshot,
        next_run_at=first_due - timedelta(days=lead_days))
    return schedule_row(schedule)


@transaction.atomic
def stop_schedule(*, actor, project_id, task_id, schedule_id):
    actor = _actor(actor)
    task = _task(actor=actor, project_id=project_id, task_id=task_id)
    Project.objects.select_for_update().get(pk=task.project_id)
    schedule = get_object_or_404(RecurringTask.objects.select_for_update(), pk=schedule_id, source_task=task)
    member = require_project_member(actor, task.project)
    if schedule.author_id != actor.id and member.role not in ("owner", "facilitator"):
        raise PermissionDenied("Only the schedule author or a project manager can stop it.")
    if not schedule.stopped_at:
        schedule.stopped_at = timezone.now()
        schedule.stop_reason = "Stopped by member"
        schedule.next_run_at = None
        schedule.save(update_fields=("stopped_at", "stop_reason", "next_run_at", "updated_at"))
    return schedule_row(schedule)


@transaction.atomic
def _generate_one(schedule_id, now):
    identity = RecurringTask.objects.filter(pk=schedule_id).values("author_id", "project_id").first()
    if not identity:
        return 0
    actor = get_user_model().objects.select_for_update().get(pk=identity["author_id"])
    project = Project.objects.select_for_update().get(pk=identity["project_id"])
    schedule = RecurringTask.objects.select_for_update().get(pk=schedule_id)
    source = Task.objects.select_for_update().get(pk=schedule.source_task_id)
    if schedule.stopped_at or not schedule.next_run_at or schedule.next_run_at > now:
        return 0
    eligible = actor.is_active and not actor.closed_at and ProjectMembership.objects.filter(project=project, user=actor, removed_at__isnull=True).exists()
    if not eligible or project.archived_at or source.archived_at:
        schedule.stopped_at = now
        schedule.stop_reason = "Author unavailable or source archived"
        schedule.next_run_at = None
        schedule.save(update_fields=("stopped_at", "stop_reason", "next_run_at", "updated_at"))
        return 0
    due = occurrence_due(schedule, schedule.next_index)
    if due is None:
        return 0
    snapshot = schedule.snapshot
    task = create_task(project=project, actor=actor, data={"title": snapshot["title"], "description": snapshot["description"], "priority": snapshot["priority"], "due_at": due})
    eligible_assignees = list(ProjectMembership.objects.filter(project=project, removed_at__isnull=True,
        user__is_active=True, user__closed_at__isnull=True, user_id__in=snapshot["assignees"]).values_list("user_id", flat=True))
    replace_assignees(task=task, actor=actor, assignee_ids=eligible_assignees)
    TaskPlan.objects.create(task=task, acceptance=snapshot["acceptance"], tags=snapshot["tags"], estimate_hours=snapshot["estimate_hours"])
    ChecklistItem.objects.bulk_create([ChecklistItem(task=task, text=text, checked=False) for text in snapshot["checklist"]])
    RecurringOccurrence.objects.create(schedule=schedule, index=schedule.next_index, task=task, due_at=due)
    schedule.next_index += 1
    following = occurrence_due(schedule, schedule.next_index)
    schedule.next_run_at = following - timedelta(days=schedule.lead_days) if following else None
    if following is None:
        schedule.stopped_at = now
        schedule.stop_reason = "Schedule completed"
    schedule.save(update_fields=("next_index", "next_run_at", "stopped_at", "stop_reason", "updated_at"))
    return 1


def generate_due_recurring_tasks(*, now=None, limit=100):
    now = now or timezone.now()
    if not 1 <= limit <= 1000:
        raise ValidationError("Generation batch limit must be between 1 and 1000.")
    generated = 0
    # Each iteration takes one user/project/schedule lock and commits one task.
    # Multiple workers recheck next_run_at under the lock; occurrence uniqueness
    # provides an additional database-level idempotency boundary.
    for _ in range(limit):
        candidate = RecurringTask.objects.filter(stopped_at__isnull=True, next_run_at__lte=now).order_by("next_run_at", "id").values_list("id", flat=True).first()
        if not candidate:
            break
        generated += _generate_one(candidate, now)
    return generated


def _check_overlap(*, user, start, end, exclude=None):
    query = TimeEntry.objects.filter(user=user, cancelled_at__isnull=True, started_at__lt=end).filter(Q(ended_at__gt=start) | Q(ended_at__isnull=True))
    if exclude:
        query = query.exclude(pk=exclude)
    if query.exists():
        raise ValidationError("This time overlaps another personal time record. Correct that record first.")


@transaction.atomic
def start_timer(*, actor, project_id, task_id):
    actor = _actor(actor)
    task = _task(actor=actor, project_id=project_id, task_id=task_id, write=True)
    if TimeEntry.objects.filter(user=actor, ended_at__isnull=True, cancelled_at__isnull=True).exists():
        raise ValidationError("You already have a running timer. Stop or discard it first.")
    now = timezone.now()
    _check_overlap(user=actor, start=now, end=now + timedelta(seconds=1))
    entry = TimeEntry.objects.create(task=task, user=actor, started_at=now, source="timer")
    return entry_row(entry)


@transaction.atomic
def stop_timer(*, actor, project_id, task_id, note=""):
    actor = _actor(actor)
    task = _task(actor=actor, project_id=project_id, task_id=task_id, write=True)
    entry = get_object_or_404(TimeEntry.objects.select_for_update(), task=task, user=actor, ended_at__isnull=True, cancelled_at__isnull=True)
    now = timezone.now()
    elapsed = max(0, int((now - entry.started_at).total_seconds()))
    entry.seconds = min(MAX_SECONDS, elapsed)
    entry.capped = elapsed > MAX_SECONDS
    entry.ended_at = entry.started_at + timedelta(seconds=entry.seconds)
    entry.note = _note(note)
    entry.save(update_fields=("seconds", "capped", "ended_at", "note", "updated_at"))
    return entry_row(entry)


@transaction.atomic
def discard_timer(*, actor):
    actor = _actor(actor)
    entry = TimeEntry.objects.select_for_update().filter(user=actor, ended_at__isnull=True, cancelled_at__isnull=True).first()
    if entry:
        entry.cancelled_at = timezone.now()
        entry.note = ""
        entry.save(update_fields=("cancelled_at", "note", "updated_at"))
    return {"discarded": bool(entry)}


def _manual_bounds(started_at, minutes):
    if not timezone.is_aware(started_at) or not 1 <= minutes <= 1440:
        raise ValidationError("Manual time must be 1 to 1440 minutes with an explicit timezone.")
    end = started_at + timedelta(minutes=minutes)
    if end > timezone.now() + timedelta(minutes=1) or started_at < timezone.now() - timedelta(days=3660):
        raise ValidationError("Record past work within the last ten years.")
    return end


@transaction.atomic
def add_manual(*, actor, project_id, task_id, started_at, minutes, note=""):
    actor = _actor(actor)
    task = _task(actor=actor, project_id=project_id, task_id=task_id, write=True)
    end = _manual_bounds(started_at, minutes)
    _check_overlap(user=actor, start=started_at, end=end)
    if TimeEntry.objects.filter(user=actor, created_at__gte=timezone.now() - timedelta(days=1)).count() >= 200:
        raise ValidationError("Daily time record limit reached.")
    return entry_row(TimeEntry.objects.create(task=task, user=actor, started_at=started_at, ended_at=end,
        seconds=minutes * 60, source="manual", note=_note(note)))


@transaction.atomic
def correct_entry(*, actor, project_id, task_id, entry_id, expected_updated_at, started_at, minutes, note=""):
    actor = _actor(actor)
    task = _task(actor=actor, project_id=project_id, task_id=task_id, write=True)
    entry = get_object_or_404(TimeEntry.objects.select_for_update(), pk=entry_id, task=task, user=actor, cancelled_at__isnull=True)
    if not entry.ended_at:
        raise ValidationError("Stop the timer before correcting it.")
    if expected_updated_at != entry.updated_at:
        raise ValidationError("This time record changed. Reload before correcting it.")
    end = _manual_bounds(started_at, minutes)
    _check_overlap(user=actor, start=started_at, end=end, exclude=entry.id)
    entry.started_at, entry.ended_at, entry.seconds = started_at, end, minutes * 60
    entry.note, entry.corrected_at, entry.capped = _note(note), timezone.now(), False
    entry.save(update_fields=("started_at", "ended_at", "seconds", "note", "corrected_at", "capped", "updated_at"))
    return entry_row(entry)


@transaction.atomic
def delete_entry(*, actor, project_id, task_id, entry_id, expected_updated_at):
    actor = _actor(actor)
    task = _task(actor=actor, project_id=project_id, task_id=task_id, write=True)
    entry = get_object_or_404(TimeEntry.objects.select_for_update(), pk=entry_id, task=task, user=actor)
    if entry.updated_at != expected_updated_at:
        raise ValidationError("This time record changed. Reload before discarding it.")
    entry.cancelled_at, entry.note = timezone.now(), ""
    entry.save(update_fields=("cancelled_at", "note", "updated_at"))
    return {"discarded": True}


def active_timer(*, actor):
    if not get_user_model().objects.filter(pk=actor.pk, is_active=True, closed_at__isnull=True).exists():
        return None
    entry = TimeEntry.objects.select_related("task__project").filter(user=actor, ended_at__isnull=True, cancelled_at__isnull=True).first()
    if not entry:
        return None
    task = entry.task
    visible = actor.is_active and not actor.closed_at and ProjectMembership.objects.filter(user=actor, project=task.project, removed_at__isnull=True).exists()
    return {"id": str(entry.id), "started_at": entry.started_at, "accessible": bool(visible),
        "task_id": str(task.id) if visible else None, "project_id": str(task.project_id) if visible else None,
        "title": task.title if visible else None, "read_only": bool(task.archived_at or task.project.archived_at) if visible else True}


def task_overview(*, actor, project_id, task_id, page=1):
    task = _task(actor=actor, project_id=project_id, task_id=task_id)
    try:
        page = int(page)
    except (TypeError, ValueError):
        raise ValidationError("Choose a valid time-record page.") from None
    query = TimeEntry.objects.filter(task=task, user=actor, cancelled_at__isnull=True, ended_at__isnull=False)
    total = query.count()
    pages = max(1, (total + 19) // 20)
    if not 1 <= page <= pages:
        raise ValidationError("Choose a valid time-record page.")
    manager = require_project_member(actor, task.project).role in ("owner", "facilitator")
    return {"schedules": [{**schedule_row(item), "can_stop": manager or item.author_id == actor.id} for item in RecurringTask.objects.filter(source_task=task)[:20]],
        "entries": [entry_row(item) for item in query[(page - 1) * 20:page * 20]],
        "page": page, "pages": pages, "total": total, "active_timer": active_timer(actor=actor),
        "actual_seconds": TimeEntry.objects.filter(task=task, cancelled_at__isnull=True).aggregate(value=Sum("seconds"))["value"] or 0,
        "my_seconds": TimeEntry.objects.filter(task=task, user=actor, cancelled_at__isnull=True).aggregate(value=Sum("seconds"))["value"] or 0,
        "timezone_name": getattr(getattr(actor, "profile", None), "time_zone", "Australia/Sydney"),
        "read_only": bool(task.project.archived_at or task.archived_at),
        "can_stop_schedules": manager}


def workload(*, actor, project_id):
    if not get_user_model().objects.filter(pk=actor.pk, is_active=True, closed_at__isnull=True).exists():
        raise PermissionDenied("This account cannot access project data.")
    project = get_object_or_404(Project, pk=project_id)
    require_project_member(actor, project)
    task_query = Task.objects.filter(project=project, archived_at__isnull=True)
    if task_query.count() > 10000:
        raise ValidationError("Workload view supports up to 10,000 active tasks per project.")
    tasks = list(task_query.select_related("academic_plan").prefetch_related("assignments"))
    actual = {str(item["user_id"]): item["total"] for item in TimeEntry.objects.filter(task__project=project,
        cancelled_at__isnull=True, ended_at__isnull=False).values("user_id").annotate(total=Sum("seconds"))}
    members = list(ProjectMembership.objects.filter(project=project).select_related("user__profile"))
    rows = {str(member.user_id): {"user_id": str(member.user_id), "name": member.user.profile.display_name,
        "current_member": member.removed_at is None and member.user.is_active and member.user.closed_at is None, "open_tasks": 0, "assigned_estimate_hours": Decimal("0"),
        "actual_seconds": 0, "due": {"overdue": 0, "next_7_days": 0, "later": 0, "no_deadline": 0}} for member in members}
    now = timezone.now()
    unassigned = {"open_tasks": 0, "estimate_hours": Decimal("0"), "due": {"overdue": 0, "next_7_days": 0, "later": 0, "no_deadline": 0}}
    for task in tasks:
        assignees = [str(item.user_id) for item in task.assignments.all() if str(item.user_id) in rows and rows[str(item.user_id)]["current_member"]]
        if task.status == "done":
            continue
        plan = getattr(task, "academic_plan", None)
        estimate = plan.estimate_hours if plan and plan.estimate_hours is not None else Decimal("0")
        bucket = "no_deadline" if not task.due_at else "overdue" if task.due_at < now else "next_7_days" if task.due_at <= now + timedelta(days=7) else "later"
        if not assignees:
            unassigned["open_tasks"] += 1
            unassigned["estimate_hours"] += estimate
            unassigned["due"][bucket] += 1
        for user_id in assignees:
            rows[user_id]["open_tasks"] += 1
            rows[user_id]["assigned_estimate_hours"] += estimate / len(assignees)
            rows[user_id]["due"][bucket] += 1
    for user_id, seconds in actual.items():
        if user_id in rows:
            rows[user_id]["actual_seconds"] += seconds
    return {"project": {"id": str(project.id), "name": project.name}, "as_of": now,
        "members": [{**row, "assigned_estimate_hours": str(row["assigned_estimate_hours"].quantize(Decimal("0.01")))} for row in rows.values()],
        "unassigned": {**unassigned, "estimate_hours": str(unassigned["estimate_hours"])},
        "actual_seconds": sum(row["actual_seconds"] for row in rows.values()),
        "method": "Open-task estimates are divided equally among current assignees. Actual time is self-recorded completed sessions, including archived tasks. Running timers are excluded. Member order follows joining order; these are not scores."}


def personal_data(user):
    accessible = set(Project.objects.for_user(user).values_list("id", flat=True))
    entries = [{"id": str(item.id), "started_at": item.started_at.isoformat(), "ended_at": item.ended_at.isoformat() if item.ended_at else None,
        "seconds": item.seconds, "source": item.source, "cancelled": bool(item.cancelled_at),
        "project_id": str(item.task.project_id) if item.task.project_id in accessible else None,
        "task_id": str(item.task_id) if item.task.project_id in accessible else None,
        "note": item.note if item.task.project_id in accessible else "", "content_withheld": item.task.project_id not in accessible}
        for item in TimeEntry.objects.filter(user=user).select_related("task")]
    schedules = [{"id": str(item.id), "frequency": item.frequency, "interval": item.interval,
        "timezone_name": item.timezone_name, "generated_count": item.next_index, "stopped": bool(item.stopped_at),
        "start_local": item.start_local, "until_date": item.until_date.isoformat(),
        "occurrence_limit": item.occurrence_limit, "lead_days": item.lead_days,
        "next_run_at": item.next_run_at.isoformat() if item.next_run_at else None,
        "snapshot": item.snapshot if item.project_id in accessible else {},
        "project_id": str(item.project_id) if item.project_id in accessible else None,
        "source_task_id": str(item.source_task_id) if item.project_id in accessible else None,
        "content_withheld": item.project_id not in accessible} for item in RecurringTask.objects.filter(author=user)]
    return {"time_entries": entries, "recurring_schedules": schedules}


def close_user(user):
    """Call inside account-closure's existing user-locked transaction."""
    now = timezone.now()
    RecurringTask.objects.filter(author=user, stopped_at__isnull=True).update(stopped_at=now, stop_reason="Author account closed", next_run_at=None)
    RecurringTask.objects.filter(author=user).update(snapshot={})
    TimeEntry.objects.filter(user=user).update(note="")
    TimeEntry.objects.filter(user=user, ended_at__isnull=True, cancelled_at__isnull=True).update(cancelled_at=now)
