"""Bounded expiry of derived vectors and old approval receipts; retain tasks."""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from knowledge.models import AssistantTaskReceipt, EmbeddingCache


class Command(BaseCommand):
    help = ("Report expired embedding vectors (14 days) and approval receipts (30 days). "
            "Use --execute to delete at most --limit rows from each table. Project tasks remain retained.")

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--execute", action="store_true", help="Delete the bounded expired rows; otherwise only report counts.")
        mode.add_argument("--dry-run", action="store_true", help="Only report candidates (the default).")
        parser.add_argument("--embedding-days", type=int, default=14, help="Keep vectors for this many days (1–3650).")
        parser.add_argument("--receipt-days", type=int, default=30, help="Keep approval receipts for this many days (1–3650).")
        parser.add_argument("--limit", type=int, default=1000, help="Maximum rows to delete per table in one run (1–10000).")

    def handle(self, *args, **options):
        for field in ("embedding_days", "receipt_days"):
            value = options[field]
            if type(value) is not int or not 1 <= value <= 3650:
                raise CommandError("Retention must be a whole number of days between 1 and 3650.")
        limit = options["limit"]
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise CommandError("The row limit must be a whole number between 1 and 10000.")
        if options["execute"] and options["dry_run"]:
            raise CommandError("Choose either --execute or --dry-run.")
        now = timezone.now()
        vectors = EmbeddingCache.objects.filter(created_at__lt=now - timedelta(days=options["embedding_days"]))
        receipts = AssistantTaskReceipt.objects.filter(created_at__lt=now - timedelta(days=options["receipt_days"]))
        eligible_vectors, eligible_receipts = vectors.count(), receipts.count()
        if not options["execute"]:
            self.stdout.write(
                f"Dry run: eligible vectors={eligible_vectors}, receipts={eligible_receipts}; "
                f"would delete vectors={min(eligible_vectors, limit)}, receipts={min(eligible_receipts, limit)}. "
                f"Limit={limit} per table; no tasks or projects are deleted."
            )
            return
        with transaction.atomic():
            # Recheck expiry at deletion and keep the transaction bounded. Deleting
            # a receipt removes the child row, never its PROTECT-referenced task.
            vector_ids = list(vectors.order_by("created_at", "pk").values_list("pk", flat=True)[:limit])
            receipt_ids = list(receipts.order_by("created_at", "pk").values_list("pk", flat=True)[:limit])
            vector_count, _ = vectors.filter(pk__in=vector_ids).delete()
            receipt_count, _ = receipts.filter(pk__in=receipt_ids).delete()
        self.stdout.write(
            f"Deleted vectors={vector_count}, receipts={receipt_count}; "
            f"eligible before cleanup vectors={eligible_vectors}, receipts={eligible_receipts}. "
            f"Limit={limit} per table; project tasks remain retained."
        )
