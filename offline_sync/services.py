"""Atomic version-checked offline edits; retries never apply twice."""
import hashlib
import json
from datetime import timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from accounts.models import User
from projects.models import Project
from projects.policies import require_project_member
from tasks.models import Task
from tasks.services import update_task, transition_task
from .models import TaskSyncReceipt


class EditConflict(Exception):
    pass


@transaction.atomic
def synchronize(*, actor, task_id, mutation_id, expected_updated_at, changes):
    user = User.objects.select_for_update().filter(pk=actor.pk, is_active=True, closed_at__isnull=True).first()
    if user is None:
        raise PermissionDenied("An active account is required.")
    project_id = Task.objects.filter(pk=task_id).values_list("project_id", flat=True).first()
    if project_id is None:
        raise Http404
    project = Project.objects.select_for_update().get(pk=project_id)
    require_project_member(user, project)
    task = Task.objects.select_for_update().select_related("project", "created_by__profile").get(pk=task_id)
    if project.archived_at or task.archived_at:
        raise ValidationError("Archived projects and tasks are read-only.")
    digest = hashlib.sha256(json.dumps({"task": str(task_id), "base": expected_updated_at, "changes": changes}, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()
    receipt = TaskSyncReceipt.objects.filter(user=user, mutation_id=mutation_id).first()
    if receipt:
        if receipt.task_id != task.pk or receipt.payload_hash != digest:
            raise ValidationError("This sync identifier was already used for a different edit.")
        return task, True
    if task.updated_at != expected_updated_at:
        raise EditConflict()
    detail_changes = {key: value for key, value in changes.items() if key not in {"status", "blocker_note"}}
    if detail_changes:
        task = update_task(task=task, actor=user, data={**detail_changes, "expected_updated_at": expected_updated_at})
    if "status" in changes:
        task = transition_task(task=task, actor=user, status=changes["status"], blocker_note=changes.get("blocker_note", task.blocker_note))
    TaskSyncReceipt.objects.create(user=user, task=task, mutation_id=mutation_id, payload_hash=digest)
    return task, False


def cleanup_receipts():
    return TaskSyncReceipt.objects.filter(applied_at__lt=timezone.now() - timedelta(days=7)).delete()[0]


def personal_data(user):
    return list(TaskSyncReceipt.objects.filter(user=user).values("task_id", "mutation_id", "applied_at"))


def close_user(user):
    TaskSyncReceipt.objects.filter(user=user).delete()
