"""Private project conversation and a durable reconnect cursor."""
from django.conf import settings
from django.db import models
from config.models import TimestampedModel, UUIDPrimaryKeyModel


class ChatMessage(UUIDPrimaryKeyModel, TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    client_nonce = models.UUIDField()
    body = models.TextField(max_length=2000)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["author", "client_nonce"], name="unique_chat_author_nonce")]
        indexes = [models.Index(fields=["project", "created_at"], name="chat_project_created_idx")]


class ChatEvent(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    message = models.ForeignKey(ChatMessage, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["project", "id"], name="chat_project_cursor_idx")]


class ChatPresence(TimestampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "user"], name="unique_chat_project_user")]
