"""Coordination records supplement, rather than replace, real tasks and meetings."""

from django.conf import settings
from django.db import models

from config.immutable import ImmutableModelMixin, ImmutableQuerySet
from config.models import TimestampedModel, UUIDPrimaryKeyModel


class WeeklyAvailability(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    time_zone = models.CharField(max_length=64)
    slots = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("project", "user"), name="coord_unique_availability")]


class SchedulingPoll(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=120)
    agenda = models.TextField(max_length=4000, blank=True)
    location = models.CharField(max_length=2048, blank=True)
    participants = models.JSONField(default=list)
    closed_at = models.DateTimeField(null=True, blank=True)
    meeting = models.OneToOneField("meetings.Meeting", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        ordering = ("-created_at", "id")


class PollOption(UUIDPrimaryKeyModel):
    poll = models.ForeignKey(SchedulingPoll, related_name="options", on_delete=models.CASCADE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class Meta:
        ordering = ("starts_at", "id")
        constraints = [models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="coord_poll_end_after_start")]


class PollVote(UUIDPrimaryKeyModel, TimestampedModel):
    option = models.ForeignKey(PollOption, related_name="votes", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    response = models.CharField(max_length=8, choices=(("yes", "Available"), ("maybe", "If needed"), ("no", "Unavailable")))

    class Meta:
        constraints = [models.UniqueConstraint(fields=("option", "user"), name="coord_unique_poll_vote")]


class MeetingRecord(UUIDPrimaryKeyModel, TimestampedModel):
    meeting = models.OneToOneField("meetings.Meeting", related_name="coordination_record", on_delete=models.CASCADE)
    participants = models.JSONField(default=list)
    minutes = models.TextField(max_length=12000, blank=True)
    decisions = models.TextField(max_length=6000, blank=True)
    version = models.PositiveIntegerField(default=0)


class MinutesConfirmation(UUIDPrimaryKeyModel, TimestampedModel):
    record = models.ForeignKey(MeetingRecord, related_name="confirmations", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("record", "user"), name="coord_unique_minutes_confirmation")]


class AttendanceRecord(UUIDPrimaryKeyModel, TimestampedModel):
    record = models.ForeignKey(MeetingRecord, related_name="attendance", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    attended = models.BooleanField()
    note = models.CharField(max_length=500, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="recorded_coord_attendance", on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("record", "user"), name="coord_unique_actual_attendance")]


class MeetingAction(UUIDPrimaryKeyModel, TimestampedModel):
    record = models.ForeignKey(MeetingRecord, related_name="actions", on_delete=models.CASCADE)
    task = models.OneToOneField("tasks.Task", on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class MeetingSeries(UUIDPrimaryKeyModel, TimestampedModel):
    original = models.OneToOneField("meetings.Meeting", on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    interval_days = models.PositiveSmallIntegerField()
    time_zone = models.CharField(max_length=64)
    occurrence_ids = models.JSONField(default=list)


class CalendarSubscription(UUIDPrimaryKeyModel, TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    include_details = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    request_window_started_at = models.DateTimeField(null=True, blank=True)
    request_count = models.PositiveIntegerField(default=0)


class ContributionClaim(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=160)
    statement = models.TextField(max_length=6000)
    artifact_url = models.URLField(max_length=2048, blank=True)
    task = models.ForeignKey("tasks.Task", null=True, blank=True, on_delete=models.PROTECT)
    supersedes = models.OneToOneField("self", null=True, blank=True, related_name="revision", on_delete=models.PROTECT)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "id")


class ClaimContributor(UUIDPrimaryKeyModel, TimestampedModel):
    claim = models.ForeignKey(ContributionClaim, related_name="contributors", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    response = models.CharField(max_length=12, default="pending", choices=(("pending", "Pending"), ("confirmed", "Confirmed"), ("declined", "Declined")))

    class Meta:
        constraints = [models.UniqueConstraint(fields=("claim", "user"), name="coord_unique_claim_contributor")]


class ClaimReview(ImmutableModelMixin, UUIDPrimaryKeyModel):
    claim = models.ForeignKey(ContributionClaim, related_name="reviews", on_delete=models.CASCADE)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    outcome = models.CharField(max_length=20, choices=(("confirmed", "Team confirmed"), ("changes_requested", "Changes requested")))
    note = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "id")


class CoordinationEvent(ImmutableModelMixin, UUIDPrimaryKeyModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=40)
    object_id = models.UUIDField()
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "id")
