"""Preview first, then atomically create real tasks without overwriting imports."""
import csv
import io
from datetime import datetime, timedelta
from math import ceil
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth import get_user_model
from campus.models import TaskPlan
from campus.policies import project_access
from projects.models import Project
from projects.policies import require_project_member
from tasks.models import Task
from tasks.services import create_task
from .models import ImportBatch, ImportPreview, ImportedAssignment
from .parser import digest, parse


def duplicates(project, source, namespace, rows):
    known = dict(ImportedAssignment.objects.filter(project=project, source=source, source_namespace=namespace,
        source_id__in=[row["source_id"] for row in rows]).values_list("source_id", "task_id"))
    return [{**row, "action": "skip" if row["source_id"] in known else "create", "existing_task": str(known[row["source_id"]]) if row["source_id"] in known else None} for row in rows]


def batch_row(batch):
    return {"id": str(batch.id), "source": batch.source, "source_namespace": batch.source_namespace,
        "timezone_name": batch.timezone_name, "created_at": batch.created_at,
        "imported_count": batch.imported_count, "skipped_count": batch.skipped_count}


@transaction.atomic
def preview(*, actor, project_id, content, source, source_namespace, timezone_name=None):
    actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
    # Match account-closure lock ordering and serialise the per-user preview cap.
    get_object_or_404(Project.objects.select_for_update(), pk=project_id)
    project = project_access(user=actor, project_id=project_id, manager=True, write=True)
    zone = timezone_name or getattr(getattr(actor, "profile", None), "time_zone", "Australia/Sydney")
    rows, ignored = parse(content, source=source, source_namespace=source_namespace, timezone_name=zone)
    rows = duplicates(project, source, source_namespace, rows)
    valid = not any(row["errors"] for row in rows)
    result = {"valid": valid, "preview_id": None, "expires_at": None, "timezone_name": zone,
        "source": source, "source_namespace": source_namespace, "rows": rows, "ignored_columns": ignored,
        "create_count": sum(row["action"] == "create" for row in rows), "skip_count": sum(row["action"] == "skip" for row in rows)}
    if not valid:
        return result
    if ImportPreview.objects.filter(actor=actor, created_at__gte=timezone.now() - timedelta(hours=1)).count() >= 20:
        raise ValidationError("Preview limit reached. Try again in an hour.")
    identity = digest({"source": source, "namespace": source_namespace, "rows": [{key: value for key, value in row.items() if key not in ("action", "existing_task", "errors")} for row in rows]})
    item = ImportPreview.objects.create(project=project, actor=actor, source=source,
        source_namespace=source_namespace, timezone_name=zone, content_hash=identity, rows=rows,
        expires_at=timezone.now() + timedelta(minutes=30))
    result.update(preview_id=str(item.id), expires_at=item.expires_at)
    return result


