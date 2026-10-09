# StudyCrew advance: local operation, backup and launch engineering

These assets prepare a deployable configuration using the repository's existing
Django/uWSGI/Nginx/PostgreSQL stack. They do not demonstrate a configured public
server, valid domain/TLS certificate, working production SMTP or measured
production capacity. Production credentials, a Linux host and PostgreSQL clients
remain external dependencies. No Docker installation is required for the local
workflow.

## One-command local operation

From the project root in PowerShell 7 or newer:

```powershell
.\scripts\Start-Advance.ps1 -Port 8003
.\scripts\Start-Advance.ps1 -Demo -Port 8002
```

The normal command uses `var/studycrew.sqlite3`. `-Demo` uses the separate
`var/advance-preview.sqlite3`, media directory and file-email directory. It checks
the application, applies migrations, and seeds only the demo database. Existing
dependencies and a built frontend must already be present; the launcher performs
no automatic installation. The normal local-data entry is
`http://127.0.0.1:8003/app/`, using existing accounts and codes under `var/emails/`.
The isolated demo/test entry is `http://127.0.0.1:8002/app/`, with codes under
`var/advance-preview-emails/`; choose the command for the intended dataset.
Older processes on 8000/8001 may run earlier code.
The `advance` work remains local, uncommitted and unpushed, with no public
deployment. The seven newest enhancements retain the English UI and do not add
a language switch. Rebuild the frontend after editing its source:

```powershell
Set-Location frontend
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
```

The application binds only to `127.0.0.1`; the independent delivery/export worker
also runs locally. Async reminders and exports are enabled. Both background
processes use hidden windows and produce distinct timestamped logs under
`var/logs`. Keep the launcher terminal open. Ctrl+C runs its `finally` cleanup,
which stops only the retained process trees created by that invocation and
restores its environment. An occupied port is an error; the launcher never finds
or terminates other processes using it. `runserver --noreload --insecure` prevents an
untracked reloader child and serves the reviewed static build despite DEBUG=false.
The server is always loopback-only; this static option is for local use. This is a local development host, not a public web
server. Terminating the whole parent terminal or power loss cannot execute
PowerShell's `finally`; inspect the recorded child processes/logs after such an
interruption.

## Health and worker acceptance

`GET /health/` and `HEAD /health/` are low-cost, no-PII readiness endpoints. They
check a database `SELECT 1` and the delivery worker heartbeat freshness. Expect
200 only when dependencies are ready; a stale/missing worker yields 503. The
separate management check includes migration state, the media directory and
aggregate queue/failure counts:

```powershell
.\.venv\Scripts\python.exe manage.py check_runtime_health --require-worker
```

The same worker also creates due recurring-task copies, deletes offline sync
receipts older than 7 days, removes chat presence rows older than 5 minutes,
and clears expired assignment-import previews. Chat considers a member online
only for the most recent 35 seconds; that display window is shorter than row
retention. Recurring generation is idempotent and rechecks the schedule author's
account, current membership and source/project archive state. Run
`manage.py generate_recurring_tasks` for an explicit local generation pass;
keeping the independent worker running is required for scheduled generation.

Do not equate a queued or SMTP-accepted message with confirmed inbox delivery.
Check worker heartbeat, queue growth, failure counts, provider bounce/complaint
callbacks and actual OTP delivery using your chosen provider. A worker crash
after SMTP acceptance can have an uncertain outcome; investigate before retrying
such a message, since sending it again may duplicate delivery.

## Backup format and trust boundary

The backup helpers create a **new** directory containing a database snapshot,
optional `media/`, and a final `manifest.json` with creation time, engine,
optional reviewed revision, file sizes and SHA-256 hashes. A directory without
its final manifest is incomplete. They do not include `.env` files, certificates,
credentials or repository source. Keep secrets separately in a restricted
password/secret store so a restore can use the original Django signing key if
existing security-token digests must remain valid. After a real compromise,
rotate secrets and revoke outstanding tokens deliberately.

SQLite snapshots use `sqlite3.Connection.backup`, the consistent online backup
API, including committed WAL rows. They are checked with `integrity_check` and
`foreign_key_check`. Database and media are not one atomic cross-filesystem
snapshot: enable maintenance mode and pause the worker/writes while taking a
matched database+media backup for release/restore acceptance. A live database-only
snapshot remains internally consistent, but media may change while it is copied.
[Python sqlite3 documentation](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).

