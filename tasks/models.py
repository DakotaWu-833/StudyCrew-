"""Persistent task collaboration models."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from config.models import TimestampedModel, UUIDPrimaryKeyModel


class Task(UUIDPrimaryKeyModel, TimestampedModel):
    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked", "Blocked"
        DONE = "done", "Done"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True, max_length=4000)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TODO)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM)
    blocker_note = models.CharField(max_length=500, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tasks",
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="TaskAssignment",
        through_fields=("task", "user"),
        related_name="assigned_tasks",
    )

    class Meta:
        ordering = ("status", "due_at", "created_at")
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=("todo", "in_progress", "blocked", "done")),
                name="task_valid_status",
            ),
            models.CheckConstraint(
                condition=Q(priority__in=("low", "medium", "high", "urgent")),
                name="task_valid_priority",
            ),
            models.CheckConstraint(
                condition=~Q(status="blocked") | ~Q(blocker_note=""),
                name="task_blocked_has_note",
            ),
            models.CheckConstraint(
                condition=(Q(status="done") & Q(completed_at__isnull=False))
                | (~Q(status="done") & Q(completed_at__isnull=True)),
                name="task_completion_matches_status",
            ),
        ]
        indexes = [
            models.Index(fields=("project", "status", "priority"), name="task_project_board_idx"),
            models.Index(fields=("project", "due_at"), name="task_project_due_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        self.title = self.title.strip()
        if not 3 <= len(self.title) <= 120:
            raise ValidationError({"title": "Title must contain between 3 and 120 characters."})
        if self.status == self.Status.BLOCKED and not 3 <= len(self.blocker_note.strip()) <= 500:
            raise ValidationError({"blocker_note": "A blocker note of 3 to 500 characters is required."})
        if self.status == self.Status.DONE and self.completed_at is None:
            raise ValidationError({"completed_at": "Completed tasks require a completion time."})
        if self.status != self.Status.DONE and self.completed_at is not None:
            raise ValidationError({"completed_at": "Only completed tasks may have a completion time."})

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def __str__(self) -> str:
        return self.title


class TaskAssignment(UUIDPrimaryKeyModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_assignments_created",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("task", "user"), name="unique_task_assignee"),
        ]
        indexes = [models.Index(fields=("user", "assigned_at"), name="task_assignee_time_idx")]


class TaskComment(UUIDPrimaryKeyModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_comments",
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="moderated_task_comments",
    )

    class Meta:
        ordering = ("created_at",)
        indexes = [models.Index(fields=("task", "created_at"), name="comment_task_time_idx")]

    def clean(self) -> None:
        super().clean()
        self.body = self.body.strip()
        if not 1 <= len(self.body) <= 2000:
            raise ValidationError({"body": "Comment must contain between 1 and 2000 characters."})

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __str__(self) -> str:
        return "[deleted]" if self.is_deleted else self.body[:60]


class ContentReport(UUIDPrimaryKeyModel):
    class Reason(models.TextChoices):
        ABUSE = "abuse", "Abusive content"
        PRIVACY = "privacy", "Personal or private information"
        SPAM = "spam", "Spam"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    comment = models.ForeignKey(TaskComment, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="content_reports",
    )
    reason = models.CharField(max_length=16, choices=Reason.choices)
    details = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="resolved_content_reports",
    )
    resolution_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("comment", "reporter"),
                condition=Q(status="pending"),
                name="unique_pending_comment_report",
            ),
        ]
        permissions = [("moderate_reports", "Can review and resolve content reports")]

    def clean(self) -> None:
        super().clean()
        if self.reason == self.Reason.OTHER and not self.details.strip():
            raise ValidationError({"details": "Please explain reports submitted as other."})
        if self.status == self.Status.PENDING and (self.resolved_at or self.resolved_by_id):
            raise ValidationError("A pending report cannot have resolution details.")
        if self.status != self.Status.PENDING and not self.resolved_at:
            self.resolved_at = timezone.now()
