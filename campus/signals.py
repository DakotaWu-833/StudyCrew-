"""Keep the existing task completion route consistent with its academic extensions."""

from django.db.models.signals import pre_save
from django.dispatch import receiver

from tasks.models import Task
from .services import validate_task_completion


@receiver(pre_save, sender=Task)
def validate_academic_completion(sender, instance, **kwargs):
    if instance.status != "done" or not instance.pk:
        return
    previous = Task.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    if previous == "done":
        return
    validate_task_completion(instance)
