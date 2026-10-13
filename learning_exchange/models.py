"""Private, explicitly confirmed assignment file imports; no institutional grants."""
from django.conf import settings
from django.db import models
from config.models import TimestampedModel, UUIDPrimaryKeyModel


class ImportBatch(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source = models.CharField(max_length=16)
    source_namespace = models.CharField(max_length=80)
    timezone_name = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    imported_count = models.PositiveSmallIntegerField(default=0)
    skipped_count = models.PositiveSmallIntegerField(default=0)
    rows = models.JSONField(default=list)

    class Meta:
        ordering = ("-created_at", "id")
        constraints = [models.UniqueConstraint(fields=("project", "content_hash"), name="learning_batch_unique")]


class ImportPreview(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source = models.CharField(max_length=16)
    source_namespace = models.CharField(max_length=80)
    timezone_name = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    rows = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    batch = models.ForeignKey(ImportBatch, on_delete=models.SET_NULL, null=True, blank=True)


class ImportedAssignment(UUIDPrimaryKeyModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="assignments")
    task = models.OneToOneField("tasks.Task", on_delete=models.PROTECT, related_name="learning_import")
    source = models.CharField(max_length=16)
    source_namespace = models.CharField(max_length=80)
    source_id = models.CharField(max_length=160)
    source_row = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("project", "source", "source_namespace", "source_id"), name="learning_source_unique")]
