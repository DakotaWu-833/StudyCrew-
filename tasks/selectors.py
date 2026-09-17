"""Reusable, membership-scoped task reads."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet
from django.utils import timezone

from tasks.models import Task, TaskComment
from tasks.policies import active_membership


def task_for_member(*, task_id, user, include_archived: bool = False) -> Task:
    try:
        task = Task.objects.select_related("project", "created_by").prefetch_related(
            "assignments__user"
        ).get(pk=task_id)
    except Task.DoesNotExist:
        raise
    active_membership(project=task.project, user=user)
    if task.archived_at and not include_archived:
        raise Task.DoesNotExist
    return task


def comment_for_member(*, comment_id, user, include_deleted: bool = False) -> TaskComment:
    comment = TaskComment.objects.select_related("task__project", "author").get(pk=comment_id)
    active_membership(project=comment.task.project, user=user)
    if comment.deleted_at and not include_deleted:
        raise TaskComment.DoesNotExist
    return comment


def tasks_for_project(
    *,
    project,
    user,
    include_archived: bool = False,
    query: str = "",
    status: str = "",
    priority: str = "",
    assignee_id=None,
    due: str = "",
) -> QuerySet[Task]:
    active_membership(project=project, user=user)
    queryset = Task.objects.filter(project=project).select_related("created_by").prefetch_related(
        "assignments__user"
    )
    if not include_archived:
        queryset = queryset.filter(archived_at__isnull=True)
    if query := query.strip():
        queryset = queryset.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if status:
        if status not in Task.Status.values:
            raise ValidationError({"status": "Unknown task status."})
        queryset = queryset.filter(status=status)
    if priority:
        if priority not in Task.Priority.values:
            raise ValidationError({"priority": "Unknown task priority."})
        queryset = queryset.filter(priority=priority)
    if assignee_id:
        queryset = queryset.filter(assignments__user_id=assignee_id)
    now = timezone.now()
    if due == "overdue":
        queryset = queryset.filter(due_at__lt=now).exclude(status=Task.Status.DONE)
    elif due == "upcoming":
        queryset = queryset.filter(due_at__gte=now)
    elif due == "none":
        queryset = queryset.filter(due_at__isnull=True)
    elif due:
        raise ValidationError({"due": "Unknown due-date filter."})
    return queryset.distinct()
