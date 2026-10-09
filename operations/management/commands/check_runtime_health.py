import json
from pathlib import Path
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from operations.models import WorkerHeartbeat, OutboundMessage


class Command(BaseCommand):
    help = "Check database, migration state, media availability and delivery-worker freshness without PII."

    def add_arguments(self, parser):
        parser.add_argument("--require-worker", action="store_true")
        parser.add_argument("--require-backup", action="store_true")
        parser.add_argument("--max-worker-age", type=int, default=300)

    def handle(self, *args, **options):
        status = {"database": False, "migrations": False, "media_directory": False, "worker": "not_required"}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1"); status["database"] = cursor.fetchone()[0] == 1
            executor = MigrationExecutor(connection)
            status["migrations"] = not executor.migration_plan(executor.loader.graph.leaf_nodes())
            media = Path(settings.MEDIA_ROOT)
            status["media_directory"] = media.is_dir()
            if status["migrations"]:
                worker = WorkerHeartbeat.objects.filter(name="delivery").first()
                fresh = bool(worker and worker.last_run_at >= timezone.now()-timedelta(seconds=max(30, options["max_worker_age"])))
                status["worker"] = "fresh" if fresh else "stale_or_missing"
                status["queued_messages"] = OutboundMessage.objects.filter(status="queued").count()
                status["failed_messages"] = OutboundMessage.objects.filter(status="failed").count()
        except Exception:
            # Avoid leaking DB host names, credentials, recipient addresses or paths.
            status["error"] = "A runtime dependency check failed."
        from operations.backup_health import backup_health
        try:
            backup = backup_health() if status["migrations"] else {"healthy": False}
        except Exception:
            backup = {"healthy": False}
        status["backup"] = "fresh" if backup["healthy"] else "stale_or_missing"
        passed = status["database"] and status["migrations"] and status["media_directory"] and (not options["require_worker"] or status["worker"] == "fresh") and (not options["require_backup"] or backup["healthy"])
        self.stdout.write(json.dumps({"healthy": bool(passed), **status}))
        if not passed: raise CommandError("Runtime health checks failed.")
