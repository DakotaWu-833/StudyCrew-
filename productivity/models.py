"""Recurring task snapshots and factual, owner-controlled time records."""
from django.conf import settings
from django.db import models
from django.db.models import Q
from config.models import TimestampedModel, UUIDPrimaryKeyModel


class RecurringTask(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    source_task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="recurring_schedules")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    frequency = models.CharField(max_length=8, choices=(("weekly", "Weekly"), ("monthly", "Monthly")))
    interval = models.PositiveSmallIntegerField(default=1)
    timezone_name = models.CharField(max_length=64)
    start_local = models.CharField(max_length=32)
    until_date = models.DateField()
    occurrence_limit = models.PositiveSmallIntegerField(default=52)
    lead_days = models.PositiveSmallIntegerField(default=7)
    next_index = models.PositiveSmallIntegerField(default=0)
    next_run_at = models.DateTimeField(null=True, blank=True)
    snapshot = models.JSONField(default=dict)
    stopped_at = models.DateTimeField(null=True, blank=True)
    stop_reason = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("-created_at", "id")
        constraints = [
            models.CheckConstraint(condition=Q(frequency__in=("weekly", "monthly")), name="productivity_frequency_valid"),
            models.CheckConstraint(condition=Q(interval__gte=1, interval__lte=12), name="productivity_interval_valid"),
            models.CheckConstraint(condition=Q(occurrence_limit__gte=1, occurrence_limit__lte=520), name="productivity_count_valid"),
            models.CheckConstraint(condition=Q(lead_days__lte=30), name="productivity_lead_valid"),
            models.UniqueConstraint(fields=("source_task",), condition=Q(stopped_at__isnull=True), name="productivity_source_one_active"),
        ]
        indexes = [models.Index(fields=("stopped_at", "next_run_at"), name="productivity_next_run_idx")]


class RecurringOccurrence(UUIDPrimaryKeyModel):
    schedule = models.ForeignKey(RecurringTask, on_delete=models.CASCADE, related_name="occurrences")
    index = models.PositiveSmallIntegerField()
    task = models.OneToOneField("tasks.Task", on_delete=models.CASCADE, related_name="recurring_occurrence")
    due_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("index",)
        constraints = [models.UniqueConstraint(fields=("schedule", "index"), name="productivity_occurrence_unique")]


class TimeEntry(UUIDPrimaryKeyModel, TimestampedModel):
    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="time_entries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    seconds = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=8, choices=(("timer", "Timer"), ("manual", "Manual")))
    note = models.CharField(max_length=500, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    corrected_at = models.DateTimeField(null=True, blank=True)
    capped = models.BooleanField(default=False)

    class Meta:
        ordering = ("-started_at", "id")
        constraints = [
            models.UniqueConstraint(fields=("user",), condition=Q(ended_at__isnull=True, cancelled_at__isnull=True), name="productivity_one_active_timer"),
            models.CheckConstraint(condition=Q(seconds__lte=86400), name="productivity_time_max_day"),
            models.CheckConstraint(condition=Q(ended_at__isnull=True) | Q(ended_at__gte=models.F("started_at")), name="productivity_time_ordered"),
        ]
        indexes = [models.Index(fields=("task", "cancelled_at"), name="productivity_task_time_idx")]
