"""Pipeline contract with fake tools only; these tests never contact a remote."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase
from operations.recovery import create_backup


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deployment/scripts/backup-offhost.sh"


def bash_executable():
    candidate = shutil.which("bash")
    if candidate:
        return candidate
    git = shutil.which("git")
    if git:
        candidate = Path(git).resolve().parent.parent / "usr/bin/sh.exe"
        if candidate.is_file():
            return str(candidate)
    return None


FAKE_TOOLS = r'''
import base64, json, os, pathlib, sys
tool, args = sys.argv[1], sys.argv[2:]
root = pathlib.Path(os.environ["OFFHOST_TEST_ROOT"])
with (root / "tool-calls.jsonl").open("a", encoding="utf-8") as record:
    record.write(json.dumps({"tool": tool, "args": args}) + "\n")
if tool == "age":
    if "--version" in args:
        sys.exit(0)
    data = sys.stdin.buffer.read()
    if data and os.environ.get("FAKE_ENCRYPTION_FAIL"):
        print("private-tool-configuration", file=sys.stderr)
        sys.exit(12)
    sys.stdout.buffer.write(b"SIMULATED-AGE\n" + base64.b64encode(data))
elif tool == "tar":
    if os.environ.get("FAKE_PACKAGING_FAIL"):
        print("private-tool-configuration", file=sys.stderr)
        sys.exit(13)
    source = pathlib.Path(args[args.index("-C") + 1])
    sys.stdout.buffer.write(b"SIMULATED-TAR\n" + (source / "database.sqlite3").read_bytes())
elif tool == "rclone":
    if args[0] == "listremotes":
        print("othercloud:" if os.environ.get("FAKE_MISSING_REMOTE") else "testcloud:")
    elif args[0] == "copyto":
        if "--immutable" not in args:
            sys.exit(16)
        if os.environ.get("FAKE_UPLOAD_FAIL"):
            print("private-tool-configuration", file=sys.stderr)
            sys.exit(14)
        source = pathlib.Path(args[1])
        suffix = args[2].split(":", 1)[1]
        target = root / "fake-cloud" / suffix
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(source.read_bytes())
    else:
        sys.exit(15)
'''


class OffhostBackupTests(SimpleTestCase):
    def setUp(self):
        self.bash = bash_executable()
        if not self.bash:
            self.skipTest("Bash is required for deployment pipeline simulation.")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.source = self.root / "source.sqlite3"
        with closing(sqlite3.connect(self.source)) as database:
            with database:
                database.execute("CREATE TABLE private_example (message TEXT)")
                database.execute("INSERT INTO private_example VALUES ('private-student-example')")
        self.snapshot = self.backups / "snapshot"
        create_backup(config={"ENGINE": "django.db.backends.sqlite3", "NAME": str(self.source)}, destination=self.snapshot)
        self.original_files = self.fingerprint()
        self.config = self.root / "rclone.conf"
        self.config.write_text("[testcloud]\nsecret = private-config-sentinel\n", encoding="utf-8")
        self.config.chmod(0o600)
        tools = self.root / "tools"
        tools.mkdir()
        helper = self.root / "fake_tools.py"
        helper.write_text(FAKE_TOOLS, encoding="utf-8")
        for name in ("tar", "age", "rclone"):
            wrapper = tools / name
            wrapper.write_text(f'#!/bin/sh\nexec "$OFFHOST_TEST_PYTHON" "$OFFHOST_TEST_HELPER" {name} "$@"\n', encoding="utf-8", newline="\n")
            wrapper.chmod(0o700)
        self.environment = os.environ.copy()
        # The synthetic tools precede all real tools. Credentials/configuration
        # are disposable fixtures, and upload means writing inside this temp dir.
        self.environment.update({
            "PATH": f"{tools}{os.pathsep}{Path(self.bash).parent}{os.pathsep}{self.environment.get('PATH', '')}",
            "BACKUP_OFFHOST_PYTHON": sys.executable,
            "BACKUP_ROOT": str(self.backups),
            "BACKUP_OFFHOST_SPOOL": str(self.root / "spool"),
            "BACKUP_AGE_RECIPIENT": "age1testonlyrecipient",
            "BACKUP_OFFHOST_REMOTE": "testcloud:protected-prefix",
            "BACKUP_RCLONE_CONFIG": str(self.config),
            "OFFHOST_TEST_PYTHON": sys.executable,
            "OFFHOST_TEST_HELPER": str(helper),
            "OFFHOST_TEST_ROOT": str(self.root),
        })

    def fingerprint(self):
        return {row.relative_to(self.snapshot).as_posix(): hashlib.sha256(row.read_bytes()).hexdigest()
                for row in self.snapshot.rglob("*") if row.is_file()}

    def run_pipeline(self, *arguments, **values):
        result = subprocess.run([self.bash, str(SCRIPT), *arguments], env=self.environment | values,
            capture_output=True, text=True, timeout=30)
        self.assertNotIn("private-config-sentinel", result.stdout + result.stderr)
        self.assertNotIn("private-tool-configuration", result.stdout + result.stderr)
        return result

    def calls(self):
        path = self.root / "tool-calls.jsonl"
        return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def uploads(self):
        return [row for row in self.calls() if row["tool"] == "rclone" and row["args"][0] == "copyto"]

    def test_bash_syntax_and_preflight_do_not_upload_or_create_ciphertext(self):
        syntax = subprocess.run([self.bash, "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        result = self.run_pipeline("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cloud access is unverified", result.stdout)
        self.assertFalse(self.uploads())
        self.assertFalse((self.root / "spool").exists())

    def test_success_passes_only_completed_ciphertext_and_keeps_all_previous_backups(self):
        for _ in range(2):
            result = self.run_pipeline()
            self.assertEqual(result.returncode, 0, result.stderr)
        uploads = self.uploads()
        self.assertEqual(len(uploads), 2)
        self.assertNotEqual(uploads[0]["args"][2], uploads[1]["args"][2])
        objects = list((self.root / "fake-cloud").rglob("*.age"))
        self.assertEqual(len(objects), 2)
        for item in objects:
            payload = item.read_bytes()
            self.assertTrue(payload.startswith(b"SIMULATED-AGE\n"))
            self.assertNotIn(b"private-student-example", payload)
            self.assertIn(b"private-student-example", base64.b64decode(payload.split(b"\n", 1)[1]))
        self.assertEqual(self.fingerprint(), self.original_files)
        receipts = list((self.root / "spool").rglob("transport-receipt.json"))
        self.assertEqual(len(receipts), 2)
        for receipt in receipts:
            data = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertFalse(data["remote_restore_verified"])
            self.assertEqual(data["ciphertext_sha256"], hashlib.sha256((receipt.parent / "snapshot.tar.age").read_bytes()).hexdigest())

    def test_corrupt_or_stale_completed_snapshot_is_refused_before_packaging(self):
        manifest = self.snapshot / "manifest.json"
        original = manifest.read_text(encoding="utf-8")
        document = json.loads(original)
        document["created_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        manifest.write_text(json.dumps(document), encoding="utf-8")
        self.assertNotEqual(self.run_pipeline().returncode, 0)
        manifest.write_text(original, encoding="utf-8")
        with (self.snapshot / "database.sqlite3").open("ab") as output:
            output.write(b"corruption")
        self.assertNotEqual(self.run_pipeline().returncode, 0)
        self.assertFalse(self.uploads())
        self.assertFalse(any(row["tool"] == "tar" for row in self.calls()))

    def test_missing_remote_and_invalid_recipient_or_destination_are_refused(self):
        cases = [{"FAKE_MISSING_REMOTE": "1"}, {"BACKUP_AGE_RECIPIENT": "AGE-SECRET-KEY-1never-accepted"},
                 {"BACKUP_OFFHOST_REMOTE": "testcloud:../unsafe"}, {"BACKUP_OFFHOST_REMOTE": "/local/path"}]
        for values in cases:
            with self.subTest(values=values):
                self.assertNotEqual(self.run_pipeline(**values).returncode, 0)
        self.assertFalse(self.uploads())
        self.assertEqual(self.fingerprint(), self.original_files)

    def test_packaging_encryption_and_upload_failures_return_nonzero_without_deleting_source(self):
        for flag in ("FAKE_PACKAGING_FAIL", "FAKE_ENCRYPTION_FAIL", "FAKE_UPLOAD_FAIL"):
            with self.subTest(failure=flag):
                before = len(self.uploads())
                result = self.run_pipeline(**{flag: "1"})
                self.assertNotEqual(result.returncode, 0)
                if flag != "FAKE_UPLOAD_FAIL":
                    self.assertEqual(len(self.uploads()), before)
                self.assertEqual(self.fingerprint(), self.original_files)
        self.assertFalse(list((self.root / "spool").rglob("transport-receipt.json")))

