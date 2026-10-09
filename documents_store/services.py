"""Transaction-owned file writes and permission-checked authenticated reads."""
from __future__ import annotations

import hashlib
import difflib
import io
import os
from datetime import timedelta
from pathlib import Path
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from projects.policies import is_project_manager
from operations.models import OperationAudit
from operations.services import consume_rate
from .models import ProjectDocument, DocumentVersion, UploadDailyUsage, DocumentTag
from .policies import project_access, require_editor
from .storage import prepare, blob_path, limits, scan_required, validate_contents

PREVIEW_TEXT_BYTES = 512 * 1024
DIFF_TEXT_BYTES = 256 * 1024
DIFF_MAX_LINES = 2000


def preview_kind(version):
    return {"text/plain": "text", "text/csv": "text", "image/png": "image",
        "image/jpeg": "image", "application/pdf": "pdf"}.get(version.content_type)


def _values(values):
    values = dict(values)
    values.pop("expected_revision", None)
    if set(values) - {"title", "folder", "tags", "pinned"}:
        raise ValidationError("Unexpected file metadata fields.")
    for key, maximum in (("title", 150), ("folder", 80)):
        if key in values:
            if not isinstance(values[key], str) or len(values[key].strip()) > maximum or (key == "title" and not values[key].strip()):
                raise ValidationError({key: "Use a valid bounded text value."})
            values[key] = values[key].strip()
    if "tags" in values:
        if not isinstance(values["tags"], list) or len(values["tags"]) > 10 or any(not isinstance(tag, str) or len(tag.strip()) > 32 for tag in values["tags"]):
            raise ValidationError({"tags": "Use at most 10 tags of up to 32 characters."})
        values["tags"] = list(dict.fromkeys(tag.strip() for tag in values["tags"] if tag.strip()))
    if "pinned" in values and not isinstance(values["pinned"], bool):
        raise ValidationError({"pinned": "Use a boolean value."})
    return values


def _sync_tags(document):
    DocumentTag.objects.filter(document=document).delete()
    DocumentTag.objects.bulk_create([DocumentTag(document=document, tag=tag) for tag in document.tags])


def _expected(document, expected):
    if expected != document.revision:
        raise ValidationError({"expected_revision": "This file changed. Reload before saving."})


def _document(project, document_id):
    return get_object_or_404(ProjectDocument.objects.select_for_update(), pk=document_id, project=project, removed_at__isnull=True)


def upload(*, actor, project_id, upload, values=None, document_id=None):
    # Avoid processing data for users who cannot access/write the target.
    project_access(actor, project_id, write=True)
    if not consume_rate("private-file-upload", str(actor.pk), limit=30, seconds=3600):
        raise ValidationError("Upload attempts are temporarily limited. Try again later.")
    prepared = prepare(upload)
    destination = None
    created_destination = False
    try:
        # A filesystem write owns its outermost commit. Nesting it under an
        # unrelated later rollback would otherwise leave an unreferenced blob.
        with transaction.atomic(durable=True):
            # Consistent lock order serializes each user's cross-project quota and
            # each project's retained-version capacity (PostgreSQL and SQLite IMMEDIATE).
            actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
            project = project_access(actor, project_id, write=True, lock=True)
            values = dict(values or {})
            if document_id:
                document = _document(project, document_id)
                require_editor(actor, document)
                _expected(document, values.pop("expected_revision", None))
                if document.versions.count() >= 50:
                    raise ValidationError("A document can retain at most 50 versions. Start a separate document.")
                document.revision += 1
                document.save(update_fields=["revision", "updated_at"])
            else:
                metadata = _values(values)
                if metadata.get("pinned") and not is_project_manager(actor, project):
                    raise PermissionDenied("Project manager permission is required to pin a file.")
                metadata.setdefault("title", prepared["filename"][:150])
                document = ProjectDocument(project=project, author=actor, **metadata)
                document.full_clean()
                document.save()
                _sync_tags(document)
            policy = limits()
            retained = DocumentVersion.objects.filter(document__project=project)
            if retained.count() >= policy["retained_version_limit"]:
                raise ValidationError({"file": "Project retained-version count limit is full."})
            used = retained.aggregate(total=Sum("size"))["total"] or 0
            daily, _ = UploadDailyUsage.objects.get_or_create(user=actor, day=timezone.now().date())
            if used + prepared["size"] > policy["limit"]:
                raise ValidationError({"file": "Project storage quota is full, including retained versions and removed files."})
            if daily.bytes + prepared["size"] > policy["daily_bytes_limit"] or daily.count >= policy["daily_upload_limit"]:
                raise ValidationError({"file": "Your daily upload quota is full. Try again after the next UTC day."})
            key = f"{project.pk}/{uuid.uuid4()}.blob"
            destination = blob_path(key)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Exclusive destination creation prevents accidental replacement.
            with destination.open("xb") as output:
                created_destination = True
                with prepared["path"].open("rb") as source:
                    for block in iter(lambda: source.read(65536), b""):
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
            version = DocumentVersion.objects.create(document=document, uploaded_by=actor,
                number=(document.versions.first().number + 1) if document.versions.exists() else 1,
                storage_key=key, **{k: prepared[k] for k in ("filename", "content_type", "size", "sha256", "scan_status")})
            daily.bytes += version.size
            daily.count += 1
            daily.save(update_fields=["bytes", "count"])
            OperationAudit.objects.create(actor=actor, action="project_file_uploaded", target_id=document.pk,
                metadata={"project": str(project.pk), "version": str(version.pk), "size": version.size})
        return document
    except BaseException:
        if destination and created_destination:
            destination.unlink(missing_ok=True)
        raise
    finally:
        prepared["path"].unlink(missing_ok=True)


