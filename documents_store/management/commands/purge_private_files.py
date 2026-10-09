"""Purge hidden, expired retained files; never prune active project evidence."""
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from documents_store.models import ProjectDocument, DocumentVersion, UploadDailyUsage
from documents_store.storage import blob_path, root, KEY
from projects.models import Project


class Command(BaseCommand):
    help = "Purge soft-removed private files after 30 days; optional stale crash-orphan cleanup."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply cleanup; otherwise report counts only.")
        parser.add_argument("--orphans", action="store_true", help="Also clean UUID blobs/pending uploads older than 48 hours without database references.")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=30)
        candidates = list(ProjectDocument.objects.filter(removed_at__lt=cutoff).values_list("pk", "project_id"))
        removed = 0
        for identifier, project_id in candidates:
            if not options["apply"]:
                continue
            with transaction.atomic():
                Project.objects.select_for_update().get(pk=project_id)
                document = ProjectDocument.objects.select_for_update().filter(pk=identifier, removed_at__lt=cutoff).first()
                if not document:
                    continue
                try:
                    for version in document.versions.all():
                        blob_path(version.storage_key).unlink(missing_ok=True)
                except (OSError, ValueError) as exc:
                    raise CommandError("A private blob could not be removed. Cleanup stopped; retry after checking storage permissions.") from exc
                document.delete()
                removed += 1
        orphan_count = 0
        if options["orphans"]:
            references = set(DocumentVersion.objects.values_list("storage_key", flat=True))
            base = root()
            old = (timezone.now() - timedelta(hours=48)).timestamp()
            for file in base.rglob("*"):
                if not file.is_file() or file.is_symlink() or file.stat().st_mtime >= old:
                    continue
                relative = file.relative_to(base).as_posix()
                if relative in references or not (KEY.fullmatch(relative) or (file.parent == base and file.name.startswith("pending-"))):
                    continue
                if options["apply"]:
                    file.unlink()
                orphan_count += 1
        if options["apply"]:
            UploadDailyUsage.objects.filter(day__lt=cutoff.date()).delete()
        self.stdout.write(f"Expired documents: {len(candidates)}; purged: {removed}; stale orphan candidates: {orphan_count}.")
