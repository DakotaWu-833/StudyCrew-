"""Transactional coordination; permissions are always checked at the write boundary."""

import hashlib
import secrets
from datetime import timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, Throttled

from meetings.models import MeetingAttendance, latest_allowed_meeting_datetime
from meetings.policies import require_meeting_manager
from meetings.services import create_meeting
from projects.models import ProjectMembership
from projects.policies import require_project_member
from tasks.services import create_task, replace_assignees

from .models import (
    AttendanceRecord, CalendarSubscription, ClaimContributor, ClaimReview,
    ContributionClaim, CoordinationEvent, MeetingAction, MeetingRecord,
    MeetingSeries, MinutesConfirmation, PollOption, PollVote, SchedulingPoll,
    WeeklyAvailability,
)
from .policies import require_claim_reviewer, require_poll_manager, require_writable


def event(*, project, actor, kind, object_id, metadata=None):
    return CoordinationEvent.objects.create(project=project, actor=actor, kind=kind, object_id=object_id, metadata=metadata or {})


def _active_ids(project):
    return {str(value) for value in ProjectMembership.objects.filter(project=project, removed_at__isnull=True, user__is_active=True).values_list("user_id", flat=True)}


def validate_participants(project, participants):
    if not isinstance(participants, list) or not participants or len(participants) > 100:
        raise ValidationError({"participants": "Choose between 1 and 100 current team members."})
    seen = set()
    eligible = _active_ids(project)
    result = []
    for entry in participants:
        if not isinstance(entry, dict) or set(entry) != {"user_id", "required"}:
            raise ValidationError({"participants": "Each participant needs a user ID and a required flag."})
        uid = str(entry["user_id"])
        if uid not in eligible or uid in seen or not isinstance(entry["required"], bool):
            raise ValidationError({"participants": "Participants must be distinct current active team members."})
        seen.add(uid)
        result.append({"user_id": uid, "required": entry["required"]})
    return result


def validate_times(starts_at, ends_at):
    if timezone.is_naive(starts_at) or timezone.is_naive(ends_at) or ends_at <= starts_at:
        raise ValidationError("Provide a time zone and an end time after the start time.")
    if starts_at < timezone.now() or ends_at > latest_allowed_meeting_datetime():
        raise ValidationError("Candidate times must be in the future and within ten years.")
    if ends_at - starts_at > timedelta(hours=12):
        raise ValidationError("A candidate meeting cannot be longer than twelve hours.")


@transaction.atomic
def save_availability(*, actor, project, time_zone, slots):
    require_writable(actor, project)
    try:
        ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValidationError({"time_zone": "Choose a valid IANA time zone."})
    if not isinstance(slots, list) or len(slots) > 100:
        raise ValidationError({"slots": "Provide at most 100 weekly availability blocks."})
    checked = []
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) != {"weekday", "start_minute", "end_minute"}:
            raise ValidationError({"slots": "Each block requires a weekday, start minute and end minute."})
        day, start, end = (slot[key] for key in ("weekday", "start_minute", "end_minute"))
        if any(type(value) is not int for value in (day, start, end)) or not 0 <= day <= 6 or not 0 <= start < end <= 1440:
            raise ValidationError({"slots": "Weekdays are 0–6 and times are minutes from midnight."})
        if start % 30 or end % 30:
            raise ValidationError({"slots": "Use half-hour boundaries."})
        if any(item["weekday"] == day and start < item["end_minute"] and end > item["start_minute"] for item in checked):
            raise ValidationError({"slots": "Availability blocks must not overlap."})
        checked.append(dict(slot))
    pattern, _ = WeeklyAvailability.objects.update_or_create(project=project, user=actor, defaults={"time_zone": time_zone, "slots": checked})
    event(project=project, actor=actor, kind="availability_saved", object_id=pattern.id, metadata={"block_count": len(checked)})
    return pattern


