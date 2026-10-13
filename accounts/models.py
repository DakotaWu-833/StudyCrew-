"""Identity, profile, throttling, and one-time-code persistence.

The authentication workflow deliberately uses explicit services rather than
signals.  This keeps user/profile creation and security state changes visible,
transactional, and straightforward to test.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import MinLengthValidator
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils import timezone

from accounts.validators import validate_iana_timezone, validate_languages_list, validate_skills_list


class UserManager(BaseUserManager["User"]):
    """Create users whose normalised email address is their login identifier."""

    use_in_migrations = True

    @transaction.atomic
    def _create_user(self, email: str, password: str, **extra_fields) -> "User":
        if not email:
            raise ValueError("An email address is required.")
        if not password:
            raise ValueError("A password is required.")

        display_name = str(extra_fields.pop("display_name", "")).strip()
        email = self.normalize_email(email).strip().lower()
        is_active = bool(extra_fields.setdefault("is_active", True))
        if is_active and "email_verified_at" not in extra_fields:
            extra_fields["email_verified_at"] = timezone.now()

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.full_clean(exclude={"password"}, validate_unique=False)
        user.save(using=self._db)

        if not display_name:
            display_name = email.partition("@")[0].strip()[:80]
            if len(display_name) < 2:
                display_name = "Member"
        profile = Profile(user=user, display_name=display_name)
        profile.full_clean()
        profile.save(force_insert=True)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password or "", **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        if extra_fields.get("is_active") is not True:
            raise ValueError("A superuser must have is_active=True.")
        return self._create_user(email, password or "", **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """A minimal Django user identified by a case-normalised email address."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ("email",)
        permissions = [
            ("manage_user_status", "Can suspend and restore user accounts"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")),
                name="accounts_user_email_lowercase",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.email = type(self).objects.normalize_email(self.email).strip().lower()

    def save(self, *args, **kwargs) -> None:
        self.email = type(self).objects.normalize_email(self.email).strip().lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email


class Profile(models.Model):
    """Editable, non-authentication attributes for exactly one user."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="profile",
    )
    display_name = models.CharField(max_length=80, validators=[MinLengthValidator(2)])
    course_code = models.CharField(max_length=20, blank=True)
    time_zone = models.CharField(
        max_length=64,
        default="Australia/Sydney",
        validators=[validate_iana_timezone],
    )
    biography = models.CharField(max_length=500, blank=True)
    major = models.CharField(max_length=120, blank=True)
    skills = models.JSONField(default=list, blank=True, validators=[validate_skills_list])
    communication_languages = models.JSONField(default=list, blank=True, validators=[validate_languages_list])
    collaboration_preference = models.CharField(max_length=16, blank=True, choices=[
        ("", "No preference"), ("online", "Online"), ("in_person", "In person"), ("hybrid", "Online and in person"),
    ])
    avatar_url = models.URLField(max_length=2048, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_name", "user_id")

    def __str__(self) -> str:
        return self.display_name


class PendingEmailChange(models.Model):
    """One short-lived verification request for a new sign-in address."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="pending_email_change")
    new_email = models.EmailField(max_length=254)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    last_sent_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Pending email change for {self.user_id}"


class LoginThrottle(models.Model):
    """Persistent failure counters keyed only by secret-derived digests."""

    class KeyKind(models.TextChoices):
        ACCOUNT = "account", "Account"
        IP_ADDRESS = "ip", "IP address"

    kind = models.CharField(max_length=16, choices=KeyKind.choices)
    key_digest = models.CharField(max_length=64)
    failure_count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(default=timezone.now)
    last_failed_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("kind", "key_digest"), name="accounts_unique_throttle_key"),
        ]
        indexes = [models.Index(fields=("kind", "key_digest"), name="accounts_throttle_lookup")]

    def __str__(self) -> str:
        return f"{self.kind}:{self.key_digest[:10]}…"


class EmailOTPChallenge(models.Model):
    """A short-lived, single-use email verification or login challenge."""

    class Purpose(models.TextChoices):
        REGISTRATION = "registration", "Verify registration"
        LOGIN = "login", "Verify sign-in"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otp_challenges")
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField()
    send_count = models.PositiveSmallIntegerField(default=1)
    last_sent_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "purpose", "created_at"),
                name="accounts_otp_user_purpose",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1),
                name="accounts_otp_positive_max_attempts",
            ),
            models.CheckConstraint(
                condition=models.Q(send_count__gte=1),
                name="accounts_otp_positive_send_count",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__lte=models.F("max_attempts")),
                name="accounts_otp_attempt_limit",
            ),
        ]

    @property
    def is_available(self) -> bool:
        now = timezone.now()
        return (
            self.consumed_at is None
            and self.attempt_count < self.max_attempts
            and self.expires_at > now
        )

    def __str__(self) -> str:
        return f"{self.get_purpose_display()} for {self.user_id}"


class RecoveryEmail(models.Model):
    """A separately verified fallback address, never a substitute for a password."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, related_name="recovery_email")
    email = models.EmailField(max_length=254)
    verified_at = models.DateTimeField()


class AccountSecurityToken(models.Model):
    """Only digests of high-entropy single-use security links are persisted."""

    class Purpose(models.TextChoices):
        PASSWORD_RESET = "password_reset", "Password reset"
        RECOVERY_EMAIL = "recovery_email", "Verify recovery address"
        EMAIL_RECOVERY = "email_recovery", "Recover unavailable sign-in address"
        RECOVERY_NEW_EMAIL = "recovery_new", "Verify recovered sign-in address"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="security_tokens")
    purpose = models.CharField(max_length=24, choices=Purpose.choices)
    token_digest = models.CharField(max_length=64, unique=True)
    auth_digest = models.CharField(max_length=64)
    destination = models.EmailField(max_length=254)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=("user", "purpose", "created_at"), name="account_security_token_idx")]


class AccountSecurityThrottle(models.Model):
    """Persistent, secret-keyed fixed-window counters for security actions."""

    key_digest = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(default=timezone.now)


class AccountDeviceSession(models.Model):
    """User-visible devices map opaque IDs to private server-side sessions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_sessions")
    session_key = models.CharField(max_length=40, unique=True)
    browser = models.CharField(max_length=120, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ("-last_seen_at",)
