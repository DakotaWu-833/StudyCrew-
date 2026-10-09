import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from operations.recovery import create_backup, verify_backup, RecoveryError


class Command(BaseCommand):
    help = "Create a consistent database backup in a new directory, or verify an existing backup."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--destination")
        group.add_argument("--verify")
        parser.add_argument("--include-media", action="store_true")
        parser.add_argument("--hash-only", action="store_true", help="Verify hashes without a PostgreSQL archive check; never sufficient for restore.")
        parser.add_argument("--revision", default="")

    def handle(self, *args, **options):
        try:
            if options["verify"]:
                result = verify_backup(source=options["verify"], hash_only=options["hash_only"])
                result.pop("manifest", None)
            else:
                result = create_backup(config=settings.DATABASES["default"], destination=options["destination"],
                    media_root=settings.MEDIA_ROOT, include_media=options["include_media"], revision=options["revision"])
        except (RecoveryError, OSError) as exc:
            raise CommandError(str(exc) if isinstance(exc, RecoveryError) else "Backup file operation failed; check permissions and available space.") from exc
        self.stdout.write(json.dumps(result))
