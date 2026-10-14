"""Human-confirmed task creation from short-lived, project-bound proposals."""
import hashlib
import json
import re
import uuid

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import User
from coordination.models import MeetingRecord
from documents_store.models import ProjectDocument
from documents_store.services import _open_version
from django.http import Http404
from projects.models import Project
from tasks.models import Task
from tasks.services import create_task

from .policies import require_project
from .sources import fingerprint

SALT = "studycrew.assistant.reviewed-task.v1"
TOKEN_TTL = 600


def _valid_reference(row):
    if (not isinstance(row, dict) or set(row) != {"citation", "kind", "source_id", "title", "locator", "snapshot"}
        or row.get("kind") not in {"file", "meeting", "task"}
        or not isinstance(row.get("citation"), str) or not re.fullmatch(r"S(?:[1-9]|1[0-2])", row["citation"])
        or not isinstance(row.get("snapshot"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["snapshot"])
        or not isinstance(row.get("title"), str) or len(row["title"]) > 150
        or not isinstance(row.get("locator"), str) or len(row["locator"]) > 60
        or not isinstance(row.get("source_id"), str)):
        return False
    try:
        return str(uuid.UUID(row["source_id"])) == row["source_id"]
    except ValueError:
        return False


def _snapshot(value):
    encoded = json.dumps(value, default=str, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def sign_drafts(user, project_id, drafts, rows):
    current, project = require_project(user, project_id)
    indexed = {row["citation"]: row for row in rows}
    results = []
    for draft in drafts:
        references = []
        for citation in draft["source_citations"]:
            row = indexed.get(citation)
            if not row:
                raise ValidationError("A task draft references unavailable project evidence.")
            references.append({"citation": citation, "kind": row["kind"], "source_id": row["source_id"],
                               "title": row["title"][:150], "locator": row["locator"][:60],
                               "snapshot": _snapshot(row["_fingerprint"])})
        can_create = not bool(project.archived_at)
        token = signing.dumps({"version": 1, "actor": str(current.pk), "project": str(project.pk),
                               "nonce": str(uuid.uuid4()), "sources": references}, salt=SALT, compress=True) if can_create else ""
        results.append({**draft, "approval_token": token, "can_create": can_create})
    return results


def _require_current_sources(project, references):
    from .agent import _task_fingerprint
    for reference in sorted(references, key=lambda row: (row["kind"], row["source_id"])):
        kind, source_id = reference["kind"], reference["source_id"]
        if kind == "file":
            document = ProjectDocument.objects.filter(pk=source_id, project=project, removed_at__isnull=True).first()
            version = document.versions.first() if document else None
            actual = fingerprint(document, version) if version else None
            if actual:
                try:
                    stream, _ = _open_version(version)
                    stream.close()
                except (Http404, OSError):
                    actual = None
        elif kind == "meeting":
            # Minutes edits lock the record independently of the project. Hold
            # that record through task creation; project-owned writers already
            # serialize against the project's lock acquired by approve_task.
            record = MeetingRecord.objects.select_for_update(of=("self",)).filter(pk=source_id, meeting__project=project,
                                                   meeting__archived_at__isnull=True,
                                                   meeting__cancelled_at__isnull=True).select_related("meeting").first()
            actual = fingerprint(record) if record else None
        elif kind == "task":
            task = Task.objects.filter(pk=source_id, project=project, archived_at__isnull=True).first()
            actual = _task_fingerprint(task) if task else None
        else:
            actual = None
        if actual is None or _snapshot(actual) != reference["snapshot"]:
            raise ValidationError("Project sources changed after this draft was prepared. Ask the assistant again.")


@transaction.atomic
def approve_task(user, project_id, approval_token, title, description):
    from .models import AssistantTaskReceipt
    current, project = require_project(user, project_id)
    # Match existing task-service lock order; competing retries serialize here.
    current = User.objects.select_for_update().get(pk=current.pk)
    project = Project.objects.select_for_update().get(pk=project.pk)
    current, project = require_project(current, project.pk)
    if project.archived_at:
        raise ValidationError("Archived projects are read-only.")
    if (not isinstance(approval_token, str) or not approval_token or len(approval_token) > 16384
        or not isinstance(title, str) or not 3 <= len(title.strip()) <= 120
        or not isinstance(description, str) or len(description) > 2000):
        raise ValidationError("Review a valid task title and description before creating the task.")
    title, description = title.strip(), description.strip()
    try:
        payload = signing.loads(approval_token, salt=SALT, max_age=TOKEN_TTL)
    except (signing.BadSignature, ValueError, TypeError, RecursionError):
        raise ValidationError("This task draft expired or could not be verified. Ask the assistant again.") from None
    if (not isinstance(payload, dict) or payload.get("version") != 1 or payload.get("actor") != str(current.pk)
        or payload.get("project") != str(project.pk) or not isinstance(payload.get("sources"), list)
        or not 1 <= len(payload["sources"]) <= 6 or any(not _valid_reference(row) for row in payload["sources"])):
        raise ValidationError("This task draft does not belong to the current user and project.")
    token_digest = hashlib.sha256(approval_token.encode()).hexdigest()
    payload_digest = hashlib.sha256(json.dumps({"title": title, "description": description},
                                               ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    receipt = AssistantTaskReceipt.objects.select_related("task").filter(
        user=current, project=project, token_digest=token_digest).first()
    if receipt:
        if receipt.payload_sha256 != payload_digest:
            raise ValidationError("This draft has already created a task. Open that task to make further changes.")
        return {"task_id": str(receipt.task_id), "title": receipt.task.title, "created": False,
                "task_url": f"/app/projects/{project.pk}/tasks/{receipt.task_id}/"}
    _require_current_sources(project, payload["sources"])
    if Task.objects.filter(project=project, archived_at__isnull=True, title__iexact=title).exists():
        raise ValidationError("A task with this title already exists. Review the project task board.")
    references = "\n".join(f"[{row['citation']}] {row['title']} · {row['locator']} · {row['source_id']}"
                            for row in payload["sources"])
    content = (description + "\n\nReviewed assistant draft. Source references:\n" + references).strip()
    task = create_task(actor=current, project=project, data={"title": title, "description": content})
    AssistantTaskReceipt.objects.create(user=current, project=project, token_digest=token_digest,
                                         payload_sha256=payload_digest, task=task)
    return {"task_id": str(task.pk), "title": task.title, "created": True,
            "task_url": f"/app/projects/{project.pk}/tasks/{task.pk}/"}