@transaction.atomic
def confirm(*, actor, project_id, preview_id, confirmed):
    if confirmed is not True:
        raise ValidationError({"confirmed": "Explicitly confirm the displayed preview."})
    actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
    # Lock the parent without a DISTINCT membership join (PostgreSQL rejects
    # SELECT FOR UPDATE with DISTINCT); authorization is rechecked below.
    project = get_object_or_404(Project.objects.select_for_update(), pk=project_id)
    project_access(user=actor, project_id=project_id, manager=True, write=True)
    item = get_object_or_404(ImportPreview.objects.select_for_update(), pk=preview_id, project=project, actor=actor)
    if item.batch_id:
        return {"batch": batch_row(item.batch), "replayed": True}
    if item.expires_at <= timezone.now():
        raise ValidationError("This preview expired. Upload the file again before importing.")
    prior = ImportBatch.objects.filter(project=project, content_hash=item.content_hash).first()
    if prior:
        item.batch = prior
        item.save(update_fields=("batch", "updated_at"))
        return {"batch": batch_row(prior), "replayed": True}
    rows = duplicates(project, item.source, item.source_namespace, item.rows)
    if any(row["action"] != previous["action"] or row["existing_task"] != previous["existing_task"] for row, previous in zip(rows, item.rows)):
        raise ValidationError("Existing assignments changed since this preview. Upload the file again to see the current duplicates.")
    if any(row["errors"] for row in rows):
        raise ValidationError("The entire file must be valid before importing.")
    batch = ImportBatch.objects.create(project=project, actor=actor, source=item.source,
        source_namespace=item.source_namespace, timezone_name=item.timezone_name, content_hash=item.content_hash,
        imported_count=sum(row["action"] == "create" for row in rows), skipped_count=sum(row["action"] == "skip" for row in rows))
    for row in rows:
        if row["action"] == "skip":
            row["task_id"] = row["existing_task"]
            continue
        due = datetime.fromisoformat(row["official_due_at"]) if row["official_due_at"] else None
        task = create_task(project=project, actor=actor, data={"title": row["title"], "description": row["description"], "priority": row["priority"], "due_at": due})
        TaskPlan.objects.create(task=task, official_due_at=due)
        ImportedAssignment.objects.create(project=project, batch=batch, task=task, source=item.source,
            source_namespace=item.source_namespace, source_id=row["source_id"], source_row=row["row"])
        row["task_id"] = str(task.id)
    batch.rows = rows
    batch.save(update_fields=("rows", "updated_at"))
    item.batch = batch
    item.save(update_fields=("batch", "updated_at"))
    return {"batch": batch_row(batch), "replayed": False}


def overview(*, actor, project_id, page=1):
    project = project_access(user=actor, project_id=project_id)
    membership = require_project_member(actor, project)
    try:
        page = int(page)
    except (TypeError, ValueError):
        raise ValidationError("Choose a valid page.") from None
    batches = ImportBatch.objects.filter(project=project)
    total = batches.count()
    pages = max(1, ceil(total / 20))
    if not 1 <= page <= pages:
        raise ValidationError("Choose a valid page.")
    return {"project": {"id": str(project.id), "name": project.name, "archived_at": project.archived_at,
        "can_import": membership.role in ("owner", "facilitator") and project.archived_at is None},
        "timezone_name": getattr(getattr(actor, "profile", None), "time_zone", "Australia/Sydney"),
        "batches": [batch_row(batch) for batch in batches[(page - 1) * 20:page * 20]], "page": page, "pages": pages, "total": total}


def csv_cell(value):
    text = str(value if value is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) or text.startswith(("\t", "\r", "\n")) else text


def csv_export(*, actor, project_id, batch_id=None):
    project = project_access(user=actor, project_id=project_id)
    query = Task.objects.filter(project=project).select_related("academic_plan", "learning_import")
    if batch_id is not None:
        batch = get_object_or_404(ImportBatch, pk=batch_id, project=project)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("source_id", "title", "description", "official_due_at", "priority", "action", "task_id", "source_row"))
        for row in batch.rows:
            writer.writerow([csv_cell(row.get(key, "")) for key in ("source_id", "title", "description", "official_due_at", "priority", "action", "task_id", "row")])
        return output.getvalue()
    if query.count() > 10000:
        raise ValidationError("This project has more than 10,000 tasks. Export individual import batches instead.")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("source_id", "title", "description", "official_due_at", "internal_due_at", "priority", "status", "task_id", "archived"))
    for task in query.order_by("created_at", "id").iterator():
        plan = getattr(task, "academic_plan", None)
        imported = getattr(task, "learning_import", None)
        official = plan.official_due_at if plan else None
        writer.writerow([csv_cell(value) for value in (imported.source_id if imported else str(task.id), task.title, task.description,
            official.isoformat() if official else "", task.due_at.isoformat() if task.due_at else "", task.priority, task.status, str(task.id), bool(task.archived_at))])
    return output.getvalue()