@transaction.atomic
def create_poll(*, actor, project, title, agenda, location, participants, options):
    require_writable(actor, project)
    participants = validate_participants(project, participants)
    if not 3 <= len(title.strip()) <= 120 or len(agenda) > 4000 or len(location) > 2048:
        raise ValidationError("Provide a title of 3–120 characters and bounded meeting details.")
    if not 2 <= len(options) <= 12:
        raise ValidationError({"options": "Provide 2–12 candidate times."})
    unique = set()
    for option in options:
        validate_times(option["starts_at"], option["ends_at"])
        pair = (option["starts_at"], option["ends_at"])
        if pair in unique:
            raise ValidationError({"options": "Candidate times must be distinct."})
        unique.add(pair)
    poll = SchedulingPoll.objects.create(project=project, creator=actor, title=title.strip(), agenda=agenda.strip(), location=location.strip(), participants=participants)
    PollOption.objects.bulk_create([PollOption(poll=poll, **option) for option in options])
    event(project=project, actor=actor, kind="poll_created", object_id=poll.id)
    return poll


@transaction.atomic
def vote_option(*, actor, option, response):
    poll = SchedulingPoll.objects.select_for_update().select_related("project").get(pk=option.poll_id)
    require_writable(actor, poll.project)
    if poll.closed_at:
        raise ValidationError("This poll has closed.")
    if str(actor.pk) not in {entry["user_id"] for entry in poll.participants}:
        raise PermissionDenied("Only invited participants may vote.")
    if response not in {"yes", "maybe", "no"}:
        raise ValidationError({"response": "Choose available, if needed or unavailable."})
    vote, _ = PollVote.objects.update_or_create(option=option, user=actor, defaults={"response": response})
    event(project=poll.project, actor=actor, kind="poll_vote", object_id=option.id, metadata={"response": response})
    return vote


@transaction.atomic
def close_poll(*, actor, poll, option_id):
    poll = SchedulingPoll.objects.select_for_update().select_related("project").get(pk=poll.pk)
    require_poll_manager(actor, poll)
    if poll.closed_at:
        raise ValidationError("This poll has already been closed.")
    option = poll.options.filter(pk=option_id).first()
    if not option:
        raise ValidationError({"option_id": "Choose one of this poll's candidate times."})
    participants = validate_participants(poll.project, poll.participants)
    yes_ids = {str(value) for value in option.votes.filter(response="yes").values_list("user_id", flat=True)}
    required_ids = {item["user_id"] for item in participants if item["required"]}
    if not required_ids.issubset(yes_ids):
        raise ValidationError("Every required participant must mark this candidate available before it can be scheduled.")
    validate_times(option.starts_at, option.ends_at)
    meeting = create_meeting(actor=actor, project=poll.project, title=poll.title, starts_at=option.starts_at, ends_at=option.ends_at, location=poll.location, agenda=poll.agenda)
    MeetingRecord.objects.create(meeting=meeting, participants=participants)
    for participant in participants:
        MeetingAttendance.objects.create(meeting=meeting, user_id=participant["user_id"], response="accepted" if participant["user_id"] in yes_ids else "pending", responded_at=timezone.now() if participant["user_id"] in yes_ids else None)
    poll.meeting = meeting
    poll.closed_at = timezone.now()
    poll.save(update_fields=("meeting", "closed_at", "updated_at"))
    event(project=poll.project, actor=actor, kind="poll_scheduled", object_id=poll.id, metadata={"meeting_id": str(meeting.id)})
    return meeting


@transaction.atomic
def cancel_poll(*, actor, poll):
    poll = SchedulingPoll.objects.select_for_update().select_related("project").get(pk=poll.pk)
    require_poll_manager(actor, poll)
    if poll.closed_at:
        raise ValidationError("This poll has already closed.")
    poll.closed_at = timezone.now()
    poll.save(update_fields=("closed_at", "updated_at"))
    event(project=poll.project, actor=actor, kind="poll_cancelled", object_id=poll.id)
    return poll


