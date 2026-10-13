"""Extensions to the existing project/task domains, without institutional access grants."""

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q

from config.models import TimestampedModel, UUIDPrimaryKeyModel


class Term(UUIDPrimaryKeyModel, TimestampedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    university = models.CharField(max_length=120)
    year = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=80)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-year", "name")
        constraints = [models.UniqueConstraint(fields=("owner", "university", "year", "name"), name="campus_term_unique")]


class Course(UUIDPrimaryKeyModel, TimestampedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    university = models.CharField(max_length=120)
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=120)

    class Meta:
        ordering = ("university", "code")
        constraints = [models.UniqueConstraint(fields=("owner", "university", "code"), name="campus_course_unique")]


class ProjectCourse(UUIDPrimaryKeyModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="academic_links")
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    term = models.ForeignKey(Term, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("project", "course", "term"), name="campus_project_course_unique")]


class Milestone(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=120)
    due_at = models.DateTimeField(null=True, blank=True)
    done = models.BooleanField(default=False)

    class Meta:
        ordering = ("due_at", "created_at")


class TaskPlan(UUIDPrimaryKeyModel, TimestampedModel):
    task = models.OneToOneField("tasks.Task", on_delete=models.CASCADE, related_name="academic_plan")
    parent = models.ForeignKey("tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="academic_children")
    milestone = models.ForeignKey(Milestone, on_delete=models.SET_NULL, null=True, blank=True)
    acceptance = models.TextField(max_length=4000, blank=True)
    tags = models.JSONField(default=list, blank=True)
    estimate_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1000)])
    official_due_at = models.DateTimeField(null=True, blank=True)
    outcome_url = models.URLField(max_length=2048, blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    review_state = models.CharField(max_length=24, default="draft", choices=[(s, s) for s in ("draft", "requested", "approved", "changes_requested")])
    review_note = models.CharField(max_length=1000, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(estimate_hours__isnull=True) | Q(estimate_hours__gte=0, estimate_hours__lte=1000), name="campus_estimate_valid_range")]


class TaskDependency(UUIDPrimaryKeyModel):
    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="academic_dependencies")
    depends_on = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="academic_dependents")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("task", "depends_on"), name="campus_dependency_unique"),
            models.CheckConstraint(condition=~Q(task=models.F("depends_on")), name="campus_dependency_not_self"),
        ]


class ChecklistItem(UUIDPrimaryKeyModel, TimestampedModel):
    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="academic_checklist")
    text = models.CharField(max_length=300)
    checked = models.BooleanField(default=False)

    class Meta:
        ordering = ("created_at", "id")


class TeamAgreement(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.OneToOneField("projects.Project", on_delete=models.CASCADE, related_name="team_agreement")
    body = models.TextField(max_length=6000)
    revision = models.PositiveIntegerField(default=1)


class AgreementConfirmation(UUIDPrimaryKeyModel):
    agreement = models.ForeignKey(TeamAgreement, on_delete=models.CASCADE, related_name="confirmations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    revision = models.PositiveIntegerField()
    confirmed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("agreement", "user"), name="campus_agreement_confirmation_unique")]


class ResourceLink(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="resource_links")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=150)
    url = models.URLField(max_length=2048)
    description = models.CharField(max_length=1000, blank=True)
    tags = models.JSONField(default=list, blank=True)
    pinned = models.BooleanField(default=False)

    class Meta:
        ordering = ("-pinned", "title", "id")


class SubmissionPlan(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.OneToOneField("projects.Project", on_delete=models.CASCADE, related_name="submission_plan")
    official_due_at = models.DateTimeField(null=True, blank=True)
    internal_due_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    receipt_url = models.URLField(max_length=2048, blank=True)
    receipt_reference = models.CharField(max_length=200, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)


class SubmissionItem(UUIDPrimaryKeyModel, TimestampedModel):
    plan = models.ForeignKey(SubmissionPlan, on_delete=models.CASCADE, related_name="items")
    text = models.CharField(max_length=300)
    checked = models.BooleanField(default=False)

    class Meta:
        ordering = ("created_at", "id")


class SubmissionConfirmation(UUIDPrimaryKeyModel):
    plan = models.ForeignKey(SubmissionPlan, on_delete=models.CASCADE, related_name="confirmations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    revision = models.PositiveIntegerField()
    confirmed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("plan", "user"), name="campus_submission_confirmation_unique")]


class JoinLink(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="join_links")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    max_uses = models.PositiveSmallIntegerField(default=10)
    uses = models.PositiveSmallIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)


class JoinRequest(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    link = models.ForeignKey(JoinLink, on_delete=models.CASCADE, related_name="requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=12, default="pending", choices=[(s, s) for s in ("pending", "approved", "rejected")])

    class Meta:
        constraints = [models.UniqueConstraint(fields=("project", "user"), condition=Q(status="pending"), name="campus_join_pending_unique")]


class JoinAttempt(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True)
    window_started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)
