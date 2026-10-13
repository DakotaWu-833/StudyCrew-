"""Standalone local recovery CLI; credentials come from the environment/.pgpass."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from operations.recovery import create_backup, restore_backup, verify_backup, RecoveryError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    backup = actions.add_parser("backup")
    backup.add_argument("--engine", choices=("sqlite", "postgresql"), default="sqlite")
    backup.add_argument("--database", required=True)
    backup.add_argument("--destination", required=True)
    backup.add_argument("--media")
    backup.add_argument("--revision", default="")
    verify = actions.add_parser("verify")
    verify.add_argument("--source", required=True)
    verify.add_argument("--hash-only", action="store_true")
    restore = actions.add_parser("restore")
    restore.add_argument("--source", required=True)
    restore.add_argument("--target")
    restore.add_argument("--restore", action="store_true")
    restore.add_argument("--postgres-database")
    args = parser.parse_args()
    config = {"ENGINE": f"django.db.backends.{('postgresql' if getattr(args, 'engine', '') == 'postgresql' else 'sqlite3')}",
              "NAME": getattr(args, "database", None) or os.environ.get("DB_NAME", ""),
              "HOST": os.environ.get("DB_HOST", ""), "PORT": os.environ.get("DB_PORT", ""),
              "USER": os.environ.get("DB_USER", ""), "PASSWORD": os.environ.get("DB_PASSWORD", "")}
    try:
        if args.action == "backup":
            result = create_backup(config=config, destination=args.destination, media_root=args.media, include_media=bool(args.media), revision=args.revision)
        elif args.action == "verify":
            result = verify_backup(source=args.source, hash_only=args.hash_only); result.pop("manifest", None)
        else:
            result = restore_backup(source=args.source, destination=args.target, restore=args.restore, postgres_database=args.postgres_database, config=config)
        print(json.dumps(result, indent=2)); return 0
    except (RecoveryError, OSError) as exc:
        print(str(exc) if isinstance(exc, RecoveryError) else "Recovery file operation failed; inspect permissions, disk space and the isolated target.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