@transaction.atomic
def save_meeting_record(*, actor, meeting, participants=None, minutes=None, decisions=None, expected_version=None):
    require_writable(actor, meeting.project)
    require_meeting_manager(user=actor, meeting=meeting)
    if meeting.is_archived or meeting.is_cancelled:
        raise ValidationError("Cancelled and archived meetings are read-only.")
    record, _ = MeetingRecord.objects.get_or_create(meeting=meeting)
    record = MeetingRecord.objects.select_for_update().get(pk=record.pk)
    if expected_version is not None and expected_version != record.version:
        raise ValidationError("This meeting record changed. Reload it before saving; your local draft is retained.")
    if participants is not None:
        record.participants = validate_participants(meeting.project, participants)
    if minutes is not None or decisions is not None:
        if meeting.starts_at > timezone.now():
            raise ValidationError("Minutes and decisions can be recorded once the meeting starts.")
        if minutes is not None:
            if len(minutes) > 12000:
                raise ValidationError({"minutes": "Minutes cannot exceed 12,000 characters."})
            record.minutes = minutes.strip()
        if decisions is not None:
            if len(decisions) > 6000:
                raise ValidationError({"decisions": "Decisions cannot exceed 6,000 characters."})
            record.decisions = decisions.strip()
    record.version += 1
    record.save()
    event(project=meeting.project, actor=actor, kind="meeting_record_saved", object_id=record.id, metadata={"version": record.version, "minutes": record.minutes, "decisions": record.decisions, "participants": record.participants})
    return record


@transaction.atomic
def confirm_minutes(*, actor, record, version):
    record = MeetingRecord.objects.select_for_update().select_related("meeting__project").get(pk=record.pk)
    require_writable(actor, record.meeting.project)
    if record.meeting.is_cancelled or record.meeting.is_archived:
        raise ValidationError("Cancelled and archived meetings are read-only.")
    if version != record.version or not (record.minutes or record.decisions):
        raise ValidationError("Read the current saved minutes before confirming them.")
    confirmation, _ = MinutesConfirmation.objects.update_or_create(record=record, user=actor, defaults={"version": version})
    event(project=record.meeting.project, actor=actor, kind="minutes_confirmed", object_id=record.id, metadata={"version": version})
    return confirmation


@transaction.atomic
def record_attendance(*, actor, record, user_id, attended, note):
    record = MeetingRecord.objects.select_for_update().select_related("meeting__project").get(pk=record.pk)
    require_writable(actor, record.meeting.project)
    require_meeting_manager(user=actor, meeting=record.meeting)
    if record.meeting.starts_at > timezone.now() or record.meeting.is_cancelled or record.meeting.is_archived:
        raise ValidationError("Record actual attendance only for a started, non-cancelled, unarchived meeting.")
    # Former participants remain eligible for factual correction, but cannot write.
    eligible = set(ProjectMembership.objects.filter(project=record.meeting.project).values_list("user_id", flat=True))
    if user_id not in eligible:
        raise ValidationError({"user_id": "This person has no membership history in the project."})
    if not note.strip() or len(note) > 500:
        raise ValidationError({"note": "Provide a reason or source of 1–500 characters, including for corrections."})
    previous = AttendanceRecord.objects.filter(record=record, user_id=user_id).first()
    attendance, _ = AttendanceRecord.objects.update_or_create(record=record, user_id=user_id, defaults={"attended": attended, "note": note.strip(), "recorded_by": actor})
    event(project=record.meeting.project, actor=actor, kind="attendance_corrected" if previous else "attendance_recorded", object_id=record.id, metadata={"user_id": str(user_id), "from": previous.attended if previous else None, "to": attended, "note": note.strip()})
    return attendance


@transaction.atomic
def add_action(*, actor, record, title, description, due_at, assignee_ids):
    require_writable(actor, record.meeting.project)
    require_meeting_manager(user=actor, meeting=record.meeting)
    if record.meeting.is_cancelled or record.meeting.is_archived or record.meeting.starts_at > timezone.now():
        raise ValidationError("Action items require a started, non-cancelled, unarchived meeting.")
    if {str(uid) for uid in assignee_ids} - _active_ids(record.meeting.project):
        raise ValidationError({"assignee_ids": "Assign current active project members."})
    task = create_task(actor=actor, project=record.meeting.project, data={"title": title, "description": description, "due_at": due_at})
    replace_assignees(actor=actor, task=task, assignee_ids=assignee_ids)
    action = MeetingAction.objects.create(record=record, task=task, created_by=actor)
    event(project=record.meeting.project, actor=actor, kind="meeting_action_created", object_id=record.id, metadata={"task_id": str(task.id)})
    return action


