import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from operations.recovery import restore_backup, RecoveryError


class Command(BaseCommand):
    help = "Validate by default; restore only with explicit --restore into an unused target."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True)
        parser.add_argument("--target")
        parser.add_argument("--restore", action="store_true")
        parser.add_argument("--postgres-database", help="New database; the restore role needs CREATE DATABASE permission.")

    def handle(self, *args, **options):
        try:
            result = restore_backup(source=options["source"], destination=options["target"], restore=options["restore"],
                                    postgres_database=options["postgres_database"], config=settings.DATABASES["default"])
        except (RecoveryError, OSError) as exc:
            raise CommandError(str(exc) if isinstance(exc, RecoveryError) else "Restore file operation failed; inspect the isolated target and retry into a new target.") from exc
        self.stdout.write(json.dumps(result))
