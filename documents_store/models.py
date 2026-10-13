from django.conf import settings
from django.db import models

from config.models import UUIDPrimaryKeyModel, TimestampedModel


class ProjectDocument(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="documents")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="project_documents")
    title = models.CharField(max_length=150)
    folder = models.CharField(max_length=80, blank=True)
    tags = models.JSONField(default=list, blank=True)
    pinned = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
    removed_at = models.DateTimeField(null=True, blank=True)
    restoration_blocked = models.BooleanField(default=False)

    class Meta:
        ordering = ("-pinned", "-updated_at", "id")
        indexes = [models.Index(fields=("project", "removed_at"), name="document_project_active_idx")]


class DocumentVersion(UUIDPrimaryKeyModel):
    document = models.ForeignKey(ProjectDocument, on_delete=models.CASCADE, related_name="versions")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    filename = models.CharField(max_length=160)
    content_type = models.CharField(max_length=120)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=100, unique=True)
    scan_status = models.CharField(max_length=24, choices=[("clean", "Clean"), ("local_unscanned", "Local unscanned")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-number",)
        constraints = [models.UniqueConstraint(fields=("document", "number"), name="unique_document_version_number")]


class DocumentTag(UUIDPrimaryKeyModel):
    document = models.ForeignKey(ProjectDocument, on_delete=models.CASCADE, related_name="tag_index")
    tag = models.CharField(max_length=32, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("document", "tag"), name="unique_document_tag")]


class UploadDailyUsage(UUIDPrimaryKeyModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    day = models.DateField()
    bytes = models.PositiveBigIntegerField(default=0)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "day"), name="unique_file_user_day")]