@transaction.atomic
def repeat_meeting(*, actor, meeting, count, interval_days, time_zone):
    require_writable(actor, meeting.project)
    require_meeting_manager(user=actor, meeting=meeting)
    if meeting.is_cancelled or meeting.is_archived or meeting.ends_at <= timezone.now():
        raise ValidationError("Repeat a current, non-cancelled meeting.")
    if not 1 <= count <= 12 or interval_days not in {7, 14}:
        raise ValidationError("Create 1–12 additional weekly or fortnightly occurrences.")
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValidationError({"time_zone": "Choose a valid IANA time zone."})
    if MeetingSeries.objects.filter(original=meeting).exists():
        raise ValidationError("This meeting already has a generated series; edit the individual occurrences.")
    # Wall-clock arithmetic preserves the chosen local time through DST.
    local_start, local_end = meeting.starts_at.astimezone(zone), meeting.ends_at.astimezone(zone)
    record = MeetingRecord.objects.filter(meeting=meeting).first()
    participants = validate_participants(meeting.project, record.participants) if record and record.participants else []
    series = MeetingSeries.objects.create(original=meeting, created_by=actor, interval_days=interval_days, time_zone=time_zone)
    occurrence_ids = []
    for index in range(1, count + 1):
        start = (local_start + timedelta(days=interval_days * index)).astimezone(datetime_timezone.utc)
        end = (local_end + timedelta(days=interval_days * index)).astimezone(datetime_timezone.utc)
        validate_times(start, end)
        created = create_meeting(actor=actor, project=meeting.project, title=meeting.title, starts_at=start, ends_at=end, location=meeting.location, agenda=meeting.agenda)
        MeetingRecord.objects.create(meeting=created, participants=participants)
        occurrence_ids.append(str(created.id))
    series.occurrence_ids = occurrence_ids
    series.save(update_fields=("occurrence_ids", "updated_at"))
    event(project=meeting.project, actor=actor, kind="meeting_series_created", object_id=series.id, metadata={"occurrence_ids": occurrence_ids, "interval_days": interval_days})
    return series


def token_digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@transaction.atomic
def issue_subscription(*, actor, project=None, include_details=False, subscription=None):
    if project:
        require_project_member(actor, project)
    if subscription:
        subscription = CalendarSubscription.objects.select_for_update().get(pk=subscription.pk, user=actor)
        subscription.revoked_at = timezone.now()
        subscription.save(update_fields=("revoked_at", "updated_at"))
        project, include_details = subscription.project, subscription.include_details
        if project:
            require_project_member(actor, project)
    if CalendarSubscription.objects.filter(user=actor, revoked_at__isnull=True, expires_at__gt=timezone.now()).count() >= 10:
        raise ValidationError("Revoke an existing calendar subscription before adding another.")
    raw = secrets.token_urlsafe(32)
    subscription = CalendarSubscription.objects.create(user=actor, project=project, include_details=include_details, token_hash=token_digest(raw), expires_at=timezone.now() + timedelta(days=365))
    return subscription, raw


@transaction.atomic
def revoke_subscription(*, actor, subscription):
    if subscription.user_id != actor.pk:
        raise PermissionDenied("This calendar subscription belongs to another account.")
    subscription.revoked_at = timezone.now()
    subscription.save(update_fields=("revoked_at", "updated_at"))


@transaction.atomic
def consume_subscription(raw):
    if not isinstance(raw, str) or not 30 <= len(raw) <= 100:
        raise NotFound("Calendar subscription not found.")
    subscription = CalendarSubscription.objects.select_for_update().select_related("user", "user__profile", "project").filter(token_hash=token_digest(raw), revoked_at__isnull=True, expires_at__gt=timezone.now(), user__is_active=True).first()
    if not subscription:
        raise NotFound("Calendar subscription not found.")
    if subscription.project:
        # A removed member's old bearer link must no longer reveal this project.
        if str(subscription.user_id) not in _active_ids(subscription.project):
            raise NotFound("Calendar subscription not found.")
    now = timezone.now()
    if not subscription.request_window_started_at or now - subscription.request_window_started_at >= timedelta(hours=1):
        subscription.request_window_started_at, subscription.request_count = now, 0
    if subscription.request_count >= 60:
        raise Throttled(wait=3600, detail="This calendar has refreshed too often.")
    subscription.request_count += 1
    subscription.save(update_fields=("request_window_started_at", "request_count", "updated_at"))
    return subscription


