"""Recovery tests use real SQLite snapshots and isolated directories."""
from datetime import timedelta
from contextlib import closing
from io import StringIO
import json
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from operations.models import WorkerHeartbeat
from operations.recovery import RecoveryError, create_backup, restore_backup, verify_backup, _run


class RecoveryTests(SimpleTestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "live.sqlite3"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO evidence(value) VALUES ('committed')")
            connection.commit()
        self.config = {"ENGINE": "django.db.backends.sqlite3", "NAME": self.database}
        self.backup = self.root / "backup"
        self.target = self.root / "restored"

    def snapshot(self, **options):
        return create_backup(config=self.config, destination=self.backup, **options)

    def test_online_snapshot_includes_committed_wal_but_not_uncommitted_changes(self):
        connection = sqlite3.connect(self.database)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO evidence(value) VALUES ('in WAL')")
        connection.commit()
        connection.execute("INSERT INTO evidence(value) VALUES ('uncommitted')")
        self.snapshot()
        with closing(sqlite3.connect(self.backup / "database.sqlite3")) as snapshot:
            self.assertEqual(snapshot.execute("SELECT value FROM evidence ORDER BY id").fetchall(), [("committed",), ("in WAL",)])
        self.assertTrue(verify_backup(source=self.backup)["valid"])
        connection.rollback()

    def test_media_manifest_and_restore_preserve_nested_files(self):
        media = self.root / "media"
        (media / "reports").mkdir(parents=True)
        (media / "reports" / "manifest.json").write_bytes(b"student file")
        self.snapshot(media_root=media, include_media=True)
        manifest = verify_backup(source=self.backup)["manifest"]
        self.assertEqual(len(manifest["files"]), 2)
        self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["files"]))
        result = restore_backup(source=self.backup, destination=self.target, restore=True)
        self.assertTrue(result["restored"])
        self.assertEqual((self.target / "media/reports/manifest.json").read_bytes(), b"student file")
        self.assertTrue((self.target / "restore-receipt.json").is_file())

    def test_empty_media_directory_is_preserved(self):
        media = self.root / "media"
        media.mkdir()
        self.snapshot(media_root=media, include_media=True)
        restore_backup(source=self.backup, destination=self.target, restore=True)
        self.assertTrue((self.target / "media").is_dir())

    def test_default_restore_is_verification_only(self):
        self.snapshot()
        result = restore_backup(source=self.backup, destination=self.target)
        self.assertFalse(result["restored"])
        self.assertFalse(self.target.exists())

    def test_existing_backup_and_restore_destinations_are_never_overwritten(self):
        self.snapshot()
        with self.assertRaises(RecoveryError): self.snapshot()
        self.target.mkdir()
        marker = self.target / "keep.txt"
        marker.write_text("untouched")
        with self.assertRaises(RecoveryError): restore_backup(source=self.backup, destination=self.target, restore=True)
        self.assertEqual(marker.read_text(), "untouched")

    def test_tampered_database_rejected_before_restore_creates_target(self):
        self.snapshot()
        with (self.backup / "database.sqlite3").open("ab") as output: output.write(b"tamper")
        with self.assertRaises(RecoveryError): restore_backup(source=self.backup, destination=self.target, restore=True)
        self.assertFalse(self.target.exists())

    def test_manifest_traversal_and_invalid_shape_rejected(self):
        self.snapshot()
        manifest_path = self.backup / "manifest.json"
        original = json.loads(manifest_path.read_text())
        for bad_path in ("../live.sqlite3", "/live.sqlite3", "media/../live.sqlite3", "C:/live.sqlite3", "media\\escape"):
            modified = dict(original)
            modified["files"] = [{**original["files"][0], "path": bad_path}]
            manifest_path.write_text(json.dumps(modified))
            with self.assertRaises(RecoveryError): verify_backup(source=self.backup)
        manifest_path.write_text("[]")
        with self.assertRaises(RecoveryError): verify_backup(source=self.backup)

    def test_unlisted_files_and_destination_within_source_rejected(self):
        self.snapshot()
        with self.assertRaises(RecoveryError): restore_backup(source=self.backup, destination=self.backup / "nested", restore=True)
        (self.backup / "unexpected.txt").write_text("not listed")
        with self.assertRaises(RecoveryError): verify_backup(source=self.backup)

    def test_postgres_dependency_check_happens_before_destination_created(self):
        with patch("operations.recovery.shutil.which", return_value=None):
            with self.assertRaisesRegex(RecoveryError, "pg_dump"):
                create_backup(config={"ENGINE": "django.db.backends.postgresql", "NAME": "live", "PASSWORD": "secret"}, destination=self.backup)
        self.assertFalse(self.backup.exists())

    def test_postgres_restore_requires_different_new_database_and_never_cleans(self):
        report = {"engine": "postgresql", "media_included": False, "manifest": {"files": []}}
        config = {"NAME": "live", "PASSWORD": "secret", "USER": "backup"}
        with patch("operations.recovery.verify_backup", return_value=report), patch("operations.recovery._tool", side_effect=lambda value: value), patch("operations.recovery._run") as run:
            for name in ("live", "invalid-name", "postgresql://secret@host/db"):
                with self.assertRaises(RecoveryError): restore_backup(source=self.backup, destination=self.target, restore=True, postgres_database=name, config=config)
                self.assertFalse(self.target.exists())
            restore_backup(source=self.backup, destination=self.target, restore=True, postgres_database="new_restore", config=config)
            arguments = [call.args[0] for call in run.call_args_list]
            self.assertEqual(arguments[0][0], "createdb")
            self.assertIn("--single-transaction", arguments[1])
            self.assertNotIn("--clean", str(arguments))
            self.assertNotIn("secret", str(arguments))
            self.assertEqual(run.call_args_list[0].kwargs["env"]["PGPASSWORD"], "secret")

    def test_database_utility_errors_do_not_echo_credentials(self):
        error = subprocess.CalledProcessError(1, ["pg_dump"], stderr=b"postgresql://password@example.invalid")
        with patch("operations.recovery.subprocess.run", side_effect=error):
            with self.assertRaises(RecoveryError) as caught: _run(["pg_dump"])
        self.assertNotIn("password", str(caught.exception))
        self.assertNotIn("example.invalid", str(caught.exception))


class RuntimeHealthCommandTests(TestCase):
    def test_worker_required_rejects_stale_then_accepts_fresh(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            WorkerHeartbeat.objects.create(name="delivery", last_run_at=timezone.now()-timedelta(minutes=6))
            output = StringIO()
            with self.assertRaises(CommandError): call_command("check_runtime_health", require_worker=True, stdout=output)
            self.assertEqual(json.loads(output.getvalue())["worker"], "stale_or_missing")
            WorkerHeartbeat.objects.update(last_run_at=timezone.now())
            output = StringIO()
            call_command("check_runtime_health", require_worker=True, stdout=output)
            self.assertTrue(json.loads(output.getvalue())["healthy"])

    def test_command_backup_and_default_restore_require_explicit_write(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "source.sqlite3"
            with closing(sqlite3.connect(live)) as connection: connection.execute("CREATE TABLE sample(id INTEGER)")
            with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": live}}):
                output = StringIO()
                call_command("backup_studycrew", destination=str(root / "backup"), stdout=output)
                call_command("restore_studycrew", source=str(root / "backup"), target=str(root / "restore"), stdout=StringIO())
            self.assertFalse((root / "restore").exists())
