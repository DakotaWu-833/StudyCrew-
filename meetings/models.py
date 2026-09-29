"""Meeting scheduling and RSVP persistence."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from config.models import TimestampedModel, UUIDPrimaryKeyModel


def latest_allowed_meeting_datetime(*, reference=None):
    """Return the inclusive ten-calendar-year scheduling horizon.

    Calendar-year replacement keeps the rule understandable to users.  A leap
    day safely contracts to 28 February when the target year is not a leap
    year.
    """

    reference = reference or timezone.now()
    try:
        return reference.replace(year=reference.year + 10)
    except ValueError:
        return reference.replace(year=reference.year + 10, day=28)


class Meeting(UUIDPrimaryKeyModel, TimestampedModel):
    """A retained project meeting; cancellation is deliberately a soft state."""

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="meetings",
    )
    organiser = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organised_meetings",
    )
    title = models.CharField(max_length=120, validators=[MinLengthValidator(3)])
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=2048, blank=True)
    agenda = models.TextField(max_length=4000, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("starts_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="meeting_end_after_start",
            ),
            models.CheckConstraint(
                condition=(
                    Q(archived_at__isnull=True)
                    | Q(cancelled_at__isnull=False)
                    | Q(ends_at__lte=F("archived_at"))
                ),
                name="meeting_archive_after_terminal_state",
            ),
        ]
        indexes = [
            models.Index(fields=("project", "starts_at"), name="meeting_project_start_idx"),
            models.Index(fields=("project", "cancelled_at"), name="meeting_project_cancel_idx"),
            models.Index(
                fields=("project", "archived_at", "starts_at"),
                name="meeting_project_archive_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.starts_at and timezone.is_naive(self.starts_at):
            errors["starts_at"] = "Start time must include a time zone."
        if self.ends_at and timezone.is_naive(self.ends_at):
            errors["ends_at"] = "End time must include a time zone."
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "End time must be later than start time."
        if self.cancelled_at and timezone.is_naive(self.cancelled_at):
            errors["cancelled_at"] = "Cancellation time must include a time zone."
        if self.archived_at and timezone.is_naive(self.archived_at):
            errors["archived_at"] = "Archive time must include a time zone."
        horizon = latest_allowed_meeting_datetime()
        if self.starts_at and timezone.is_aware(self.starts_at) and self.starts_at > horizon:
            errors["starts_at"] = "Start time cannot be more than ten years in the future."
        if self.ends_at and timezone.is_aware(self.ends_at) and self.ends_at > horizon:
            errors["ends_at"] = "End time cannot be more than ten years in the future."
        if (
            self.archived_at
            and timezone.is_aware(self.archived_at)
            and self.ends_at
            and timezone.is_aware(self.ends_at)
            and not self.cancelled_at
            and self.ends_at > self.archived_at
        ):
            errors["archived_at"] = "Only a cancelled or ended meeting can be archived."
        if errors:
            raise ValidationError(errors)

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def is_ended(self) -> bool:
        return self.ends_at <= timezone.now()

    @property
    def lifecycle_state(self) -> str:
        if self.is_archived:
            return "archived"
        if self.is_cancelled:
            return "cancelled"
        if self.is_ended:
            return "ended"
        return "scheduled"

    def __str__(self) -> str:
        return self.title


class MeetingAttendance(UUIDPrimaryKeyModel):
    """One mutable RSVP per meeting/member pair."""

    class Response(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name="attendances",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="meeting_attendances",
    )
    response = models.CharField(
        max_length=16,
        choices=Response.choices,
        default=Response.PENDING,
    )
    availability_note = models.CharField(max_length=500, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("meeting", "user"),
                name="unique_meeting_attendee",
            ),
            models.CheckConstraint(
                condition=Q(response__in=("pending", "accepted", "declined")),
                name="attendance_valid_response",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "response"), name="attendance_user_resp_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}: {self.response}"
