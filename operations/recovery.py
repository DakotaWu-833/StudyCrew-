"""Offline backup/restore primitives. No credential values are logged or manifested."""

from datetime import datetime, timezone as datetime_timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess


class RecoveryError(RuntimeError):
    """A safe, actionable recovery error without tool stderr or secrets."""


def _digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _tool(name):
    executable = shutil.which(name)
    if not executable:
        raise RecoveryError(f"{name} is required on PATH for this PostgreSQL operation.")
    return executable


def _pg_env(config):
    result = os.environ.copy()
    if config.get("PASSWORD"):
        result["PGPASSWORD"] = str(config["PASSWORD"])
    # libpq supports a protected .pgpass/PGPASSFILE; the password is never an argument.
    result.setdefault("PGCONNECT_TIMEOUT", "10")
    return result


def _pg_args(config):
    result = []
    for setting, option in (("HOST", "host"), ("PORT", "port"), ("USER", "username")):
        if config.get(setting): result.append(f"--{option}={config[setting]}")
    return result


def _run(arguments, *, env=None, timeout=600):
    try:
        subprocess.run(arguments, env=env, check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise RecoveryError("The database utility timed out. Inspect the isolated target and retry with a new target.") from exc
    except (subprocess.CalledProcessError, OSError) as exc:
        # Database utilities may echo a connection URI/password in stderr.
        raise RecoveryError("The database utility failed. Check client compatibility, connection permissions and available space.") from exc


def _safe_tree(root):
    root = Path(root).resolve()
    for current, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(current) / name
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise RecoveryError("Symbolic links are not allowed in backup or media trees.")
        for name in files:
            path = Path(current) / name
            if not path.is_file(): raise RecoveryError("Only regular media files can be backed up.")
            yield path


def _new_directory(path):
    path = Path(path).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise RecoveryError("The destination already exists. Choose a new, unused target directory.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir(mode=0o700)
    return path.resolve()


def _sqlite_check(path):
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RecoveryError("SQLite integrity validation failed.")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise RecoveryError("SQLite foreign-key validation failed.")
    except sqlite3.DatabaseError as exc:
        raise RecoveryError("The SQLite backup is unreadable or invalid.") from exc


def _write_json(path, data):
    with path.open("x", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    path.chmod(0o600)


def create_backup(*, config, destination, media_root=None, include_media=False, revision=""):
    engine = config.get("ENGINE", "")
    if engine not in ("django.db.backends.sqlite3", "django.db.backends.postgresql"):
        raise RecoveryError("Only SQLite and PostgreSQL backups are supported.")
    source_media = Path(media_root).resolve() if include_media and media_root else None
    if include_media and (not source_media or not source_media.is_dir()):
        raise RecoveryError("The requested media directory does not exist.")
    target_candidate = Path(destination).expanduser().absolute()
    if source_media and (target_candidate.resolve().is_relative_to(source_media) or source_media.is_relative_to(target_candidate.resolve())):
        raise RecoveryError("Keep the backup destination separate from the source media directory.")
    if engine.endswith("sqlite3"):
        source_database = Path(config["NAME"]).resolve()
        if not source_database.is_file(): raise RecoveryError("The SQLite source database does not exist.")
        filename = "database.sqlite3"
    else:
        dump = _tool("pg_dump"); restore = _tool("pg_restore")
        filename = "database.dump"
    target = _new_directory(destination)
    database_file = target / filename
    if engine.endswith("sqlite3"):
        # sqlite3.Connection.backup is SQLite's consistent online .backup API,
        # including committed WAL rows. Never copy a live .sqlite3 file directly.
        try:
            with closing(sqlite3.connect(source_database.as_uri() + "?mode=ro", uri=True, timeout=20)) as source:
                with closing(sqlite3.connect(database_file)) as output:
                    source.backup(output, pages=256, sleep=0.05)
                    # The snapshot inherits WAL mode. Convert the isolated copy
                    # to a single rollback-journal file before hashing/verification.
                    output.execute("PRAGMA journal_mode=DELETE")
            _sqlite_check(database_file)
        except sqlite3.Error as exc:
            raise RecoveryError("SQLite snapshot failed. The incomplete destination has no valid manifest.") from exc
        integrity = "sqlite_integrity_and_foreign_keys_ok"
    else:
        _run([dump, *_pg_args(config), f"--dbname={config.get('NAME', '')}", "--format=custom", "--no-owner", "--no-privileges", f"--file={database_file}"], env=_pg_env(config))
        _run([restore, "--list", str(database_file)])
        integrity = "postgresql_archive_list_ok"
    database_file.chmod(0o600)
    if source_media:
        (target / "media").mkdir(mode=0o700)
        for path in _safe_tree(source_media):
            destination_file = target / "media" / path.relative_to(source_media)
            destination_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(path, destination_file)
            destination_file.chmod(0o600)
    files = [{"path": path.relative_to(target).as_posix(), "bytes": path.stat().st_size, "sha256": _digest(path)}
             for path in sorted(_safe_tree(target))]
    manifest = {"format_version": 1, "created_at": datetime.now(datetime_timezone.utc).isoformat(),
                "engine": "sqlite" if engine.endswith("sqlite3") else "postgresql",
                "database_file": filename, "database_validation": integrity,
                "media_included": bool(source_media), "revision": str(revision)[:80], "files": files}
    _write_json(target / "manifest.json", manifest)
    return {"destination": str(target), "engine": manifest["engine"], "files": len(files),
            "bytes": sum(item["bytes"] for item in files), "media_included": manifest["media_included"]}


def verify_backup(*, source, hash_only=False):
    root = Path(source).expanduser().resolve()
    if not root.is_dir() or not (root / "manifest.json").is_file():
        raise RecoveryError("A complete backup requires a manifest.json file.")
    if (root / "manifest.json").is_symlink(): raise RecoveryError("Backup manifests must be regular files.")
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError("The backup manifest cannot be read.") from exc
    if not isinstance(manifest, dict):
        raise RecoveryError("The backup manifest must be an object.")
    engine = manifest.get("engine")
    expected_database = {"sqlite": "database.sqlite3", "postgresql": "database.dump"}.get(engine)
    if manifest.get("format_version") != 1 or manifest.get("database_file") != expected_database or not expected_database:
        raise RecoveryError("This backup format or database engine is unsupported.")
    listed = set()
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RecoveryError("The backup manifest contains no files.")
    for item in files:
        if not isinstance(item, dict): raise RecoveryError("Invalid manifest file entry.")
        name = item.get("path", "")
        if not isinstance(name, str) or not name or "\\" in name or ":" in name:
            raise RecoveryError("Invalid manifest file path.")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or str(relative) != name or name in listed:
            raise RecoveryError("The manifest contains an unsafe or duplicate file path.")
        if name != expected_database and not name.startswith("media/"):
            raise RecoveryError("The manifest may include only its database and media files.")
        path = root / Path(*relative.parts)
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise RecoveryError("A manifest file is missing or escapes its backup directory.")
        if path.stat().st_size != item.get("bytes") or _digest(path) != item.get("sha256"):
            raise RecoveryError("A backup file failed its size or SHA-256 check.")
        listed.add(name)
    actual = {path.relative_to(root).as_posix() for path in _safe_tree(root) if path != root / "manifest.json"}
    if expected_database not in listed or actual != listed:
        raise RecoveryError("The backup contents do not match the manifest.")
    if any(name.startswith("media/") for name in listed) and not manifest.get("media_included"):
        raise RecoveryError("The media manifest flag does not match its contents.")
    if engine == "sqlite":
        _sqlite_check(root / expected_database)
        validation = "sqlite_integrity_and_foreign_keys_ok"
    elif hash_only:
        validation = "hashes_only_postgresql_restore_not_validated"
    else:
        _run([_tool("pg_restore"), "--list", str(root / expected_database)])
        validation = "postgresql_archive_list_ok"
    return {"valid": True, "engine": engine, "files": len(files), "database_validation": validation,
            "media_included": bool(manifest.get("media_included")), "manifest": manifest}


def restore_backup(*, source, destination=None, restore=False, postgres_database=None, config=None):
    if not restore:
        result = verify_backup(source=source)
        return {key: value for key, value in result.items() if key != "manifest"} | {"restored": False, "next_step": "Use --restore with a new target directory to create an isolated restore."}
    if not destination: raise RecoveryError("An explicit new target directory is required with --restore.")
    result = verify_backup(source=source)
    manifest = result["manifest"]
    source_root = Path(source).expanduser().resolve()
    target_candidate = Path(destination).expanduser().absolute()
    if target_candidate.resolve().is_relative_to(source_root) or source_root.is_relative_to(target_candidate.resolve()):
        raise RecoveryError("Restore into a separate new directory, outside the backup tree.")
    if result["engine"] == "postgresql":
        if not postgres_database or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", postgres_database):
            raise RecoveryError("A new PostgreSQL database name using letters, digits and underscores is required.")
        if not config or postgres_database == str(config.get("NAME", "")):
            raise RecoveryError("The restore database must differ from the configured application database.")
        create = _tool("createdb"); pg_restore = _tool("pg_restore")
    target = _new_directory(destination)
    if result["engine"] == "sqlite":
        database_file = target / "database.sqlite3"
        try:
            with closing(sqlite3.connect((source_root / "database.sqlite3").as_uri() + "?mode=ro", uri=True)) as original:
                with closing(sqlite3.connect(database_file)) as restored:
                    original.backup(restored, pages=256, sleep=0.05)
                    restored.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.Error as exc:
            raise RecoveryError("SQLite restore failed. Choose a new isolated target after checking available space.") from exc
        database_file.chmod(0o600); _sqlite_check(database_file)
    else:
        # createdb fails when the named database exists. No DROP, --clean, or
        # CREATE replacement of a live database is ever issued.
        environment = _pg_env(config)
        _run([create, *_pg_args(config), "--template=template0", postgres_database], env=environment)
        _run([pg_restore, *_pg_args(config), f"--dbname={postgres_database}", "--no-owner", "--no-privileges", "--single-transaction", "--exit-on-error", str(source_root / "database.dump")], env=environment)
    if result["media_included"]:
        (target / "media").mkdir(mode=0o700)
    for item in manifest["files"]:
        if not item["path"].startswith("media/"): continue
        output = target / Path(*PurePosixPath(item["path"]).parts)
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source_root / Path(*PurePosixPath(item["path"]).parts), output)
        output.chmod(0o600)
        if _digest(output) != item["sha256"]: raise RecoveryError("A restored media file failed its SHA-256 check.")
    receipt = {"restored": True, "engine": result["engine"], "destination": str(target),
               "files": len(manifest["files"]), "media_included": result["media_included"],
               "restored_at": datetime.now(datetime_timezone.utc).isoformat()}
    if postgres_database: receipt["new_database"] = postgres_database
    _write_json(target / "restore-receipt.json", receipt)
    return receipt
