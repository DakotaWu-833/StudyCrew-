from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase


class WorkerDependencyRecoveryTests(SimpleTestCase):
    def test_transient_database_failure_closes_connection_backs_off_and_recovers(self):
        output = StringIO()
        with patch("operations.management.commands.run_delivery_worker.tick", side_effect=[OperationalError("private-host-path"), {"recovered": True}]) as tick, patch("operations.management.commands.run_delivery_worker.connections.close_all") as close, patch("operations.management.commands.run_delivery_worker.close_old_connections"), patch("operations.management.commands.run_delivery_worker.time.sleep", side_effect=[None, KeyboardInterrupt]) as sleep:
            with self.assertRaises(KeyboardInterrupt): call_command("run_delivery_worker", stdout=output)
        self.assertEqual(tick.call_count, 2); close.assert_called_once(); self.assertEqual(sleep.call_args_list[0].args, (5,))
        self.assertIn('"recovered": true', output.getvalue()); self.assertNotIn("private-host-path", output.getvalue())

    def test_scheduler_once_reports_failure_without_marking_success_or_leaking_dependency(self):
        with patch("operations.management.commands.run_delivery_worker.tick", side_effect=OperationalError("private-host")), patch("operations.management.commands.run_delivery_worker.connections.close_all"), patch("operations.management.commands.run_delivery_worker.close_old_connections"):
            with self.assertRaises(CommandError) as failure: call_command("run_delivery_worker", once=True, stdout=StringIO())
        self.assertNotIn("private-host", str(failure.exception))
