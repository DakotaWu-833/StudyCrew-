"""Durable delivery, user preferences and bounded support workflows."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from config.models import TimestampedModel, UUIDPrimaryKeyModel
from config.immutable import ImmutableModelMixin, ImmutableQuerySet


class NotificationPreference(TimestampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences")
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=True)
    task_reminders = models.BooleanField(default=True)
    meeting_reminders = models.BooleanField(default=True)
    assignments = models.BooleanField(default=True)
    mentions = models.BooleanField(default=True)
    invitations = models.BooleanField(default=True)
    meeting_changes = models.BooleanField(default=True)
    digest = models.CharField(max_length=8, choices=[("off", "Off"), ("daily", "Daily"), ("weekly", "Weekly")], default="off")
    quiet_start = models.TimeField(null=True, blank=True)
    quiet_end = models.TimeField(null=True, blank=True)


class ProjectMute(TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    muted = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "project"], name="unique_project_notification_mute")]


class OutboundMessage(UUIDPrimaryKeyModel, TimestampedModel):
    """SMTP accepted is distinct from externally confirmed delivered."""
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        ACCEPTED = "accepted", "Accepted by mail server"
        DELIVERED = "delivered", "Delivery confirmed"
        FAILED = "failed", "Failed"
        BOUNCED = "bounced", "Bounced"
        COMPLAINED = "complained", "Complaint"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    project = models.ForeignKey("projects.Project", on_delete=models.SET_NULL, null=True, blank=True)
    recipient = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField(max_length=12000)
    category = models.CharField(max_length=32, default="service")
    deduplication_key = models.CharField(max_length=200, unique=True)
    target_type = models.CharField(max_length=24, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    target_revision = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    available_at = models.DateTimeField(default=timezone.now)
    locked_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    accepted_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["available_at", "created_at"]
        indexes = [models.Index(fields=["status", "available_at"], name="outbound_ready_idx")]


class UserAlert(UUIDPrimaryKeyModel, TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    category = models.CharField(max_length=32)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=1000)
    target_url = models.CharField(max_length=500)
    deduplication_key = models.CharField(max_length=200, unique=True)
    target_type = models.CharField(max_length=24, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    target_revision = models.CharField(max_length=100, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class SuppressedAddress(TimestampedModel):
    email = models.EmailField(unique=True)
    reason = models.CharField(max_length=24, choices=[("bounce", "Permanent bounce"), ("complaint", "Complaint")])


class WebhookReceipt(TimestampedModel):
    signature = models.CharField(max_length=64, unique=True)


class SupportTicket(UUIDPrimaryKeyModel, TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    category = models.CharField(max_length=20, choices=[("help", "Help"), ("bug", "Bug"), ("appeal", "Appeal"), ("privacy", "Privacy"), ("feedback", "Feedback")])
    subject = models.CharField(max_length=160)
    description = models.TextField(max_length=4000)
    status = models.CharField(max_length=20, choices=[("open", "Open"), ("in_progress", "In progress"), ("awaiting_user", "Awaiting user"), ("resolved", "Resolved")], default="open")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_support_tickets")
    resolution = models.TextField(max_length=2000, blank=True)

    class Meta:
        ordering = ["-updated_at", "-id"]


class TicketReply(UUIDPrimaryKeyModel, TimestampedModel):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField(max_length=2000)

    class Meta:
        ordering = ["created_at", "id"]


class UserBlock(TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_created")
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_received")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "blocked"], name="unique_user_block")]


class RateBucket(models.Model):
    key = models.CharField(max_length=64, unique=True)
    window_started_at = models.DateTimeField(default=timezone.now)
    count = models.PositiveIntegerField(default=0)


class WorkerHeartbeat(models.Model):
    name = models.CharField(max_length=32, unique=True)
    last_run_at = models.DateTimeField(default=timezone.now)
    detail = models.JSONField(default=dict)


class ServiceNotice(UUIDPrimaryKeyModel, TimestampedModel):
    title = models.CharField(max_length=160)
    body = models.TextField(max_length=2000)
    severity = models.CharField(max_length=12, choices=[("information", "Information"), ("maintenance", "Maintenance"), ("incident", "Incident")], default="information")
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class OperationAudit(ImmutableModelMixin, UUIDPrimaryKeyModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=48)
    target_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict)
    objects = ImmutableQuerySet.as_manager()


class ServiceMetric(models.Model):
    day = models.DateField()
    route_group = models.CharField(max_length=24)
    requests = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    total_ms = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["day", "route_group"], name="unique_service_daily_metric")]


class ContactRequest(UUIDPrimaryKeyModel, TimestampedModel):
    email = models.EmailField()
    category = models.CharField(max_length=20, choices=[("help", "Help"), ("appeal", "Appeal"), ("privacy", "Privacy")])
    subject = models.CharField(max_length=160)
    description = models.TextField(max_length=4000)
    verification_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    response = models.TextField(max_length=2000, blank=True)


class ProjectPost(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=120)
    body = models.TextField(max_length=6000)
    kind = models.CharField(max_length=12, choices=[("discussion", "Discussion"), ("announcement", "Announcement")], default="discussion")
    pinned = models.BooleanField(default=False)
    mention_ids = models.JSONField(default=list, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-pinned", "-created_at", "-id"]


class PostReply(UUIDPrimaryKeyModel, TimestampedModel):
    post = models.ForeignKey(ProjectPost, on_delete=models.PROTECT, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField(max_length=2000)
    mention_ids = models.JSONField(default=list, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]


class PostReport(UUIDPrimaryKeyModel, TimestampedModel):
    post = models.ForeignKey(ProjectPost, on_delete=models.PROTECT)
    reply = models.ForeignKey(PostReply, null=True, blank=True, on_delete=models.PROTECT)
    ticket = models.OneToOneField(SupportTicket, on_delete=models.PROTECT)
    snapshot = models.TextField(max_length=2200)
