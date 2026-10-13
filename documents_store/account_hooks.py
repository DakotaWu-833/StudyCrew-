"""Account integration boundaries; shared audit records retain a redacted user."""
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from projects.models import ProjectMembership
from .models import ProjectDocument, UploadDailyUsage
from .selectors import version_row


def export_documents(user):
    projects = set(ProjectMembership.objects.active().filter(user=user).values_list("project_id", flat=True))
    result = []
    authored = ProjectDocument.objects.filter(Q(author=user) | Q(versions__uploaded_by=user)).distinct().prefetch_related("versions")
    for document in authored:
        row = {"id": str(document.pk), "project": str(document.project_id), "created_at": document.created_at,
            "removed_at": document.removed_at}
        if document.project_id in projects:
            row.update(title=document.title, folder=document.folder, tags=document.tags,
                versions=[version_row(v, document.project_id) for v in document.versions.all()
                          if document.author_id == user.pk or v.uploaded_by_id == user.pk])
        else:
            row["content_withheld"] = True
        result.append(row)
    return result


@transaction.atomic
def close_documents(user):
    # Closure revokes restoration even for a file removed before the account
    # closed. Suspending/re-enabling an account cannot undo this privacy action.
    ProjectDocument.objects.filter(author=user).update(restoration_blocked=True)
    ProjectDocument.objects.filter(author=user, removed_at__isnull=True).update(
        removed_at=timezone.now(), updated_at=timezone.now(), revision=F("revision") + 1)
    UploadDailyUsage.objects.filter(user=user).delete()
