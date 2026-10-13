from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.utils import timezone
from datetime import timedelta

from .models import ProjectDocument, DocumentVersion
from .policies import project_access, can_edit
from .storage import limits, MIMES, scan_required
from .services import preview_kind


def version_row(version, project_id):
    return {"id": str(version.pk), "number": version.number, "filename": version.filename,
        "content_type": version.content_type, "size": version.size, "sha256": version.sha256,
        "scan_status": version.scan_status, "created_at": version.created_at,
        "download_url": f"/api/v1/files/projects/{project_id}/documents/{version.document_id}/download/?version={version.pk}",
        "preview_kind": preview_kind(version),
        "preview_url": f"/api/v1/files/projects/{project_id}/documents/{version.document_id}/preview/?version={version.pk}" if preview_kind(version) else None}


def document_row(document, user, *, history=False):
    versions = list(document.versions.all())
    result = {"id": str(document.pk), "project": str(document.project_id), "title": document.title,
        "folder": document.folder, "tags": document.tags, "pinned": document.pinned, "revision": document.revision,
        "author": {"id": str(document.author_id), "display_name": document.author.profile.display_name},
        "created_at": document.created_at, "updated_at": document.updated_at,
        "can_edit": not document.project.archived_at and can_edit(user, document),
        "latest": version_row(versions[0], document.project_id) if versions else None}
    if history:
        result["versions"] = [version_row(v, document.project_id) for v in versions]
    return result


def usage(project):
    return {"bytes": DocumentVersion.objects.filter(document__project=project).aggregate(total=Sum("size"))["total"] or 0,
        **limits()}


def documents(user, project_id, query="", folder="", tag="", page=1):
    project = project_access(user, project_id)
    query = str(query).strip()[:160]
    rows = ProjectDocument.objects.filter(project=project, removed_at__isnull=True).select_related("project", "author__profile").prefetch_related("versions")
    if query:
        rows = rows.filter(Q(title__icontains=query) | Q(folder__icontains=query) | Q(tags__icontains=query))
    if folder:
        rows = rows.filter(folder=folder[:80])
    if tag:
        rows = rows.filter(tag_index__tag=tag[:32])
    pager = Paginator(rows, 25)
    try:
        current = pager.get_page(int(page))
    except (ValueError, TypeError):
        raise ValidationError({"page": "Use a valid page number."})
    return {"results": [document_row(row, user) for row in current], "count": pager.count,
        "page": current.number, "pages": pager.num_pages, "usage": usage(project),
        "allowed_extensions": sorted(MIMES), "scan_required": scan_required()}


def detail(user, project_id, document_id):
    from django.shortcuts import get_object_or_404
    project = project_access(user, project_id)
    row = get_object_or_404(ProjectDocument.objects.select_related("project", "author__profile").prefetch_related("versions"),
        pk=document_id, project=project, removed_at__isnull=True)
    return document_row(row, user, history=True)


def trash(user, project_id, query="", page=1):
    project = project_access(user, project_id)
    rows = ProjectDocument.objects.filter(project=project, removed_at__isnull=False,
        restoration_blocked=False, author__is_active=True, author__closed_at__isnull=True).select_related(
        "project", "author__profile").prefetch_related("versions").order_by("-removed_at", "id")
    if query:
        rows = rows.filter(Q(title__icontains=str(query).strip()[:160]) | Q(folder__icontains=str(query).strip()[:160]))
    try:
        current = Paginator(rows, 25).get_page(int(page))
    except (ValueError, TypeError):
        raise ValidationError({"page": "Use a valid page number."})
    result = []
    for document in current:
        row = document_row(document, user)
        row["can_edit"] = False
        row["removed_at"] = document.removed_at
        row["purge_after"] = document.removed_at + timedelta(days=30)
        row["can_restore"] = bool(not project.archived_at and can_edit(user, document)
            and row["purge_after"] > timezone.now() and document.versions.exists())
        # Trash rows intentionally contain no usable preview/download links.
        # All reads remain forbidden until explicit restoration.
        row["latest"] = None
        result.append(row)
    return {"results": result, "count": current.paginator.count, "page": current.number,
        "pages": current.paginator.num_pages, "retention_days": 30}