Hashes detect corruption and unexpected content; they do not authenticate a
backup against someone who can replace both files and the manifest. Store backups
off the web root, restrict filesystem access, encrypt sensitive copies using a
trusted external storage mechanism, and keep an independently protected/offline
copy. Unix files are created with restricted modes; review Windows ACLs on the
chosen backup directory. The helper refuses symlinks and path traversal, checks
the complete file set, and never executes SQL supplied as a text restore script.

### SQLite local backup, verify and isolated restore

Choose unique destination names for each attempt:

```powershell
.\.venv\Scripts\python.exe manage.py backup_studycrew --destination var\backups\release-20261002 --include-media --revision REVIEWED_COMMIT
.\.venv\Scripts\python.exe manage.py backup_studycrew --verify var\backups\release-20261002
.\.venv\Scripts\python.exe manage.py restore_studycrew --source var\backups\release-20261002
.\.venv\Scripts\python.exe manage.py restore_studycrew --source var\backups\release-20261002 --restore --target var\restore-drills\release-20261002
```

Restore defaults to validation only. It changes files only with explicit
`--restore` and an unused target directory. Existing target directories are
rejected; there is no overwrite/clean option. SQLite is restored to
`<target>/database.sqlite3`; optional media goes to `<target>/media`. A successful
operation writes `restore-receipt.json`. The currently configured database and
media paths are not switched or overwritten. Point a **separate local process**
at the recovered paths for acceptance; do not switch the live process merely to
test a backup. Do not run a recovery drill's worker against a live SMTP provider.

The standalone script avoids loading Django settings when inspecting local
backups:

```powershell
.\.venv\Scripts\python.exe scripts\studycrew_recovery.py backup --engine sqlite --database var\studycrew.sqlite3 --destination var\backups\standalone-example --media var\media
.\.venv\Scripts\python.exe scripts\studycrew_recovery.py verify --source var\backups\standalone-example
.\.venv\Scripts\python.exe scripts\studycrew_recovery.py restore --source var\backups\standalone-example --restore --target var\restore-drills\standalone-example
```

### PostgreSQL boundary

