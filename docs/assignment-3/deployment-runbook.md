# StudyCrew AWS deployment runbook

This runbook targets the Assignment 3 learner-lab constraint: one Ubuntu EC2
instance with approximately 1 vCPU, 1 GiB RAM and 8 GiB storage. Replace values
inside angle brackets; never paste a password into a command.

## 1. Create the instance and network boundary

1. Launch Ubuntu Server LTS with the required learner-lab instance size and an
   8 GiB root volume.
2. Attach an Elastic IP if the lab permits it and point the chosen DNS name to
   that address.
3. Configure the AWS security group:

   | Port | Protocol | Source | Purpose |
   |---:|---|---|---|
   | 22 | TCP | each team member's current public IP `/32` | key-only SSH |
   | 80 | TCP | `0.0.0.0/0`, `::/0` | certificate validation and HTTPS redirect |
   | 443 | TCP | `0.0.0.0/0`, `::/0` | application HTTPS |

   Do not expose PostgreSQL port 5432. The database listens on loopback only.
4. Keep the downloaded AWS private key on the local computer. Never copy it to
   EC2 or commit it. Apply its local file permissions before connecting.

## 2. Install only the required server packages

Connect as Ubuntu's default account, then run:

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install python3-venv python3-dev build-essential libpq-dev \
  postgresql postgresql-client nginx certbot ufw git
sudo adduser --system --group --home /srv/studycrew studycrew
sudo chown studycrew:www-data /srv/studycrew
sudo chmod 0750 /srv/studycrew
sudo install -d -o studycrew -g www-data -m 0750 /srv/studycrew/app
sudo install -d -o studycrew -g studycrew -m 0750 /srv/studycrew/venv
sudo install -d -o studycrew -g www-data -m 0750 /srv/studycrew/app/var
sudo install -d -o root -g studycrew -m 0750 /etc/studycrew
```

The production server does not require Node.js. The reviewed frontend bundle in
`static/workspace/` is built and checked by CI before deployment.

## 3. Install the reviewed release

Clone the public/team repository over HTTPS. A deploy private key must not be
placed on the server.

```bash
sudo -u studycrew git clone <HTTPS_REPOSITORY_URL> /srv/studycrew/app
sudo -u studycrew python3 -m venv /srv/studycrew/venv
sudo -u studycrew /srv/studycrew/venv/bin/pip install --upgrade pip
sudo -u studycrew /srv/studycrew/venv/bin/pip install \
  -r /srv/studycrew/app/requirements/production.txt
test -f /srv/studycrew/app/static/workspace/main.js
```

## 4. Create separate PostgreSQL roles

Both `createuser` commands prompt for the new password without putting it in
shell history. Use two different randomly generated passwords.

First bind PostgreSQL to loopback and select SCRAM password storage. These
settings prevent network exposure even if a future firewall rule is too broad.

```bash
sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
ALTER SYSTEM SET listen_addresses = '127.0.0.1,::1';
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
SQL
sudo systemctl restart postgresql
sudo -u postgres psql -c "SHOW listen_addresses"
sudo -u postgres psql -c "SHOW password_encryption"
```

Generate each password in a password manager. If one is unavailable, this
command prints a URL-safe random value while keeping the value itself out of
shell history:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Then paste the values only into the hidden prompts:

```bash
sudo -u postgres createuser --login --no-createdb --no-createrole \
  --no-superuser --pwprompt studycrew_migrator
sudo -u postgres createdb --owner=studycrew_migrator studycrew
sudo -u postgres createuser --login --no-createdb --no-createrole \
  --no-superuser --pwprompt studycrew_app
```

`studycrew_migrator` owns schema changes but is never used by the web service.
`studycrew_app` is the restricted runtime identity.

## 5. Create the root-controlled environment file

Copy the template, edit it through `sudoedit`, and replace every `CHANGE_ME`.
Generate long random values with a password manager or a command that prints a
value without embedding it in history.

```bash
sudo install -o root -g studycrew -m 0640 \
  /srv/studycrew/app/deploy/studycrew.env.example \
  /etc/studycrew/studycrew.env
sudoedit /etc/studycrew/studycrew.env
sudo stat -c '%U %G %a %n' /etc/studycrew/studycrew.env
```

The environment must use the `studycrew_app` password, the real HTTPS hostname,
a unique 50+ character Django secret and working SMTP credentials. SMTP is
required because every login completes email OTP verification. Keep values
inside the template's single quotes and use URL-safe generated secrets so the
file remains valid for both systemd and the controlled deployment scripts.

## 6. Migrate, collect static files and restrict the runtime role

The migration helper requests the migration password using hidden input and
holds it only in the child process environment.

```bash
sudo bash /srv/studycrew/app/deploy/scripts/migrate-production.sh
sudo -u postgres psql -d studycrew -v ON_ERROR_STOP=1 \
  -f /srv/studycrew/app/deploy/postgresql/permissions.sql
