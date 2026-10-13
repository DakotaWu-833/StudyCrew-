import json
import logging
import time
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connections, OperationalError
from operations.worker import tick

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Schedule and deliver durable notifications and exports; --once is suitable for a scheduler."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=30)
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        failures = 0
        while True:
            close_old_connections()
            try:
                result = tick(max(1, min(options["limit"], 200)))
            except OperationalError:
                # A temporary DB lock/disconnect must not terminate the local
                # web host. Leased messages remain subject to uncertainty rules.
                connections.close_all()
                if options["once"]:
                    raise CommandError("The worker database is temporarily unavailable; no successful heartbeat was recorded.") from None
                failures += 1
                logger.warning("Worker database temporarily unavailable; retrying with backoff.")
                time.sleep(min(60, 5 * failures))
                continue
            failures = 0
            self.stdout.write(json.dumps(result))
            if options["once"]:
                break
            time.sleep(max(5, min(options["interval"], 300)))
