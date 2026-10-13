"""Transactional task use cases shared by the REST and HTML layers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from projects.models import ProjectMembership
from tasks.models import ContentReport, Task, TaskAssignment, TaskComment
from tasks.policies import (
    active_membership,
    require_comment_change_permission,
    require_task_transition_permission,
)


def _activity_services():
    from activity import services

    return services


def _require_writable_project(project) -> None:
    if project.archived_at is not None:
        raise ValidationError("Archived projects are read-only.")


def _require_writable_task(task: Task) -> None:
    _require_writable_project(task.project)
    if task.archived_at is not None:
        raise ValidationError("Archived tasks cannot be changed.")


def _lock_actor(actor):
    from accounts.models import User
    current = User.objects.select_for_update().filter(pk=actor.pk, is_active=True, closed_at__isnull=True).first()
    if current is None:
        raise PermissionDenied("An active account is required.")
    return current


def _lock_task(task, actor):
    from projects.models import Project
    actor = _lock_actor(actor)
    Project.objects.select_for_update().get(pk=task.project_id)
    task.refresh_from_db(from_queryset=Task.objects.select_for_update().select_related("project"))
    return task, actor


@transaction.atomic
def create_task(*, project, actor, data: Mapping) -> Task:
    from projects.models import Project
    actor = _lock_actor(actor)
    project = Project.objects.select_for_update().get(pk=project.pk)
    active_membership(project=project, user=actor)
    _require_writable_project(project)
    task = Task(
        project=project,
        created_by=actor,
        title=data.get("title", ""),
        description=data.get("description", ""),
        priority=data.get("priority", Task.Priority.MEDIUM),
        due_at=data.get("due_at"),
    )
    task.full_clean()
    task.save()
    _activity_services().record_event(
        project=project,
        actor=actor,
        event_type="task_created",
        target_type="task",
        target_id=task.id,
        metadata={"title": task.title},
    )
    return task


@transaction.atomic
def update_task(*, task: Task, actor, data: Mapping) -> Task:
    task, actor = _lock_task(task, actor)
    active_membership(project=task.project, user=actor)
    _require_writable_task(task)
    if "expected_updated_at" in data and data["expected_updated_at"] != task.updated_at:
        raise ValidationError("This task changed while you were editing. Reload it before saving; your local draft is retained.")
    if data.get("due_at"):
        from campus.models import TaskPlan
        official = TaskPlan.objects.filter(task=task).values_list("official_due_at", flat=True).first()
        if official and data["due_at"] > official:
            raise ValidationError({"due_at": "The internal deadline cannot be after the official deadline."})
    allowed = {"title", "description", "priority", "due_at"}
    changed: list[str] = []
    for field in allowed:
        if field in data and getattr(task, field) != data[field]:
            setattr(task, field, data[field])
            changed.append(field)
    if not changed:
        return task
    task.full_clean()
    task.save(update_fields=[*changed, "updated_at"])
    _activity_services().record_event(
        project=task.project,
        actor=actor,
        event_type="task_updated",
        target_type="task",
        target_id=task.id,
        metadata={"changed_fields": sorted(changed)},
    )
    return task


@transaction.atomic
def archive_task(*, task: Task, actor) -> Task:
    task, actor = _lock_task(task, actor)
    active_membership(project=task.project, user=actor)
    _require_writable_project(task.project)
    if task.archived_at:
        return task
    task.archived_at = timezone.now()
    task.save(update_fields=["archived_at", "updated_at"])
    _activity_services().record_event(
        project=task.project,
        actor=actor,
        event_type="task_archived",
        target_type="task",
        target_id=task.id,
    )
    return task


@transaction.atomic
def replace_assignees(*, task: Task, actor, assignee_ids: Iterable) -> Task:
    task, actor = _lock_task(task, actor)
    active_membership(project=task.project, user=actor)
    _require_writable_task(task)
    requested_ids = set(assignee_ids)
    eligible_ids = set(
        ProjectMembership.objects.filter(
            project=task.project,
            removed_at__isnull=True,
            user_id__in=requested_ids,
        ).values_list("user_id", flat=True)
    )
    if requested_ids != eligible_ids:
        raise ValidationError({"assignees": "Every assignee must be a current project member."})

    existing_ids = set(task.assignments.values_list("user_id", flat=True))
    added_ids = requested_ids - existing_ids
    removed_ids = existing_ids - requested_ids
    if not added_ids and not removed_ids:
        return task

    task.assignments.filter(user_id__in=removed_ids).delete()
    TaskAssignment.objects.bulk_create(
        [TaskAssignment(task=task, user_id=user_id, assigned_by=actor) for user_id in added_ids]
    )
    task.save(update_fields=["updated_at"])
    event = _activity_services().record_event(
        project=task.project,
        actor=actor,
        event_type="task_assignees_changed",
        target_type="task",
        target_id=task.id,
        metadata={"added_count": len(added_ids), "removed_count": len(removed_ids)},
    )
    users_by_id = {
        member.user_id: member.user
        for member in ProjectMembership.objects.filter(
            project=task.project,
            user_id__in=added_ids,
            removed_at__isnull=True,
        ).select_related("user")
    }
    for user_id in added_ids:
        recipient = users_by_id[user_id]
        if recipient.id != actor.id:
            _activity_services().create_notification(
                event=event,
                recipient=recipient,
                notification_type="task_assignment",
                target_url=f"/app/projects/{task.project_id}/tasks/{task.id}/",
            )
    return task


@transaction.atomic
def transition_task(*, task: Task, actor, status: str, blocker_note: str = "") -> Task:
    task, actor = _lock_task(task, actor)
    require_task_transition_permission(task=task, user=actor)
    _require_writable_task(task)
    if status not in Task.Status.values:
        raise ValidationError({"status": "Unknown task status."})
    blocker_note = blocker_note.strip()
    if status == Task.Status.BLOCKED and not 3 <= len(blocker_note) <= 500:
        raise ValidationError({"blocker_note": "A blocker note of 3 to 500 characters is required."})
    if task.status == status and (status != Task.Status.BLOCKED or task.blocker_note == blocker_note):
        return task

    if status == Task.Status.DONE:
        from campus.services import validate_task_completion
        validate_task_completion(task)
    previous_status = task.status
    task.status = status
    task.blocker_note = blocker_note if status == Task.Status.BLOCKED else ""
    task.completed_at = timezone.now() if status == Task.Status.DONE else None
    task.full_clean()
    task.save(update_fields=["status", "blocker_note", "completed_at", "updated_at"])
    _activity_services().record_event(
        project=task.project,
        actor=actor,
        event_type="task_status_changed",
        target_type="task",
        target_id=task.id,
        metadata={"from": previous_status, "to": status},
    )
    return task


def _validate_mentions(*, task: Task, mentioned_user_ids: Iterable) -> list:
    requested = set(mentioned_user_ids)
    memberships = list(
        ProjectMembership.objects.filter(
            project=task.project,
            user_id__in=requested,
            removed_at__isnull=True,
        ).select_related("user")
    )
    if {membership.user_id for membership in memberships} != requested:
        raise ValidationError({"mentions": "Mentioned users must be current project members."})
    return [membership.user for membership in memberships]


@transaction.atomic
def create_comment(*, task: Task, actor, body: str, mentioned_user_ids: Iterable = ()) -> TaskComment:
    active_membership(project=task.project, user=actor)
    _require_writable_task(task)
    recipients = _validate_mentions(task=task, mentioned_user_ids=mentioned_user_ids)
    comment = TaskComment(task=task, author=actor, body=body)
    comment.full_clean()
    comment.save()
    event = _activity_services().record_event(
        project=task.project,
        actor=actor,
        event_type="comment_created",
        target_type="comment",
        target_id=comment.id,
    )
    for recipient in recipients:
        if recipient.id != actor.id:
            _activity_services().create_notification(
                event=event,
                recipient=recipient,
                notification_type="comment_mention",
                target_url=f"/app/projects/{task.project_id}/tasks/{task.id}/",
            )
    return comment


@transaction.atomic
def update_comment(*, comment: TaskComment, actor, body: str) -> TaskComment:
    moderated = require_comment_change_permission(comment=comment, user=actor)
    _require_writable_task(comment.task)
    if comment.deleted_at:
        raise ValidationError("Deleted comments cannot be edited.")
    comment.body = body
    comment.edited_at = timezone.now()
    if moderated:
        comment.moderated_by = actor
    comment.full_clean()
    comment.save(update_fields=["body", "edited_at", "moderated_by"])
    _activity_services().record_event(
        project=comment.task.project,
        actor=actor,
        event_type="comment_moderated" if moderated else "comment_edited",
        target_type="comment",
        target_id=comment.id,
    )
    return comment


@transaction.atomic
def delete_comment(*, comment: TaskComment, actor) -> TaskComment:
    moderated = require_comment_change_permission(comment=comment, user=actor)
    _require_writable_task(comment.task)
    if comment.deleted_at:
        return comment
    comment.deleted_at = timezone.now()
    if moderated:
        comment.moderated_by = actor
    comment.save(update_fields=["deleted_at", "moderated_by"])
    _activity_services().record_event(
        project=comment.task.project,
        actor=actor,
        event_type="comment_moderated" if moderated else "comment_deleted",
        target_type="comment",
        target_id=comment.id,
    )
    return comment


@transaction.atomic
def report_comment(*, comment: TaskComment, actor, reason: str, details: str = "") -> ContentReport:
    active_membership(project=comment.task.project, user=actor)
    _require_writable_task(comment.task)
    if comment.deleted_at:
        raise ValidationError("Deleted comments cannot be reported.")
    report = ContentReport(comment=comment, reporter=actor, reason=reason, details=details)
    report.full_clean()
    try:
        report.save()
    except IntegrityError as exc:
        raise ValidationError("You already have a pending report for this comment.") from exc
    _activity_services().record_event(
        project=comment.task.project,
        actor=actor,
        event_type="comment_reported",
        target_type="comment",
        target_id=comment.id,
    )
    return report


@transaction.atomic
def resolve_report(
    *, report: ContentReport, actor, outcome: str, resolution_note: str, remove_comment: bool = False
) -> ContentReport:
    if not actor.has_perm("tasks.moderate_reports"):
        raise PermissionDenied("Site moderation permission is required.")
    if report.status != ContentReport.Status.PENDING:
        raise ValidationError("This report has already been reviewed.")
    if outcome not in {ContentReport.Status.RESOLVED, ContentReport.Status.DISMISSED}:
        raise ValidationError({"outcome": "Choose resolved or dismissed."})
    report.status = outcome
    report.resolution_note = resolution_note.strip()
    report.resolved_by = actor
    report.resolved_at = timezone.now()
    report.full_clean()
    report.save(
        update_fields=("status", "resolution_note", "resolved_by", "resolved_at")
    )
    if remove_comment and not report.comment.deleted_at:
        report.comment.deleted_at = timezone.now()
        report.comment.moderated_by = actor
        report.comment.save(update_fields=("deleted_at", "moderated_by"))
    activity = _activity_services()
    if hasattr(activity, "record_site_audit"):
        activity.record_site_audit(
            actor=actor,
            action="content_report_resolved",
            target_type="content_report",
            target_id=report.id,
            metadata={"outcome": outcome, "content_removed": remove_comment},
        )
    return report
