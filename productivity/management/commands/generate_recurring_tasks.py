from django.core.management.base import BaseCommand
from productivity.services import generate_due_recurring_tasks


class Command(BaseCommand):
    help = "Create due recurring task occurrences safely, without duplicates."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        count = generate_due_recurring_tasks(limit=options["limit"])
        self.stdout.write(f"Created {count} recurring task occurrences.")
