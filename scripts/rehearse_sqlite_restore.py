"""Create an isolated SQLite recovery drill and compare every restored table.

No application path is changed. The evidence directory must be new. Output
contains counts and hashes, never row contents or user identifiers.
"""
from argparse import ArgumentParser
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from operations.recovery import RecoveryError, create_backup, restore_backup, verify_backup


def fingerprint(database):
    tables = {}
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        schema = connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            identifier = '"' + name.replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA table_info({identifier})").fetchall()
            order = ",".join(str(index+1) for index in range(len(columns)))
            digest = hashlib.sha256()
            count = 0
            for row in connection.execute(f"SELECT * FROM {identifier} ORDER BY {order}"):
                digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=lambda value: {"binary_hex": value.hex()}).encode("utf-8"))
                digest.update(b"\n")
                count += 1
            tables[name] = {"rows": count, "sha256": digest.hexdigest()}
    return {"schema_sha256": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(), "tables": tables}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--media")
    args = parser.parse_args()
    root = Path(args.evidence_dir).resolve()
    if root.exists(): parser.error("The evidence directory must be new.")
    root.mkdir(parents=True, mode=0o700)
    started = monotonic()
    try:
        create_backup(config={"ENGINE": "django.db.backends.sqlite3", "NAME": args.database}, destination=root / "backup",
                      media_root=args.media, include_media=bool(args.media))
        verified = verify_backup(source=root / "backup")
        restore_backup(source=root / "backup", destination=root / "restored", restore=True)
        snapshot = fingerprint(root / "backup/database.sqlite3")
        restored = fingerprint(root / "restored/database.sqlite3")
        if snapshot != restored: raise RecoveryError("The restored schema or table data differs from the snapshot.")
        report = {"passed": True, "engine": "sqlite", "tables_compared": len(snapshot["tables"]),
                  "rows_compared": sum(item["rows"] for item in snapshot["tables"].values()),
                  "manifest_files": verified["files"], "media_included": verified["media_included"],
                  "schema_sha256": snapshot["schema_sha256"], "elapsed_seconds": round(monotonic()-started, 3),
                  "comparison": "schema_and_every_table_row_sha256", "tables": snapshot["tables"]}
        with (root / "report.json").open("x", encoding="utf-8") as output: json.dump(report, output, indent=2)
        print(json.dumps({key: value for key, value in report.items() if key != "tables"}))
        return 0
    except RecoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
