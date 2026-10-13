from io import StringIO
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from operations.models import WorkerHeartbeat
from operations.backup_health import backup_health
from operations.recovery import RecoveryError


class ScheduledBackupTests(TestCase):
    def test_heartbeat_requires_successful_database_and_media_verification(self):
        with TemporaryDirectory() as root, override_settings(BACKUP_ROOT=root):
            result = {"engine": "sqlite", "files": 3, "bytes": 123}
            with patch("operations.management.commands.scheduled_backup.create_backup", return_value=result) as create, patch("operations.management.commands.scheduled_backup.verify_backup", side_effect=RecoveryError("Corrupt copy")):
                with self.assertRaises(CommandError): call_command("scheduled_backup", stdout=StringIO())
            self.assertFalse(backup_health()["healthy"]); self.assertFalse(WorkerHeartbeat.objects.filter(name="backup").exists())
            with patch("operations.management.commands.scheduled_backup.create_backup", return_value=result) as create, patch("operations.management.commands.scheduled_backup.verify_backup"):
                call_command("scheduled_backup", stdout=StringIO()); first = create.call_args.kwargs["destination"]
                call_command("scheduled_backup", stdout=StringIO()); second = create.call_args.kwargs["destination"]
            self.assertNotEqual(first, second); self.assertTrue(create.call_args.kwargs["include_media"])
            self.assertTrue(backup_health()["healthy"])
            text = str(WorkerHeartbeat.objects.get(name="backup").detail); self.assertNotIn(root, text)

    @override_settings(BACKUP_MAX_AGE_HOURS=30)
    def test_missing_failed_or_old_snapshot_is_unhealthy(self):
        self.assertFalse(backup_health()["healthy"])
        row = WorkerHeartbeat.objects.create(name="backup", last_run_at=timezone.now() - timedelta(hours=31), detail={"verified": True})
        self.assertFalse(backup_health()["healthy"])
        row.last_run_at = timezone.now(); row.detail = {"verified": False}; row.save()
        self.assertFalse(backup_health()["healthy"])
        row.detail = {"verified": True}; row.save(); self.assertTrue(backup_health()["healthy"])
