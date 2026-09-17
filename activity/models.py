"""Append-only evidence, notifications, exports, and site audit models."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from config.models import TimestampedModel, UUIDPrimaryKeyModel


class ImmutableRecordError(TypeError):
    """Raised when application code attempts to mutate audit evidence."""


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError("Append-only records cannot be updated.")

    def delete(self):
        raise ImmutableRecordError("Append-only records cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ImmutableRecordError("Append-only records cannot be updated.")


class ImmutableModelMixin(models.Model):
    """Application-level guard for evidence rows after their first insert."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Append-only records cannot be updated.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Append-only records cannot be deleted.")


def validate_metadata(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("Audit metadata must be a JSON object.")

    forbidden_keys = {
        "password",
        "password_hash",
        "secret",
        "token",
        "token_hash",
        "otp",
        "comment_body",
    }

    def inspect(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested_value in item.items():
                if str(key).strip().lower() in forbidden_keys:
                    raise ValidationError(f"Sensitive metadata key '{key}' is not permitted.")
                inspect(nested_value)
        elif isinstance(item, list):
            for nested_value in item:
                inspect(nested_value)

    inspect(value)


class ActivityEvent(ImmutableModelMixin, UUIDPrimaryKeyModel):
    """Immutable, factual evidence emitted with successful project mutations."""

    class Type(models.TextChoices):
        PROJECT_CREATED = "project_created", "Project created"
        PROJECT_UPDATED = "project_updated", "Project updated"
        PROJECT_ARCHIVED = "project_archived", "Project archived"
        INVITATION_CREATED = "invitation_created", "Invitation created"
        INVITATION_DECLINED = "invitation_declined", "Invitation declined"
        INVITATION_CANCELLED = "invitation_cancelled", "Invitation cancelled"
        INVITATION_EXPIRED = "invitation_expired", "Invitation expired"
        MEMBER_JOINED = "member_joined", "Member joined"
        MEMBER_ROLE_CHANGED = "member_role_changed", "Member role changed"
        MEMBER_REMOVED = "member_removed", "Member removed"
        OWNERSHIP_TRANSFERRED = "ownership_transferred", "Ownership transferred"
        TASK_CREATED = "task_created", "Task created"
        TASK_UPDATED = "task_updated", "Task updated"
        TASK_ARCHIVED = "task_archived", "Task archived"
        TASK_ASSIGNEES_CHANGED = "task_assignees_changed", "Task assignees changed"
        TASK_ASSIGNED = "task_assigned", "Task assigned"
        TASK_UNASSIGNED = "task_unassigned", "Task unassigned"
        TASK_STATUS_CHANGED = "task_status_changed", "Task status changed"
        COMMENT_CREATED = "comment_created", "Comment created"
        COMMENT_EDITED = "comment_edited", "Comment edited"
        COMMENT_DELETED = "comment_deleted", "Comment deleted"
        COMMENT_MODERATED = "comment_moderated", "Comment moderated"
        COMMENT_REPORTED = "comment_reported", "Comment reported"
        MEETING_CREATED = "meeting_created", "Meeting created"
        MEETING_UPDATED = "meeting_updated", "Meeting updated"
        MEETING_CANCELLED = "meeting_cancelled", "Meeting cancelled"
        MEETING_RSVP = "meeting_rsvp", "Meeting RSVP changed"
        EXPORT_REQUESTED = "export_requested", "Export requested"
        EXPORT_READY = "export_ready", "Export ready"
        EXPORT_FAILED = "export_failed", "Export failed"

    class TargetType(models.TextChoices):
        PROJECT = "project", "Project"
        MEMBERSHIP = "membership", "Project membership"
        INVITATION = "invitation", "Project invitation"
        TASK = "task", "Task"
        COMMENT = "comment", "Task comment"
        MEETING = "meeting", "Meeting"
        ATTENDANCE = "attendance", "Meeting attendance"
        EXPORT = "export", "Export job"

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="activity_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="activity_events",
    )
    event_type = models.CharField(max_length=40, choices=Type.choices)
    target_type = models.CharField(max_length=24, choices=TargetType.choices, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True, validators=[validate_metadata])
    occurred_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        ordering = ("-occurred_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(target_type="", target_id__isnull=True)
                    | (~models.Q(target_type="") & models.Q(target_id__isnull=False))
                ),
                name="activity_target_pair_complete",
            ),
        ]
        indexes = [
            models.Index(fields=("project", "occurred_at"), name="activity_project_time_idx"),
            models.Index(fields=("actor", "occurred_at"), name="activity_actor_time_idx"),
            models.Index(fields=("project", "event_type"), name="activity_project_type_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        validate_metadata(self.metadata)
        if bool(self.target_type) != bool(self.target_id):
            raise ValidationError("Activity target type and target ID must be supplied together.")

    def __str__(self) -> str:
        return f"{self.event_type} by {self.actor_id} at {self.occurred_at.isoformat()}"


class Notification(UUIDPrimaryKeyModel, TimestampedModel):
    """A recipient-owned in-app notification linked to its source evidence."""

    class Type(models.TextChoices):
        INVITATION = "invitation", "Invitation"
        TASK_ASSIGNMENT = "task_assignment", "Task assignment"
        COMMENT_MENTION = "comment_mention", "Comment mention"
        MEETING_CHANGE = "meeting_change", "Meeting change"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    source_event = models.ForeignKey(
        ActivityEvent,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    notification_type = models.CharField(max_length=24, choices=Type.choices)
    target_url = models.CharField(max_length=500)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("recipient", "source_event"),
                name="unique_notification_recipient_event",
            ),
        ]
        indexes = [
            models.Index(fields=("recipient", "read_at", "created_at"), name="notification_inbox_idx"),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def __str__(self) -> str:
        return f"{self.notification_type} for {self.recipient_id}"


class ExportJob(UUIDPrimaryKeyModel, TimestampedModel):
    """A time-bounded evidence export request retained independently of files."""

    class Format(models.TextChoices):
        PDF = "pdf", "PDF"
        CSV = "csv", "CSV"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="export_jobs",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_export_jobs",
    )
    format = models.CharField(max_length=8, choices=Format.choices)
    range_start = models.DateField()
    range_end = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    storage_key = models.CharField(max_length=512, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(range_end__gte=models.F("range_start")),
                name="export_end_not_before_start",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    range_end__lte=models.F("range_start") + timedelta(days=366)
                ),
                name="export_range_at_most_366_days",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="ready")
                    | (
                        ~models.Q(storage_key="")
                        & models.Q(expires_at__isnull=False)
                        & models.Q(completed_at__isnull=False)
                    )
                ),
                name="ready_export_has_file_and_expiry",
            ),
        ]
        indexes = [
            models.Index(fields=("project", "created_at"), name="export_project_time_idx"),
            models.Index(fields=("status", "expires_at"), name="export_status_expiry_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        if self.range_start and self.range_end:
            if self.range_end < self.range_start:
                raise ValidationError({"range_end": "End date cannot precede start date."})
            if self.range_end - self.range_start > timedelta(days=366):
                raise ValidationError({"range_end": "Export range cannot exceed 366 days."})
        if self.status == self.Status.READY and not (
            self.storage_key and self.completed_at and self.expires_at
        ):
            raise ValidationError("A ready export requires a file, completion time, and expiry.")


class SiteAuditEvent(ImmutableModelMixin, UUIDPrimaryKeyModel):
    """Immutable evidence for limited mutations from the custom site panel."""

    class Action(models.TextChoices):
        USER_DISABLED = "user_disabled", "User disabled"
        USER_ENABLED = "user_enabled", "User enabled"
        COMMENT_MODERATED = "comment_moderated", "Comment moderated"
        CONTENT_REPORT_RESOLVED = "content_report_resolved", "Content report resolved"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="site_audit_events",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    target_type = models.CharField(max_length=32)
    target_id = models.UUIDField()
    metadata = models.JSONField(default=dict, blank=True, validators=[validate_metadata])
    occurred_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        ordering = ("-occurred_at", "-id")
        indexes = [
            models.Index(fields=("actor", "occurred_at"), name="site_audit_actor_time_idx"),
            models.Index(fields=("target_type", "target_id"), name="site_audit_target_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        validate_metadata(self.metadata)

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_id}"