@transaction.atomic
def update(*, actor, project_id, document_id, values):
    project = project_access(actor, project_id, write=True, lock=True)
    document = _document(project, document_id)
    require_editor(actor, document)
    _expected(document, values.get("expected_revision"))
    metadata = _values(values)
    if "pinned" in metadata and metadata["pinned"] != document.pinned and not is_project_manager(actor, project):
        raise PermissionDenied("Project manager permission is required to pin a file.")
    for key, value in metadata.items():
        setattr(document, key, value)
    document.revision += 1
    document.full_clean()
    document.save()
    if "tags" in metadata:
        _sync_tags(document)
    OperationAudit.objects.create(actor=actor, action="project_file_metadata_changed", target_id=document.pk,
        metadata={"project": str(project.pk), "revision": document.revision})
    return document


@transaction.atomic
def remove(*, actor, project_id, document_id, expected_revision):
    project = project_access(actor, project_id, write=True, lock=True)
    document = _document(project, document_id)
    require_editor(actor, document)
    _expected(document, expected_revision)
    document.removed_at = timezone.now()
    document.revision += 1
    document.save(update_fields=["removed_at", "revision", "updated_at"])
    OperationAudit.objects.create(actor=actor, action="project_file_removed", target_id=document.pk,
        metadata={"project": str(project.pk)})


def _open_version(version):
    if not version or (scan_required() and version.scan_status != "clean"):
        raise Http404
    path = blob_path(version.storage_key)
    try:
        stream = path.open("rb")
    except OSError:
        raise Http404
    try:
        digest = hashlib.sha256()
        size = 0
        for block in iter(lambda: stream.read(65536), b""):
            size += len(block)
            digest.update(block)
        if size != version.size or digest.hexdigest() != version.sha256:
            raise Http404
        stream.seek(0)
        return stream, version
    except BaseException:
        stream.close()
        raise


def open_download(*, user, project_id, document_id, version_id=None):
    project = project_access(user, project_id)
    document = get_object_or_404(ProjectDocument, pk=document_id, project=project, removed_at__isnull=True)
    versions = document.versions.all()
    version = versions.filter(pk=version_id).first() if version_id else versions.first()
    if not consume_rate("private-file-download", str(user.pk), limit=120, seconds=3600):
        raise ValidationError("Downloads are temporarily limited. Try again later.")
    return _open_version(version)


def open_preview(*, user, project_id, document_id, version_id=None):
    stream, version = open_download(user=user, project_id=project_id, document_id=document_id, version_id=version_id)
    kind = preview_kind(version)
    if not kind:
        stream.close()
        raise ValidationError("Preview supports PDF, PNG, JPEG and UTF-8 text/CSV files. Download other formats.")
    # Revalidate permitted formats before exposing a renderer. The download's
    # stored digest must also match; changing a blob never bypasses this check.
    try:
        payload = stream.read()
        validate_contents(payload, version.filename.rsplit(".", 1)[-1].lower())
        truncated = kind == "text" and len(payload) > PREVIEW_TEXT_BYTES
        if kind == "text":
            payload = payload[:PREVIEW_TEXT_BYTES].decode("utf-8-sig", errors="ignore").encode("utf-8")
        return io.BytesIO(payload), version, truncated
    finally:
        stream.close()


