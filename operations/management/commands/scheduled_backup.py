"""Unique, verified automatic snapshots. Existing backups are never replaced."""
import json
import secrets
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from operations.models import WorkerHeartbeat
from operations.recovery import create_backup, verify_backup, RecoveryError


class Command(BaseCommand):
    help = "Create and verify a new timestamped database/media snapshot under BACKUP_ROOT."

    def handle(self, *args, **options):
        root = Path(settings.BACKUP_ROOT).resolve()
        # The parent is a trusted operator-configured directory. Never prune or
        # replace existing backups; off-host encrypted retention is operator-owned.
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = root / (timezone.now().strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4))
        try:
            result = create_backup(config=settings.DATABASES["default"], destination=destination,
                                  media_root=settings.MEDIA_ROOT, include_media=True)
            verify_backup(source=destination)
        except (RecoveryError, OSError):
            raise CommandError("Automatic backup failed; the previous verified snapshot remains unchanged. Check protected operator logs and storage.") from None
        # Record success only after DB/media hash and engine checks pass. A failed
        # run leaves the last success unchanged and is detected by freshness.
        WorkerHeartbeat.objects.update_or_create(name="backup", defaults={"last_run_at": timezone.now(),
            "detail": {"verified": True, "engine": result["engine"], "files": result["files"], "bytes": result["bytes"], "media_included": True}})
        self.stdout.write(json.dumps({"verified": True, "engine": result["engine"], "files": result["files"], "bytes": result["bytes"]}))
