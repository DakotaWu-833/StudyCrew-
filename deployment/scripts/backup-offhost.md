# Encrypted off-host backup boundary

This optional Linux template transports an already completed local snapshot.
Nothing here demonstrates working cloud credentials, real encryption-tool
installation, remote durability or a successful remote restore. The tests use
explicit fake tools and a temporary local directory; their simulated ciphertext
is not encryption. No real transfer was performed during implementation.

The script checks the selected snapshot's age, complete manifest and full file
hashes with the existing verifier, including SQLite integrity/FK checks or
PostgreSQL archive validation. It validates the age public recipient and that a
named remote exists in a protected rclone configuration. These are local
preflights; `listremotes` does not establish cloud authentication or reachability.
Without `BACKUP_SOURCE`, it selects the newest completed manifest under
`BACKUP_ROOT`; a corrupt or stale newest snapshot fails instead of silently
choosing an older one.

`tar` feeds `age --encrypt --recipient` through a pipe into a newly created
private ciphertext directory. Upload starts only after both commands succeed.
`rclone copyto --immutable` uploads this completed ciphertext to a new UUID object
under the configured prefix. This avoids `rclone rcat`'s documented overwrite
behavior and permits retrying the ciphertext. Configure server-side object
retention/lock and an appropriate append-only identity where supported; generic
rclone checks do not provide an atomic create-only guarantee against a separate
writer racing at the storage provider. The script does not delete, move or prune
any local snapshot, encrypted spool file or remote object. Failed partial
ciphertext remains retained and has no successful transport receipt.

Only a public recipient key belongs on the application host. Keep its age private
identity offline in a protected independent location; test it before relying on
the backup. Copy `backup-offhost.env.example` into a protected
`/etc/studycrew/backup-offhost.env`, configure `/etc/studycrew/rclone.conf` with
your chosen provider, and grant only the required service identity access. No
configuration or credentials are sourced as shell code or printed. Configuration
files may be 0600 or root:studycrew 0640; world access and group-write are rejected
on Linux. Provision `/srv/studycrew/app/var/offhost` as studycrew-owned 0700 before
installing the systemd service. This directory and the existing snapshot root
must remain outside the web root. Review provider quota, cost, retention and
spool disk capacity separately; this template deliberately performs no pruning.

Read-only local preflight, after installing the real dependencies and privately
loading the reviewed environment:

```bash
bash -n deployment/scripts/backup-offhost.sh
bash deployment/scripts/backup-offhost.sh --check
```

`--check` reads the snapshot/configuration and validates the public recipient; it
creates no ciphertext and uploads nothing. Running without this flag is the
explicit transport operation. Install the optional `studycrew-backup-offhost`
service/timer only after reviewing the provider configuration. Its 04:00 UTC
schedule follows the local snapshot timer; a missing/stale snapshot fails the
transport rather than manufacturing a backup. Both services need independent
monitoring. The transport service reports failure via its exit status and emits
no messages or notifications.

A successful run retains a private local `transport-receipt.json` containing the
ciphertext SHA-256, byte count and remote object address. It explicitly records
`remote_restore_verified: false`. Download the exact remote object to a new
isolated location, compare that ciphertext hash, decrypt with the separately
held age identity, extract to an unused directory and run the repository's
backup verification and isolated restore acceptance. Do not deploy a restored
database or send recovered notifications merely to test the backup. Retain
measured remote retrieval/decryption/restore evidence before public launch.

Contract verification uses `manage.py test config.tests.test_offhost_backup`.
It checks Bash syntax, no-upload preflight, stale/corrupt backup refusal,
separate ciphertext destinations, bounded failures and unchanged source hashes.
It validates orchestration using tool substitutes; actual age/rclone/cloud
operation and Linux service confinement remain external acceptance gates.

Primary references: [age usage](https://github.com/FiloSottile/age#usage),
[rclone copyto](https://rclone.org/commands/rclone_copyto/),
[rclone immutable flag](https://rclone.org/flags/),
[rclone rcat overwrite behavior](https://rclone.org/commands/rclone_rcat/).