@transaction.atomic
def create_claim(*, actor, project, title, statement, artifact_url="", task=None, contributor_ids=(), supersedes=None):
    require_writable(actor, project)
    if not 3 <= len(title.strip()) <= 160 or not 10 <= len(statement.strip()) <= 6000:
        raise ValidationError("Use a 3–160 character title and a 10–6,000 character contribution statement.")
    if artifact_url:
        URLValidator(schemes=("http", "https"))(artifact_url)
    if task and task.project_id != project.pk:
        raise ValidationError({"task_id": "The linked task must belong to this project."})
    ids = {str(uid) for uid in contributor_ids}
    if str(actor.pk) in ids or ids - _active_ids(project):
        raise ValidationError({"contributor_ids": "Choose other current active project members."})
    if supersedes and (supersedes.author_id != actor.pk or supersedes.project_id != project.pk or ContributionClaim.objects.filter(supersedes=supersedes).exists()):
        raise ValidationError({"supersedes_id": "Revise your own most recent claim in this project."})
    claim = ContributionClaim(project=project, author=actor, title=title.strip(), statement=statement.strip(), artifact_url=artifact_url, task=task, supersedes=supersedes)
    claim.full_clean()
    claim.save()
    ClaimContributor.objects.bulk_create([ClaimContributor(claim=claim, user_id=uid) for uid in ids])
    event(project=project, actor=actor, kind="contribution_claimed", object_id=claim.id, metadata={"supersedes_id": str(supersedes.id) if supersedes else None})
    return claim


@transaction.atomic
def respond_claim(*, actor, claim, response):
    claim = ContributionClaim.objects.select_for_update().select_related("project").get(pk=claim.pk)
    require_writable(actor, claim.project)
    if claim.withdrawn_at or ContributionClaim.objects.filter(supersedes=claim).exists():
        raise ValidationError("This claim was withdrawn or superseded.")
    if response not in {"confirmed", "declined"}:
        raise ValidationError({"response": "Confirm or decline the joint contribution attribution."})
    contributor = claim.contributors.filter(user=actor).first()
    if not contributor:
        raise PermissionDenied("Only a named collaborator can confirm their contribution.")
    contributor.response = response
    contributor.save(update_fields=("response", "updated_at"))
    event(project=claim.project, actor=actor, kind="joint_contribution_response", object_id=claim.id, metadata={"response": response})
    return contributor


@transaction.atomic
def review_claim(*, actor, claim, outcome, note):
    claim = ContributionClaim.objects.select_for_update().select_related("project").get(pk=claim.pk)
    require_claim_reviewer(actor, claim)
    if claim.withdrawn_at or ContributionClaim.objects.filter(supersedes=claim).exists():
        raise ValidationError("This claim was withdrawn or superseded.")
    if outcome not in {"confirmed", "changes_requested"} or not note.strip() or len(note) > 1000:
        raise ValidationError("Choose an outcome and provide a review note of 1–1,000 characters.")
    if outcome == "confirmed" and claim.contributors.exclude(response="confirmed").exists():
        raise ValidationError("Every named collaborator must confirm their attribution before team confirmation.")
    review = ClaimReview.objects.create(claim=claim, reviewer=actor, outcome=outcome, note=note.strip())
    event(project=claim.project, actor=actor, kind="contribution_reviewed", object_id=claim.id, metadata={"outcome": outcome, "note": note.strip()})
    return review


@transaction.atomic
def withdraw_claim(*, actor, claim):
    require_writable(actor, claim.project)
    if claim.author_id != actor.pk:
        raise PermissionDenied("Only the author can withdraw a claim.")
    if not claim.withdrawn_at:
        claim.withdrawn_at = timezone.now()
        claim.save(update_fields=("withdrawn_at", "updated_at"))
        event(project=claim.project, actor=actor, kind="contribution_withdrawn", object_id=claim.id)
    return claim
