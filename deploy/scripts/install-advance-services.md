# Install advance services on the prepared Ubuntu host

Use `install-advance-services.sh` after installing the release at
`/srv/studycrew/app`, its production dependencies and PostgreSQL clients, Nginx,
ClamAV with current signatures, and a valid TLS certificate. The installer does
not provision AWS, install packages, request certificates, change firewall/SSH
rules, migrate a database, or create users.

Prepare `/etc/studycrew/studycrew.env` from
`deployment/studycrew.env.example` privately, root-owned with mode `0600` or
`0640`. Configure the real origin, SMTP, runtime database identity, scanner and
approved model endpoint. Keep secrets out of command arguments. The certificate
must already exist under `/etc/letsencrypt/live/HOST/` and match the DNS name or
IPv4 address passed to the installer. Move the stock Nginx `sites-enabled/default`
link outside `sites-enabled` first, preserving it for rollback.

Before installation, migrate with the migration identity, collect static files,
apply `deploy/postgresql/permissions.sql` followed by
`deployment/postgresql/launch-permissions.sql`, and run the launch permissions
verifier as `studycrew_app`. Use the procedure in `docs/launch-operations.md`.

Run `sudo bash /srv/studycrew/app/deploy/scripts/install-advance-services.sh`
followed by the actual host name or IPv4 address. Add `--enable-backups` to create
an initial verified snapshot and enable daily backups. Add `--enable-health` to
enable the existing worker-and-backup freshness monitor; this requires either
`--enable-backups` or an already fresh backup. These flags do not enable deletion
or retention pruning. PostgreSQL backup requires compatible `pg_dump` and
`pg_restore` clients. Existing optional timers are not disabled when flags are
omitted on a later run.

The installer checks production settings, migration state and database/media
readiness before changing configuration. It composes the reviewed Nginx rules
with private token-route logging, adds the uWSGI privacy override and installs
the independent delivery worker. It validates Nginx before enabling or reloading
services; a failed Nginx check restores the three Nginx files it replaced. It does
not replace `/etc/nginx/nginx.conf` or configure other virtual hosts. Other
service failures stop the installer for investigation.

After installation, check actual HTTPS `/health/`, inbox OTP delivery, file
scanning, model-backed features when enabled, five simultaneous authenticated
users, and recovery after a real reboot. Successful configuration checks alone
do not establish these outcomes. This installer has only been checked locally
for shell syntax; execution still requires acceptance on the Ubuntu host.
