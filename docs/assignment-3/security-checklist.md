# Assignment 3 security and deployment acceptance checklist

This checklist deliberately separates repository readiness from facts that can
only be proved on the team's AWS instance. A checked repository item means that
the reviewed implementation exists and is covered by configuration or tests; it
does **not** claim that the production host has already been configured.

## Repository readiness

- [x] Production settings reject `DEBUG=True`, weak/default secrets, wildcard
      hosts, non-HTTPS trusted origins, non-PostgreSQL databases, missing SMTP
      credentials and non-proxied private downloads.
- [x] Nginx templates provide HTTP-to-HTTPS redirect, TLS 1.2/1.3, security
      headers, direct static delivery, authorised internal media delivery, and
      explicit denial rules for source, keys, databases, backups and dotfiles.
- [x] uWSGI is configured behind a Unix socket with six request threads, bounded
      request lifetimes and worker recycling suitable for the learner-lab VM.
- [x] The systemd unit runs as an unprivileged user, restarts on failure, starts
      at boot and restricts filesystem, device and kernel access.
- [x] PostgreSQL setup uses separate migration and runtime roles. The runtime
      grant script denies schema creation and all hard deletes except session
      invalidation and task-assignment replacement; both audit tables are
      append-only by grants and triggers.
- [x] Passwords use Argon2 plus a 12-character complexity policy for ordinary
      users and site moderators. Login lockout, email OTP MFA, idle timeout and
      server-side logout invalidation are implemented.
- [x] Django/DRF enforce CSRF, completed MFA, active accounts and project-level
      object permissions. Tests cover cookie/session tampering, IDOR, XSS-safe
      rendering, ORM-handled SQL-like input, CSRF and safe error responses.
- [x] Deployment helpers keep passwords out of command arguments, load secrets
      from a root-controlled environment file and prompt invisibly for the
      migration role password.
- [x] The deployment verifier checks TLS, redirect, security headers, cookie
      flags, static delivery, sensitive-path denial, safe 404s, database health
      and 50 requests from five simultaneous simulated users.

## AWS evidence required before submission

- [ ] Record the actual Ubuntu version, EC2 instance type, vCPU/RAM, 8 GiB EBS
      volume, Elastic IP/DNS name and deployed Git commit.
- [ ] Capture AWS security-group and UFW evidence showing only 22, 80 and 443;
      restrict port 22 to each team member's current public `/32` where possible.
- [ ] Prove a valid HTTPS certificate, HTTP redirect and successful
      `certbot renew --dry-run` on the real hostname.
- [ ] After a real reboot, prove Nginx, StudyCrew and PostgreSQL are both enabled
      and active without manual intervention.
- [ ] Run `manage.py check --deploy` with the production environment and retain
      the clean output; also confirm that production errors expose no traceback.
- [ ] Run `verify_deployment.py https://<DOMAIN>` and retain its passing JSON
      output, including all 50/50 concurrent requests.
- [ ] Complete the separate five-person functional exercise: five accounts sign
      in and simultaneously use distinct task or meeting workflows without an
      application or Nginx error.
- [ ] Use `psql` as `studycrew_app` to show the schema and prove that CREATE,
      ALTER, DROP, broad DELETE and audit UPDATE/DELETE are denied while normal
      application writes still succeed.
- [ ] Prove effective SSH settings disable password, keyboard-interactive and
      root login; prove a second key-only SSH session before closing the first.
- [ ] Search `/home`, `/root` and `/srv` for private-key file patterns and retain
      the expected empty result. Do not place the AWS private key on EC2.
- [ ] Verify `/etc/studycrew/studycrew.env` is `root:studycrew` mode `0640` and
      capture only its ownership/mode, never its secret contents.
- [ ] Annotate screenshots/logs in the Canvas A3 template and state the honest
      single-instance limitation: systemd recovery and a six-thread pool, but no
      multi-AZ failover or external load balancer.

Follow [deployment-runbook.md](deployment-runbook.md) in order. Do not check a
live item until its evidence has been observed on the final assessed instance.
