"""Private vector cache and receipts for explicitly approved task creation."""

from django.conf import settings
from django.db import models

from config.models import UUIDPrimaryKeyModel


class EmbeddingCache(UUIDPrimaryKeyModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="embedding_cache")
    model = models.CharField(max_length=160)
    content_sha256 = models.CharField(max_length=64)
    vector = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("project", "model", "content_sha256"), name="knowledge_embed_unique")]


class AssistantTaskReceipt(UUIDPrimaryKeyModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_digest = models.CharField(max_length=64)
    payload_sha256 = models.CharField(max_length=64)
    task = models.ForeignKey("tasks.Task", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "project", "token_digest"), name="knowledge_receipt_unique")]
