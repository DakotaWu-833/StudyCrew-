from django.conf import settings
from django.db import models
from config.models import UUIDPrimaryKeyModel


class TaskSyncReceipt(UUIDPrimaryKeyModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    task = models.ForeignKey("tasks.Task", on_delete=models.PROTECT)
    mutation_id = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "mutation_id"], name="unique_offline_user_mutation")]
