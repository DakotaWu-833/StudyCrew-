"""Personal-data boundaries used by account export and closure."""
from projects.models import ProjectMembership
from .models import ImportBatch, ImportPreview


def export_learning(user):
    current = set(ProjectMembership.objects.active().filter(user=user, user__is_active=True).values_list("project_id", flat=True))
    batches = []
    for batch in ImportBatch.objects.filter(actor=user).iterator():
        record = {"id": str(batch.id), "project_id": str(batch.project_id), "created_at": batch.created_at.isoformat()}
        if batch.project_id in current:
            record.update(source=batch.source, source_namespace=batch.source_namespace, timezone_name=batch.timezone_name,
                imported_count=batch.imported_count, skipped_count=batch.skipped_count, rows=batch.rows)
        else:
            record["content_withheld"] = True
        batches.append(record)
    previews = []
    for item in ImportPreview.objects.filter(actor=user).iterator():
        record = {"id": str(item.id), "project_id": str(item.project_id), "created_at": item.created_at.isoformat(), "expires_at": item.expires_at.isoformat()}
        if item.project_id in current:
            record.update(source=item.source, source_namespace=item.source_namespace, timezone_name=item.timezone_name, rows=item.rows)
        else:
            record["content_withheld"] = True
        previews.append(record)
    return {"learning_imports": batches, "learning_previews": previews}


def close_learning(user):
    ImportPreview.objects.filter(actor=user).delete()