sudo chown -R studycrew:www-data /srv/studycrew/app/var
sudo find /srv/studycrew/app/var -type d -exec chmod 0750 {} +
sudo find /srv/studycrew/app/var -type f -exec chmod 0640 {} +
```

The SQL grants `SELECT`, `INSERT` and `UPDATE` to application tables, grants hard
`DELETE` only for session rotation, task-assignment replacement and consumption
or cleanup of pending email-change verification requests, denies
database/schema/temporary-object creation, removes update/delete rights from
both audit tables, and adds triggers that reject audit-row mutation even if
grants are accidentally widened later.

Create the least-privilege custom-site moderator through the supplied hidden
password prompt. Do not use `seed_demo` or a simple shared account in production.

```bash
sudo bash /srv/studycrew/app/deploy/scripts/run-production-management.sh \
  create_site_moderator --email <MODERATOR_EMAIL> \
  --display-name '<MODERATOR_DISPLAY_NAME>'
```

The command applies the same 12-character complexity/common-password policy as
registration and grants only the two permissions used by `/control/`. Never put
a password in this command or any other command argument.

## 7. Install and start uWSGI under systemd

```bash
sudo install -o root -g root -m 0644 \
  /srv/studycrew/app/deploy/systemd/studycrew.service \
  /etc/systemd/system/studycrew.service
sudo systemctl daemon-reload
sudo systemctl enable --now studycrew
sudo systemctl status studycrew --no-pager
sudo journalctl -u studycrew -n 50 --no-pager
```

The service runs as the unprivileged `studycrew` user, creates a protected Unix
socket, starts automatically, restarts on failure and uses systemd filesystem
and kernel hardening. Two processes with three threads provide six request
threads while keeping process memory suitable for the small instance.

## 8. Obtain TLS and enable Nginx

Confirm DNS first. Start with the supplied HTTP-only bootstrap configuration,
then use Certbot's webroot method. This avoids the port-80 conflict caused by
the standalone plugin and leaves an automatically renewable configuration.

```bash
sed 's/__DOMAIN__/<DOMAIN>/g' \
  /srv/studycrew/app/deploy/nginx/studycrew-bootstrap.conf | \
  sudo tee /etc/nginx/sites-available/studycrew >/dev/null
sudo ln -s /etc/nginx/sites-available/studycrew /etc/nginx/sites-enabled/studycrew
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo certbot certonly --webroot -w /var/www/html \
  -d <DOMAIN> --email <TEAM_EMAIL> \
  --agree-tos --no-eff-email
sed 's/__DOMAIN__/<DOMAIN>/g' \
  /srv/studycrew/app/deploy/nginx/studycrew.conf | \
  sudo tee /etc/nginx/sites-available/studycrew >/dev/null
sudo install -o root -g root -m 0755 \
  /srv/studycrew/app/deploy/scripts/reload-nginx-after-cert-renewal.sh \
  /etc/letsencrypt/renewal-hooks/deploy/reload-nginx-after-cert-renewal
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
```

Nginx redirects HTTP, terminates TLS, sends dynamic requests through the Unix
socket, serves collected static files, and serves private avatars and exports
only through an internal `X-Accel-Redirect` after Django authorisation. Source, environment,
key, database, backup and dotfile paths return 404. The renewal hook first tests
the Nginx configuration and reloads it only after Certbot renews successfully.

The HTTP request-body cap is 3 MiB so a valid 2 MiB avatar plus multipart
boundaries and form fields is not rejected by Nginx. This does not increase the
avatar-file limit: Django separately rejects files larger than 2 MiB and decodes
and re-encodes accepted images. Do not expose `/media/` or remove `internal` from
`/protected-media/`; avatar URLs must go through the authenticated API.

## 9. Apply host and SSH firewall controls

Keep the current SSH session open until a second terminal has proved key login.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <TEAM_MEMBER_PUBLIC_IP> to any port 22 proto tcp
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status verbose
sudoedit /etc/ssh/sshd_config.d/00-studycrew.conf
```

Enter the following SSH settings:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
AuthenticationMethods publickey
```

Validate, reload, then open a second terminal from the local computer with the
AWS key. Only after that succeeds should the original session be closed.

```bash
sudo sshd -t
sudo sshd -T | grep -E \
  '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication|authenticationmethods) '
sudo systemctl reload ssh
```

Expected effective values are `passwordauthentication no`,
`kbdinteractiveauthentication no`, `permitrootlogin no`,
`pubkeyauthentication yes` and `authenticationmethods publickey`. The `00-`
prefix makes these settings take precedence because OpenSSH uses the first value
it obtains for most settings.

Verify that no private key exists on EC2:

```bash
sudo find /home /root /srv -xdev -type f \
  \( -name '*.pem' -o -name '*.ppk' -o -name '*.key' -o \
     -name 'id_rsa' -o -name 'id_dsa' -o -name 'id_ecdsa' -o \
     -name 'id_ed25519' \) -print
```

The expected output is empty. Do not delete anything blindly if it is not.

## 10. Reboot and acceptance evidence

Reboot is part of acceptance, not an optional check.

```bash
sudo reboot
```

Reconnect and capture the following evidence:

```bash
systemctl is-active nginx studycrew postgresql
systemctl is-enabled nginx studycrew postgresql
sudo ss -lntup
curl -I http://<DOMAIN>/
curl -I https://<DOMAIN>/
curl https://<DOMAIN>/api/v1/health/
python3 /srv/studycrew/app/deploy/scripts/verify_deployment.py \
  https://<DOMAIN>