PostgreSQL backup runs the installed `pg_dump --format=custom --no-owner
--no-privileges`, then validates the archive with `pg_restore --list`. Backup
requires a compatible `pg_dump`/`pg_restore` on PATH and a role that can read every
application table. Restore additionally requires `createdb`, a separate trusted
restore role capable of creating a database, and an explicitly new database
name. It creates that database using `template0`, then runs `pg_restore
--single-transaction --exit-on-error --no-owner --no-privileges`. It never issues
DROP, `--clean`, or a replace-existing operation. An existing database name fails
at `createdb`; a failed restore leaves only its newly created isolated database
and target for inspection, never deletes an existing database. Reapply migration
ownership/runtime grants and immutable-audit guards before connecting the web
role to a recovered database. Archive listing is structural validation, not a
successful database restore. A PostgreSQL restore drill is still required.
[pg_dump documentation](https://www.postgresql.org/docs/current/app-pgdump.html),
[pg_restore documentation](https://www.postgresql.org/docs/current/app-pgrestore.html).

The helpers use `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD` (or a protected
libpq `.pgpass`/`PGPASSFILE`). Passwords are passed only in the child environment,
never process arguments or the manifest. Utility stderr is not echoed because it
can contain connection secrets. A backup verification with `--hash-only` reports
that archive/restore validation was not performed; it is insufficient for
restoration. Missing PostgreSQL clients fail safely before database backup
creation. No PostgreSQL production result is claimed without running against an
actual instance and role.

```powershell
# Set connection variables privately in your trusted environment, not in a log.
.\.venv\Scripts\python.exe scripts\studycrew_recovery.py backup --engine postgresql --database studycrew --destination var\backups\postgres-example
.\.venv\Scripts\python.exe scripts\studycrew_recovery.py restore --source var\backups\postgres-example --restore --target var\restore-drills\postgres-example --postgres-database studycrew_rehearsal_20261002
```

## Prepared deployment sequence

Use the baseline learner-lab instructions in
`docs/assignment-3/deployment-runbook.md` for Linux packages, service account,
runtime/migration PostgreSQL roles, firewall and certificate setup. Supplement
them with `deployment/studycrew.env.example`, the independent
`deployment/systemd/studycrew-worker.service`, and the privacy logging snippets.
Replace all `CHANGE_ME` values privately. Keep a domain, certificate, verified
sender, reachable PostgreSQL and explicit production settings as prerequisites.
Production configuration rejects SQLite, placeholder signing keys, insecure
origins and a non-SMTP mail backend.

1. Build and test the reviewed checkout locally; retain its exact revision and
   dependencies. Transfer the reviewed frontend and backend release artifacts.
2. Verify a current backup and perform the isolated restore acceptance below.
3. Enable maintenance mode and stop the worker before schema changes. Record
   the previous application revision, schema state and backup identifier.
4. Load the protected production environment and run `manage.py check --deploy`.
   Migrate only with `studycrew_migrator`; collect static assets. Do not run
   production demo seeding.
5. As the migration/administration role, apply
   `deploy/postgresql/permissions.sql`, then
   `deployment/postgresql/launch-permissions.sql` after every migration. Run
   `deployment/postgresql/verify-launch-permissions.sql` directly as
   `studycrew_app`. The supplemental script grants hard-delete only for named
   disposable/security/relationship records used by the new workflows and guards
   all five audit tables against UPDATE/DELETE. The older baseline verifier's
   three-table DELETE allowlist is intentionally superseded by the launch
   verifier; do not use it as the final advance permission check.
6. Include `deployment/nginx/privacy-logging.conf` in `http {}` and
   `deployment/nginx/studycrew-token-routes.conf` inside the HTTPS server. Retain
   baseline TLS, static, protected-media and sensitive-path denial rules. Replace
   default access logging so inherited logs do not also record raw `$request`.
   Launch uWSGI with both its baseline ini and `deployment/uwsgi-privacy.ini` to
   suppress raw 4xx/5xx request lines. Recovery/join query parameters and ICS
   bearer tokens must not appear in proxy, uWSGI or application logs. Sensitive
   edge locations suppress raw Nginx upstream errors; monitor sanitized
   application errors and readiness for these routes instead.
7. Validate `nginx -t`, restart the application and independent worker, wait for
   a fresh heartbeat, then disable maintenance mode. Run readiness and smoke
   journeys with real email verification and representative project permissions.
8. Run the existing TLS/deployment verifier against the actual domain; retain
   evidence of redirect, headers, cookie flags, denied sensitive paths, worker
   freshness and the SMTP/provider callbacks. No configuration-only check
   demonstrates that these external services work.

The web and worker share the database and media but must be independently
supervised. No browser or request loop launches a worker. Monitor readiness,
queue age/growth, transport failures, database/storage capacity and backup age.
Select retention/RPO/RTO based on real pilot needs; a reasonable initial rehearsal
goal is a daily recoverable snapshot plus a pre-release snapshot, with measured
restore time before the first public cohort. This is an operating target, not a
verified SLA.

## Rollback and measured acceptance

For code-only regression, enable maintenance, stop the worker, switch back to
the recorded previous release, validate static assets and restart both services.
Reverting application code is safe only if the migrated schema remains backward
compatible. Do not assume reverse migrations preserve user data. For an
incompatible schema rollback, restore the verified pre-release backup into a new
database/media location, rehearse it, then explicitly change the protected
configuration during maintenance. Retain the original data for investigation.

Measure these gates on isolated or authorized systems:

- Restore: database integrity/FK checks pass, table and representative record
  counts match the snapshot, media hashes match, migrations are applied, project
  IDOR remains denied, private exports remain authorized, and the recovered
  process can sign in/create/read work. Record snapshot age and elapsed recovery
  time to measure RPO and RTO.
- Concurrency: use the existing five-client deployment verifier as a smoke check,
  then a realistic pilot load against an isolated dataset. Record request count,
  status distribution, latency percentiles, query/DB contention, memory, queue
  lag and throughput. Agree a target before testing and compare the measured
  result. Public home/health requests alone do not demonstrate authenticated task
  editing, calendar generation or worker capacity.
- Failure recovery: stop/restart the worker, confirm stale readiness and fresh
  recovery; simulate transport failure using a test mail backend; corrupt a copy
  of a backup and verify refusal; attempt restore into an existing directory and
  confirm it is unchanged. Never perform outage/corruption drills on the live
  database or on the sole backup copy.

Keep actual results under `var/` or an approved private evidence store. Test
records and configuration templates are distinguishable from production
evidence. Do not store tokens, student messages, email addresses or credentials
in shared benchmark reports.


## Automatic backups and freshness checks

`manage.py scheduled_backup` creates a new timestamped directory under
`BACKUP_ROOT`, includes media, validates every manifest hash and the database,
and records a successful backup heartbeat only after verification. Failure
preserves the previous success. It never replaces or prunes existing backups.
The moderator operations page reports whether the latest verified snapshot is
within `BACKUP_MAX_AGE_HOURS` (default 30). Local SQLite transactions use
IMMEDIATE mode so web and worker writes acquire locks before read/write upgrades;
a temporary worker database error closes its connection and retries with a
bounded backoff without killing the web process.

```powershell
.\.venv\Scripts\python.exe manage.py scheduled_backup
.\.venv\Scripts\python.exe manage.py check_runtime_health --require-worker --require-backup
```

For the prepared Linux host, install `deployment/systemd/studycrew-backup.service`
and `.timer`, and `studycrew-health.service` and `.timer`. The backup timer runs
daily at 03:00 UTC with up to ten minutes of jitter and catches missed runs after
boot. The health timer checks the worker and backup every five minutes; missing
or stale backups make the check exit nonzero. Configure the host's existing
monitor to alert on failed units and stale checks. Create the protected backup
directory first; if changing `BACKUP_ROOT`, also change the backup unit's
`ReadWritePaths`. These units are prepared configuration and have not been
activated on a production Linux host.

Protect backups as sensitive student data. Keep the backup directory outside
MEDIA_ROOT and private to the service account. Arrange encrypted off-host
retention and rehearse recovery from that destination before accepting public
users. The optional [off-host transfer template](../deployment/scripts/backup-offhost.md)
provides a verified-snapshot, age encryption and immutable rclone transfer boundary;
its cloud credentials and remote restoration still require external acceptance.
PostgreSQL archive listing verifies structure; only a real isolated
PostgreSQL restore demonstrates recoverability. A media file copy can race
concurrent uploads or expiry: quiesce writes/worker cleanup or use a coordinated
filesystem snapshot for a release backup, and check referenced media in the
restored application. Backup success alone is not an RPO/RTO or capacity SLA.

The versioned entry bundle and lazy page chunks are checked during `npm run build`
to prevent a lazy page from loading a second unversioned application root.
Account and bearer-link pages use an origin-only referrer policy, avoiding secret
paths in referrers while preserving browser same-origin form submissions. Proxy
and application logging redact joining, subscription, recovery, support and
nested login redirect tokens.

## Private project uploads and local assignment exchange

See [the local expansion acceptance](advance-local-expansion.md) for implemented
recruiting, private-file and CSV exchange workflows. Production settings now
require `PROJECT_FILES_REQUIRE_SCAN=true` and a discoverable
`PROJECT_FILES_CLAMSCAN` executable, normally `/usr/bin/clamscan`. Install ClamAV,
update its signature database through the host's package/service workflow, and
perform a real harmless upload plus an approved antivirus test fixture before
opening student uploads. Scanner errors fail closed. Local development displays
unscanned files explicitly; its format validation is not antivirus or CDR.

The reviewed Nginx configuration keeps the 3 MiB global body limit and grants a
12 MiB allowance only to `/api/v1/files/`. Django bounds the actual file stream,
rejects multiple files, and enforces retained-version and per-user quotas. CSV
previews have a separate 256 KiB file limit. Private files use UUID paths outside
public static routes; every download rechecks current membership and integrity.

Private preview supports PDF rendered locally on a canvas, PNG/JPEG and UTF-8
TXT/CSV. Text previews show at most 512 KiB and disclose truncation. Inline
version comparison supports only UTF-8 TXT/CSV, with a 256 KiB limit per version,
2,000 lines and 5,000 characters per line; other permitted upload formats remain
download-only. Previews and comparisons repeat authorization and integrity
checks and are not cached by the Service Worker. Deleted files immediately lose
download access and remain in a 30-day recycle bin. Only the author or a current
project manager may restore an intact retained file before expiry; archived
projects are read-only and files retired after account closure cannot be restored.

Reapply `deployment/postgresql/launch-permissions.sql` and its read-only verifier
after migrations. The necessary DELETE grants cover bookmarks, transient import
previews, retired file metadata/versions/tags, daily usage counters, chat presence
(`project_chat_chatpresence`) and offline synchronization receipts
(`offline_sync_tasksyncreceipt`). The
immutable audit tables retain their restrictions.

The worker clears expired assignment previews. `purge_private_files` is a dry
run until `--apply`; it deletes only files removed more than 30 days ago and
preserves active documents. Install the prepared
`deployment/systemd/studycrew-private-file-cleanup.service` and `.timer` to run
this cleanup daily at 04:00 UTC. Back up and verify referenced media before
enabling retention jobs. These units, ClamAV and PostgreSQL grants still need
real host acceptance; the local browser and SQLite drill do not verify them.

## Recurring tasks, time records and project chat

Weekly/monthly schedules use an explicit IANA timezone and saved local deadline,
with 0–30 days of lead time, at most 520 occurrences and an end within ten years.
Monthly deadlines clamp to the last day of shorter months. Repeated DST times
use the first occurrence; nonexistent times shift forward. Each generated task
copies the saved title, description, priority, estimate, tags, acceptance and
checklist text. Completion, review, dependencies, parent and official assignment
deadlines reset; only current eligible assignees transfer. Stopping a schedule
retains already-created tasks. The snapshot does not track later source edits.

Time recording permits one running timer per person, completed entries up to
24 hours, manual entries and owner correction/cancellation. Personal notes stay
private. Workload uses recorded completed time, open-task estimates and deadline
buckets; running timers are excluded. Estimates for shared tasks are divided
equally, and unassigned work is shown separately. These are self-recorded facts,
not grades or member quality scores.

Project chat uses HTTP polling every 2 seconds in the foreground and every
10 seconds in a hidden tab; no WebSocket server is required. Presence pulses
every 15 seconds while visible and shows eligible teammates seen within
35 seconds. Sending uses a retained nonce for transport retries. Each request
checks membership, removed/blocked content is hidden, and archived chat is
read-only. The runtime-role grants for new presence and sync-receipt deletion
have prepared SQL and local configuration checks, but have not been executed
against a real PostgreSQL role. Reapply and verify them after migrations.

Team recommendations use only the requesting student's own course/profile
preferences and publicly consented card fields. They explain matches and disclose
their latest-200-candidate window. They do not infer student ability or a team
quality score.

## Explicitly selected offline task edits

Offline tasks require the signed-in student to enable device copies and select
each task while connected. Copies live in this browser's IndexedDB, up to
200 tasks and 50 pending task edits, with a 24-hour lifetime. They cover title,
description, priority, deadline, status and blocker note only. Files, chats and
the whole private workspace are not copied. The Service Worker caches public
code and a generic offline shell, never API responses.

Reconnection verifies the server account and sends its saved `expected_user_id`
with each mutation, checks current membership and task revision, and enforces
normal dependency/review/status rules. A conflict displays local/server values
and lets the student select each field to keep; unselected fields retain the
server value. Retries preserve the mutation identifier after transport uncertainty,
and responses for older edits cannot clear a newer edit. Authorization failure
or disappearance removes that task copy. Sign-out, session expiry and verified
account switching clear local copies. Remote changes cannot erase an offline
device immediately; that device checks them when it reconnects. The 7-day server
receipt retention is independent of the 24-hour device-copy lifetime.

The current automated acceptance on 2 October 2026 passed 836 backend tests with
91.8% combined coverage with branch measurement enabled (93.6% statements,
83.9% branches) and 36 frontend files/213 tests, plus migration consistency,
strict zero-warning API schema generation, type checking and production build.
The integrated browser run passed all seven enhancement flows, including actual
PDF canvas/image/text previews, two-account chat refresh and withdrawal, offline
reload/edit/field conflict resolution and sign-out removal of device copies.
Five mobile routes at 390 pixels had no page overflow or unexpected browser
errors. The new isolated SQLite restore compared 98 tables, 969 rows and
21 manifest files including media, with schema and all row fingerprints matching;
all seven restored runtime checks passed. Its 0.141-second file recovery and
comparison measurement is not a disaster-recovery RTO. See
[the local acceptance document](advance-local-expansion.md).
Evidence is kept under `var/advance-enhancements-*.log`,
`var/advance-qa/enhancements-ui-result.json` and
`var/advance-enhancements-restore/`. The normal local database has also received
the new migrations and is available on 8003. Production PostgreSQL, ClamAV, Linux
scheduling and public-service acceptance remain separate from local SQLite checks.
