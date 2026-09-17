"""Projects, membership, and invitation persistence models."""

from __future__ import annotations

import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator, validate_email
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from config.models import TimestampedModel, UUIDPrimaryKeyModel


TOKEN_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def normalise_email(value: str) -> str:
    """Return the canonical representation used by invitations and users."""

    return value.strip().lower()


class ProjectQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived_at__isnull=True)

    def for_user(self, user):
        if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return self.none()
        return self.filter(
            memberships__user=user,
            memberships__removed_at__isnull=True,
        ).distinct()


class Project(UUIDPrimaryKeyModel, TimestampedModel):
    """A private collaboration space owned through an active membership."""

    name = models.CharField(max_length=100, validators=[MinLengthValidator(3)])
    description = models.TextField(max_length=2000, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_projects",
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = ("name", "id")
        indexes = [
            models.Index(fields=("created_by", "created_at"), name="project_creator_time_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class ProjectMembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(removed_at__isnull=True)

    def owners(self):
        return self.active().filter(role=ProjectMembership.Role.OWNER)


class ProjectMembership(UUIDPrimaryKeyModel):
    """A user's role in a project, retained after access is removed."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        FACILITATOR = "facilitator", "Facilitator"
        MEMBER = "member", "Member"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="project_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(default=timezone.now, editable=False)
    removed_at = models.DateTimeField(null=True, blank=True)

    objects = ProjectMembershipQuerySet.as_manager()

    class Meta:
        ordering = ("joined_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "user"),
                name="unique_project_membership",
            ),
            models.UniqueConstraint(
                fields=("project",),
                condition=models.Q(role="owner", removed_at__isnull=True),
                name="unique_active_project_owner",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=("owner", "facilitator", "member")),
                name="valid_project_membership_role",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "removed_at"), name="membership_user_active_idx"),
            models.Index(fields=("project", "removed_at"), name="membership_project_active_idx"),
        ]

    @property
    def is_active(self) -> bool:
        return self.removed_at is None

    def __str__(self) -> str:
        return f"{self.user} in {self.project} ({self.role})"


class ProjectInvitationQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(status=ProjectInvitation.Status.PENDING)

    def usable(self, *, at=None):
        at = at or timezone.now()
        return self.pending().filter(expires_at__gt=at)


class ProjectInvitation(UUIDPrimaryKeyModel, TimestampedModel):
    """A single-use invitation; only a digest of the bearer token is stored."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    invited_email = models.EmailField(max_length=254)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_project_invitations",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)

    objects = ProjectInvitationQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "id")
        constraints = [
            models.UniqueConstraint(
                Lower("invited_email"),
                "project",
                condition=models.Q(status="pending"),
                name="unique_pending_project_invite",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="pending", responded_at__isnull=True)
                    | models.Q(
                        status__in=("accepted", "declined", "cancelled", "expired"),
                        responded_at__isnull=False,
                    )
                ),
                name="invitation_response_time_matches_status",
            ),
        ]
        indexes = [
            models.Index(fields=("invited_email", "status"), name="invite_email_status_idx"),
            models.Index(fields=("project", "status"), name="invite_project_status_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        self.invited_email = normalise_email(self.invited_email)
        validate_email(self.invited_email)
        if not TOKEN_HASH_PATTERN.fullmatch(self.token_hash or ""):
            raise ValidationError({"token_hash": "The invitation token digest is invalid."})
        if self.status == self.Status.PENDING and self.expires_at <= timezone.now():
            raise ValidationError({"expires_at": "A pending invitation must expire in the future."})

    def save(self, *args, **kwargs):
        self.invited_email = normalise_email(self.invited_email)
        return super().save(*args, **kwargs)

    @property
    def has_expired(self) -> bool:
        return self.status == self.Status.EXPIRED or (
            self.status == self.Status.PENDING and self.expires_at <= timezone.now()
        )

    @classmethod
    def default_expiry(cls):
        return timezone.now() + timedelta(days=7)

    def __str__(self) -> str:
        return f"{self.invited_email} invited to {self.project}"
