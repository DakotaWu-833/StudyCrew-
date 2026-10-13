from django.core.management.base import BaseCommand
from django.utils import timezone
from learning_exchange.models import ImportPreview


class Command(BaseCommand):
    help = "Remove expired assignment import previews; retain confirmed batch audit records."

    def handle(self, *args, **options):
        count, _ = ImportPreview.objects.filter(expires_at__lt=timezone.now()).delete()
        self.stdout.write(f"Removed {count} expired learning exchange previews.")
