"""Explicitly published recruitment cards; project content stays private."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from config.models import TimestampedModel, UUIDPrimaryKeyModel


class Recruitment(UUIDPrimaryKeyModel, TimestampedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recruitments")
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="recruitments")
    title = models.CharField(max_length=120)
    university = models.CharField(max_length=120)
    course = models.CharField(max_length=60)
    term = models.CharField(max_length=80)
    description = models.TextField(max_length=3000)
    skills = models.JSONField(default=list, blank=True)
    skills_search = models.CharField(max_length=1024, blank=True, editable=False)
    languages = models.JSONField(default=list, blank=True)
    cooperation = models.CharField(max_length=12, default="hybrid", choices=[("online", "Online"), ("campus", "On campus"), ("hybrid", "Hybrid")])
    capacity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(20)])
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=[("open", "Open"), ("closed", "Closed")], default="open")
    published_at = models.DateTimeField()
    consent_at = models.DateTimeField()
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-published_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["project"], condition=models.Q(status="open"), name="one_open_recruitment_per_project"),
            models.CheckConstraint(condition=models.Q(capacity__gte=1, capacity__lte=20), name="recruitment_valid_capacity"),
        ]
        indexes = [models.Index(fields=["status", "expires_at"], name="recruitment_open_expiry_idx")]


class Application(UUIDPrimaryKeyModel, TimestampedModel):
    recruitment = models.ForeignKey(Recruitment, on_delete=models.CASCADE, related_name="applications")
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recruitment_applications")
    message = models.TextField(max_length=1500)
    status = models.CharField(max_length=12, choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected"), ("withdrawn", "Withdrawn"), ("cancelled", "Cancelled")], default="pending")
    decision_reason = models.CharField(max_length=1000, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["recruitment", "applicant"], name="one_recruitment_application_per_user")]


class Bookmark(TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    recruitment = models.ForeignKey(Recruitment, on_delete=models.CASCADE, related_name="bookmarks")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "recruitment"], name="unique_recruitment_bookmark")]


class RecruitmentReport(UUIDPrimaryKeyModel, TimestampedModel):
    recruitment = models.ForeignKey(Recruitment, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=20, choices=[("spam", "Spam"), ("harassment", "Harassment"), ("misleading", "Misleading identity or information"), ("other", "Other")])
    details = models.TextField(max_length=2000)
    status = models.CharField(max_length=12, default="open", choices=[("open", "Open"), ("resolved", "Resolved")])
    resolution = models.TextField(max_length=1000, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_recruitment_reports")

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["recruitment", "reporter"], condition=models.Q(status="open"), name="one_open_recruitment_report_per_user")]

