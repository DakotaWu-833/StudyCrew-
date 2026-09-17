# Assignment 3 report evidence guide

Use the official Canvas template for the submitted PDF. This file is a content
and evidence guide so the team can fill that template without missing a marking
criterion. Replace every placeholder with an observed fact; do not submit angle
brackets or claim an unperformed test.

## Deployment summary content

Record:

- deployed release commit: `<GIT_COMMIT>`;
- AWS resource: `<INSTANCE_TYPE>`, `<VCPU>` vCPU, `<RAM>` GiB RAM, Ubuntu
  `<VERSION>`, `<EBS_SIZE>` GiB EBS;
- public origin: `https://<DOMAIN>`;
- network boundary: AWS security group and UFW allow 80/443 publicly and 22 only
  from the documented team addresses; PostgreSQL 5432 is loopback-only;
- request path: browser -> Nginx TLS/reverse proxy -> Unix socket -> uWSGI ->
  Django -> PostgreSQL;
- static/private media path: Nginx serves collected static files directly;
  Django authorises an export before Nginx serves it through an internal route;
- availability: systemd enables Nginx, StudyCrew and PostgreSQL at boot and
  restarts StudyCrew after failure. The uWSGI pool has two processes with three
  threads each. The deployment is one EC2 instance and has no multi-AZ failover
  or separate AWS load balancer.

Suggested evidence: AWS instance/volume page, security-group rules,
`lsb_release -a`, `nproc`, `free -h`, `df -h`, `systemctl is-enabled`, post-reboot
`systemctl is-active`, `ss -lntup`, HTTPS response headers, correctly loaded
static assets, health JSON, and the deployment verifier JSON.

## Security requirement mapping

| # | Implementation to describe | Production evidence to insert |
|---:|---|---|
| 1 | Argon2; Django validators; 12-character upper/lower/digit/symbol policy; the moderator command uses the same validation and hidden prompt. | Redacted moderator creation and rejected weak-password example. |
| 2 | `studycrew_migrator` performs migrations; `studycrew_app` runs the website. SQL revokes CREATE/TEMP and broad DELETE, and makes audit tables append-only. | `psql` role/capability queries plus a denied `ALTER TABLE`; never show passwords. |
| 3 | Nginx TLS 1.2/1.3, port-80 redirect, HSTS and Certbot renewal hook. | Browser certificate view, `curl -I` on HTTP/HTTPS and successful renewal dry run. |
| 4 | Production settings fail closed if debug is enabled. | Production `check --deploy` output and a safe 404/500 response. |
| 5 | Custom HTML error handlers and a stable DRF error envelope hide exception details; logging remains server-side. | Safe invalid-route response and journal excerpt with secrets redacted. |
| 6 | Active membership and role policies protect every project object; ownership transfer and soft removal preserve invariants. | Cross-account forbidden-action demonstration and relevant passing test output. |
| 7 | Django server-side sessions, completed email OTP required by API auth, persistent HMAC-keyed lockout, session cycling and logout deletion. | Modified-cookie/incomplete-MFA rejection test plus a real MFA sign-in/logout. |
| 8 | Django template escaping, React text rendering, ORM queries, serializers, CSRF middleware and `X-CSRFToken` on unsafe AJAX requests. | Passing XSS, SQL-like-input and CSRF tests; CSP/other response headers. |
| 9 | Only static/authorised media aliases are exposed; Nginx denies source, dotfiles, keys, databases and backups; the verifier probes sensitive paths. | 403/404 results for the verifier's sensitive-path list. |
| 10 | Secrets live in a root-owned environment file; database-role creation and management helpers use hidden prompts rather than command arguments. | File ownership/mode and a redacted history inspection. |
| 11 | The runbook keeps the AWS key local and includes a bounded server-side key search. | Empty key-search output from `/home`, `/root` and `/srv`. |
| 12 | OpenSSH disables password, keyboard-interactive and root login and requires public-key authentication. | Effective `sshd -T` settings and successful second key-only connection. |

## Required performance and database evidence

Include both kinds of concurrency evidence:

1. the verifier's five simultaneous workers, five iterations each, two requests
   per iteration: expected result `50/50` with `passed: true`;
2. five real accounts simultaneously performing separate authorised task/RSVP
   actions while service logs remain free of errors.

For terminal database inspection, show `psql`, `\dt`, one harmless `SELECT`, the
capability queries from the runbook and the denied schema change. Explain that
ordinary application INSERT/UPDATE works, task-assignment/session DELETE is
purpose-limited, and domain/audit hard deletion is unavailable to the web role.

## Final evidence hygiene

- Crop screenshots to the relevant result and annotate what the marker should
  notice; retain the command and timestamp where useful.
- Redact public IPs if required by the course, and always redact passwords,
  secret keys, OTPs, cookies, session IDs and private-key material.
- Ensure the report hostname, resource details and commit match the instance
  presented in the lab.
- Put repository configuration snippets beside observed AWS evidence. A config
  file alone proves intent, not successful deployment.
- Export the completed official Canvas template to PDF and inspect every page
  before submission.