def text_diff(*, user, project_id, document_id, from_version, to_version):
    project = project_access(user, project_id)
    document = get_object_or_404(ProjectDocument, pk=document_id, project=project, removed_at__isnull=True)
    if from_version == to_version:
        raise ValidationError("Choose two different versions to compare.")
    if not consume_rate("private-file-diff", str(user.pk), limit=60, seconds=3600):
        raise ValidationError("Version comparisons are temporarily limited. Try again later.")
    versions = document.versions.filter(pk__in=[from_version, to_version])
    by_id = {v.pk: v for v in versions}
    values = []
    for identifier in (from_version, to_version):
        version = by_id.get(identifier)
        if version is None:
            raise Http404
        if preview_kind(version) != "text":
            raise ValidationError("Version comparison supports UTF-8 text and CSV files only.")
        if version.size > DIFF_TEXT_BYTES:
            raise ValidationError("Each version must be at most 256 KB for an inline comparison. Download larger files.")
        stream, _ = _open_version(version)
        with stream:
            payload = stream.read()
        try:
            text = payload.decode("utf-8-sig")
            lines = text.splitlines(keepends=True)
        except UnicodeDecodeError:
            raise ValidationError("Version comparison requires valid UTF-8 text.")
        if len(lines) > DIFF_MAX_LINES or any(len(line) > 5000 for line in lines):
            raise ValidationError("Each version must have at most 2,000 lines with 5,000 characters per line.")
        values.append((version, lines, text))
    before, after = values
    rows, total_bytes, truncated = [], 0, False
    for line in difflib.unified_diff(before[1], after[1], fromfile=f"Version {before[0].number}: {before[0].filename}",
            tofile=f"Version {after[0].number}: {after[0].filename}", n=3, lineterm=""):
        total_bytes += len(line.encode("utf-8"))
        if len(rows) >= DIFF_MAX_LINES or total_bytes > PREVIEW_TEXT_BYTES:
            truncated = True
            break
        kind = "header" if line.startswith(("---", "+++", "@@")) else "added" if line.startswith("+") else "removed" if line.startswith("-") else "context"
        rows.append({"kind": kind, "text": line.rstrip("\r\n"),
            "no_final_newline": kind in {"added", "removed"} and not line.endswith(("\r", "\n"))})
    return {"from_version": str(from_version), "to_version": str(to_version), "lines": rows,
        "truncated": truncated, "identical": before[2] == after[2],
        "line_ending_changed": before[2] != after[2] and before[2].splitlines() == after[2].splitlines()}


@transaction.atomic
def restore(*, actor, project_id, document_id, expected_revision):
    actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
    project = project_access(actor, project_id, write=True, lock=True)
    document = get_object_or_404(ProjectDocument.objects.select_for_update(), pk=document_id,
        project=project, removed_at__isnull=False)
    require_editor(actor, document)
    _expected(document, expected_revision)
    if document.restoration_blocked or not document.author.is_active or document.author.closed_at:
        raise ValidationError("Files removed because their author closed their account cannot be restored.")
    if document.removed_at <= timezone.now() - timedelta(days=30):
        raise ValidationError("The 30-day restoration period has ended.")
    versions = list(document.versions.all())
    if not versions:
        raise ValidationError("This file no longer has retained versions and cannot be restored.")
    # Removed versions already count against storage quotas. Restoring them
    # allocates no new bytes and cannot bypass either storage or upload quotas.
    for version in versions:
        try:
            stream, _ = _open_version(version)
            stream.close()
        except Http404:
            raise ValidationError("A retained version is unavailable or failed integrity checks. This file cannot be restored.")
    document.removed_at = None
    document.revision += 1
    document.save(update_fields=["removed_at", "revision", "updated_at"])
    OperationAudit.objects.create(actor=actor, action="project_file_restored", target_id=document.pk,
        metadata={"project": str(project.pk), "revision": document.revision})
    return document