```

The verifier checks a valid HTTPS connection, same-host HTTP redirect, security
headers and cookie flags, direct Nginx static delivery, blocked sensitive paths,
safe errors, database health and 50 requests from five simultaneous simulated
users. Preserve its JSON output for the report.

For the required terminal database frontend, connect using the runtime role and
let `psql` prompt for its password:

```bash
psql -h 127.0.0.1 -U studycrew_app -d studycrew
```

Inside `psql`, show `\dt`, run a harmless `SELECT`, then collect explicit
least-privilege evidence:

```sql
SELECT current_user, current_database();
SELECT has_database_privilege(current_user, current_database(), 'CREATE') AS can_create_database_object;
SELECT has_database_privilege(current_user, current_database(), 'TEMP') AS can_create_temp_table;
SELECT has_schema_privilege(current_user, 'public', 'CREATE') AS can_create_in_public;
SELECT has_table_privilege(current_user, 'projects_project', 'DELETE') AS can_hard_delete_projects;
SELECT has_table_privilege(current_user, 'django_session', 'DELETE') AS can_rotate_sessions;
SELECT has_table_privilege(current_user, 'accounts_pendingemailchange', 'DELETE') AS can_consume_email_change;
SELECT has_table_privilege(current_user, 'activity_activityevent', 'UPDATE,DELETE') AS can_mutate_activity_audit;
BEGIN;
ALTER TABLE projects_project ADD COLUMN forbidden_test integer;
ROLLBACK;
```

Database `CREATE`/`TEMP`, schema `CREATE`, project `DELETE` and audit
`UPDATE`/`DELETE` capability results must be false; the session and pending-email
deletion checks are true. `ALTER TABLE`
must be denied. Run the supplied read-only catalogue check as the runtime role
as well (its password is requested by `psql`, not included in the command):

```bash
psql -X -W -h 127.0.0.1 -U studycrew_app -d studycrew -v ON_ERROR_STOP=1 \
  -f /srv/studycrew/app/deploy/postgresql/verify_runtime_permissions.sql
```

For profile acceptance, use an account with a mailbox you control: change the
email and consume the code once; confirm a replay is rejected. Upload a valid
image at or just below 2 MiB and confirm that it loads through the avatar API.
An image over 2 MiB must be rejected without replacing the saved image. A
project teammate may view the avatar; an unrelated account and direct
`/protected-media/avatars/...` requests must not receive it. Record these checks
against the real HTTPS/Nginx/PostgreSQL deployment, not just the local server.

Also perform the required five-person live exercise: have five accounts sign in, open project
pages and simultaneously change distinct tasks/RSVPs while watching the Nginx
and StudyCrew logs for errors. The automated verifier is supporting evidence,
not a substitute for this functional check.

## 11. Safe release updates

```bash
sudo -u studycrew git -C /srv/studycrew/app pull --ff-only
sudo -u studycrew /srv/studycrew/venv/bin/pip install \
  -r /srv/studycrew/app/requirements/production.txt
sudo bash /srv/studycrew/app/deploy/scripts/migrate-production.sh
sudo -u postgres psql -d studycrew -v ON_ERROR_STOP=1 \
  -f /srv/studycrew/app/deploy/postgresql/permissions.sql
sudo systemctl restart studycrew
sed 's/__DOMAIN__/<DOMAIN>/g' \
  /srv/studycrew/app/deploy/nginx/studycrew.conf | \
  sudo tee /etc/nginx/sites-available/studycrew >/dev/null
sudo nginx -t
sudo systemctl reload nginx
python3 /srv/studycrew/app/deploy/scripts/verify_deployment.py \
  https://<DOMAIN>
```

If verification fails, keep the database intact, inspect the service journal,
and return the application checkout to the previously reviewed release commit.
Never use a destructive database reset as rollback.

Updating this profile release requires all three parts: apply migrations before
the permission script (it references `accounts_pendingemailchange`), restart the
application, and install/test/reload the updated Nginx configuration. Reloading
an old configuration alone will not change its upload cap. Re-run the read-only
runtime permission check and the profile acceptance checks after the update.

## 12. Report only observed production facts

Record the actual EC2 instance type, Ubuntu release, vCPU/RAM, EBS size, public
hostname, security-group rules and release commit (`git rev-parse HEAD`). Capture
annotated screenshots of TLS, static loading, the reboot checks, the verifier,
the five-user exercise, `psql` permissions, effective SSH settings and the
private-key search. Do not mark an item complete from this runbook alone.

The intended fault-tolerance statement is deliberately modest: this learner-lab
deployment uses one EC2 instance, no separate AWS load balancer and no multi-AZ
failover. Nginx fronts a six-thread uWSGI pool; systemd restarts failures and
restores Nginx, uWSGI and PostgreSQL after reboot. Describe those limits honestly
instead of claiming infrastructure that was not deployed.
