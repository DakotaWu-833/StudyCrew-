#!/usr/bin/env bash
# Reviewed Linux boundary: only completed local snapshots enter this pipeline.
set -euo pipefail
set +x
set -C
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }
[[ $# -eq 0 || ( $# -eq 1 && "$1" == "--check" ) ]] || fail "Use no arguments, or --check for local preflight only."
script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
python_tool="${BACKUP_OFFHOST_PYTHON:-python3}"
snapshot_root="${BACKUP_ROOT:-$script_root/var/backups}"
spool_root="${BACKUP_OFFHOST_SPOOL:-$script_root/var/offhost}"
max_age="${BACKUP_OFFHOST_MAX_AGE_HOURS:-30}"
recipient="${BACKUP_AGE_RECIPIENT:-}"
remote="${BACKUP_OFFHOST_REMOTE:-}"
config_file="${BACKUP_RCLONE_CONFIG:-}"

for tool in "$python_tool" age rclone tar; do
    command -v "$tool" >/dev/null 2>&1 || fail "An off-host backup dependency is unavailable."
done
[[ "$recipient" =~ ^age1[0-9a-z]+$ ]] || fail "Configure an age public recipient key."
[[ "$remote" =~ ^[A-Za-z][A-Za-z0-9_.-]*:[A-Za-z0-9_./-]+$ ]] || fail "Configure a named rclone remote and restricted destination prefix."
[[ "/${remote#*:}/" != *"/../"* ]] || fail "Remote destination traversal is not allowed."
[[ -f "$config_file" && -r "$config_file" && ! -L "$config_file" ]] || fail "A readable protected rclone configuration is required."
age --version >/dev/null 2>&1 || fail "age is unavailable."
age --encrypt --recipient "$recipient" </dev/null >/dev/null 2>&1 || fail "The age public recipient is invalid."
remote_name="${remote%%:*}:"
configured_remotes="$(rclone listremotes --config "$config_file" --ask-password=false 2>/dev/null)" || fail "rclone configuration preflight failed."
remote_found=false
while IFS= read -r configured; do
    [[ "$configured" == "$remote_name" ]] && remote_found=true
done <<< "$configured_remotes"
[[ "$remote_found" == true ]] || fail "The requested rclone remote is not configured."

# This Python uses the existing verifier, including hashes, complete tree,
# SQLite integrity/FK checks or PostgreSQL archive validation. No settings load.
snapshot="$("$python_tool" - "$script_root" "$snapshot_root" "${BACKUP_SOURCE:-}" "$max_age" "$config_file" <<'PY'
import json, os, stat, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
sys.path.insert(0, sys.argv[1])
from operations.recovery import verify_backup
try:
    root = Path(sys.argv[2]).resolve()
    if not root.is_dir():
        raise ValueError()
    limit = int(sys.argv[4])
    if not 1 <= limit <= 168:
        raise ValueError()
    config = Path(sys.argv[5])
    if os.name == "posix" and stat.S_IMODE(config.stat().st_mode) & 0o037:
        raise ValueError()
    def created(path):
        value = json.loads((path / "manifest.json").read_text(encoding="utf-8"))["created_at"]
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is None:
            raise ValueError()
        return instant.astimezone(timezone.utc)
    if sys.argv[3]:
        candidate = Path(sys.argv[3])
    else:
        candidates = [row for row in root.iterdir() if row.is_dir() and not row.is_symlink() and (row / "manifest.json").is_file()]
        candidate = max(candidates, key=created)
    if candidate.is_symlink():
        raise ValueError()
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError()
    instant, now = created(candidate), datetime.now(timezone.utc)
    if instant > now + timedelta(minutes=5) or instant < now - timedelta(hours=limit):
        raise ValueError()
    verify_backup(source=candidate)
    print(candidate.as_posix())
except Exception:
    print("Completed snapshot or configuration preflight failed.", file=sys.stderr)
    sys.exit(1)
PY
)" || fail "Off-host backup preflight failed."

if [[ "${1:-}" == "--check" ]]; then
    printf '%s\n' "Local snapshot, age recipient and rclone configuration passed preflight; cloud access is unverified."
    exit 0
fi

# Create a new private spool directory. No existing ciphertext or backup is
# replaced or removed. Partial ciphertext remains available after a failure.
ciphertext="$("$python_tool" - "$spool_root" <<'PY'
import sys, uuid
from pathlib import Path
try:
    root = Path(sys.argv[1]).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / uuid.uuid4().hex
    target.mkdir(mode=0o700)
    print((target / "snapshot.tar.age").as_posix())
except Exception:
    print("Encrypted spool creation failed.", file=sys.stderr)
    sys.exit(1)
PY
)" || fail "Encrypted spool creation failed."
if ! tar -C "$snapshot" -cf - . 2>/dev/null | age --encrypt --recipient "$recipient" 2>/dev/null > "$ciphertext"; then
    fail "Backup packaging or encryption failed; no upload was attempted."
fi
object_name="$(basename -- "$(dirname -- "$ciphertext")")/snapshot.tar.age"
destination="${remote%/}/$object_name"
# copyto honors immutable destination checks and can retry the completed
# ciphertext. rcat is deliberately avoided because it overwrites existing files.
if ! rclone copyto "$ciphertext" "$destination" --config "$config_file" --ask-password=false \
    --immutable --retries 1 --low-level-retries 2 --contimeout 10s --timeout 120s \
    --max-duration 30m --stats 0 --log-level ERROR >/dev/null 2>&1; then
    fail "Encrypted backup upload failed; local snapshots and ciphertext were retained."
fi
"$python_tool" - "$ciphertext" "$destination" <<'PY'
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
try:
    ciphertext = Path(sys.argv[1])
    digest = hashlib.sha256()
    with ciphertext.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    receipt = {"transport_completed_at": datetime.now(timezone.utc).isoformat(),
               "ciphertext_bytes": ciphertext.stat().st_size, "ciphertext_sha256": digest.hexdigest(),
               "remote_object": sys.argv[2], "remote_restore_verified": False}
    with (ciphertext.parent / "transport-receipt.json").open("x", encoding="utf-8") as output:
        json.dump(receipt, output, indent=2)
except Exception:
    print("Transport completed but its local receipt could not be recorded.", file=sys.stderr)
    sys.exit(1)
PY
printf '%s\n' "Encrypted backup transport completed; remote download, decryption and restore still require acceptance."
