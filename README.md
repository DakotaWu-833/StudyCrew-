# StudyCrew

StudyCrew is a private collaboration workspace for university project teams. It
combines project membership, a task board, meeting coordination and factual
contribution evidence so a team can find delivery risk early without turning
activity counts into grades.

This repository contains the complete Assignment 2 implementation and the
reviewed Assignment 3 deployment/security configuration. Assignment 1 design
artifacts remain under `design/`, `database/` and `deliverables/`.

## Implemented functionality

- Email registration and login with 12-character password rules, Argon2 hashes,
  persistent account/IP lockout, expiring single-use email OTP and idle session
  expiry.
- Personal profile and IANA time-zone preference.
- Project creation, expiring email invitations, member/facilitator roles,
  removal and explicit ownership transfer.
- Task CRUD, filters, multi-member assignment, guarded status transitions and
  soft archive.
- Plain-text task comments, author editing/deletion, reporting and a separately
  permissioned moderation centre.
- Ten-year-bounded meeting scheduling, RSVP counts, explicit cancellation,
  terminal-state archival and a cached Australian public-holiday advisory
  fetched only by the backend from Nager.Date.
- Append-only activity evidence, accessible factual contribution charts and
  tables, in-app notifications, owner/facilitator email reminders, and
  authorised CSV/PDF exports.
- A responsive React workspace with query caching and client routing; security
  and account pages remain server-rendered Django views.
- A custom `/control/` site panel. Django's developer admin is deliberately not
  exposed.

The application has 18 meaningful domain/security tables, including one-to-one,
one-to-many and explicit many-to-many relationships. Django's built-in session,
permission and content-type tables are not included in that count.

## Architecture

```text
Browser
├── Django templates: public, registration, password, OTP, error, control pages
└── React + TypeScript workspace
    └── /api/v1 JSON API (session + MFA marker + CSRF)
        └── authorised selectors and transactional domain services
            ├── Django ORM → SQLite locally / PostgreSQL in production
            ├── append-only activity and site-audit evidence
            └── fixed Nager.Date endpoint → validated year cache → safe fallback
```

Business rules live in each app's `services.py`, read queries in `selectors.py`,
and object access rules in `policies.py`. Views and serializers translate HTTP
only; templates and signals do not hide domain mutations.

## Technology versions

Recommended runtimes are Python 3.12 and Node.js 22. The project pins direct
dependencies for reproducible marking.

| Backend | Version | Frontend | Version |
|---|---:|---|---:|
| Django | 5.2.17 LTS | React / React DOM | 19.3.0 |
| Django REST framework | 3.18.1 | React Router DOM | 7.18.3 |
| drf-spectacular | 0.30.0 | TanStack React Query | 5.102.8 |
| psycopg | 3.3.5 | TypeScript | 7.0.2 |
| httpx | 0.28.1 | Vite | 8.3.0 |
| Argon2 | 25.1.0 | Vitest | 5.0.0 |
| ReportLab | 5.0.1 | jsdom | 30.0.1 |
| coverage.py | 7.16.0 | | |
| uWSGI (production) | 2.0.30 | | |

## Local setup

### 1. Backend

From the repository root on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
.\.venv\Scripts\python.exe manage.py migrate
```

On Linux/macOS, use `python3 -m venv .venv` and `.venv/bin/python` for the same
commands. Local development defaults to SQLite and the file email backend, so no
secret or external service is required.

### 2. Frontend

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ..
```

The production bundle is written to `static/workspace/`. Django serves it during
development and `collectstatic` prepares it for Nginx in production.

### 3. Demo data and server

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver
```

`seed_demo` creates a realistic four-person project and prints cryptographically
random demo passwords only when accounts are first created. It is idempotent.
Use `seed_demo --reset-passwords` to generate replacements without placing a
password in command history.

Open `http://127.0.0.1:8000/`. After the password step, read the newest message
under `var/emails/` for the six-digit local OTP. `var/` and all secrets are
ignored by Git.

## Configuration

Development works with safe defaults. `.env.example` is a reference list; this
project intentionally does not silently load `.env` files. Set environment
variables in the process manager or current shell when overriding defaults.

Important variables:

| Variable | Purpose |
|---|---|
| `DJANGO_ENVIRONMENT` | `development` or fail-closed `production` |
| `DJANGO_SECRET_KEY` | unique random signing key; production requires 50+ characters |
| `DJANGO_ALLOWED_HOSTS` | explicit comma-separated hostnames; wildcard is rejected |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | explicit HTTPS origins in production |
| `DB_ENGINE` | `sqlite` locally; production requires `postgresql` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | database connection |
| `EMAIL_*` | SMTP delivery for production OTP; file backend locally |
| `SESSION_IDLE_TIMEOUT_SECONDS` | inactivity expiry, default 1800 seconds |
| `LOGIN_FAILURE_*` | persistent account/IP failure window and lock duration |
| `OTP_TTL_SECONDS`, `OTP_MAX_ATTEMPTS` | OTP expiry and attempt bound |
| `EXTERNAL_API_TIMEOUT_SECONDS` | Nager.Date request timeout, default 3 seconds |
| `NAGER_DATE_CACHE_TTL_SECONDS` | holiday cache lifetime, default 86400 seconds |
| `USE_X_ACCEL_REDIRECT` | protected Nginx hand-off for production exports |

Production refuses to start with debug mode, SQLite, weak/default secrets,
wildcard hosts, missing HTTPS CSRF origins, non-SMTP mail or public media export
handling.

## API

The versioned base is `/api/v1/`; the generated OpenAPI contract is
`docs/assignment-2/openapi.yml`. Major resource families include:

- `/projects/`, `/memberships/`, `/invitations/`
- `/tasks/`, `/comments/`
- `/meetings/`
- `/notifications/`, `/exports/`
- `/projects/{id}/activity/` and `/projects/{id}/insights/`

Normal resources use `GET`, `POST`, `PUT`, `PATCH` and `DELETE` as applicable.
Deletes soft-archive collaboration records rather than destroying evidence;
meeting cancellation is the explicit `POST /meetings/{id}/cancel/` transition.
Authentication uses the same server-side session established after email OTP;
unsafe requests must send the CSRF cookie value as `X-CSRFToken`.

All JSON errors use one stable shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Please correct the highlighted fields.",
    "fields": {"title": ["This field is required."]}
  }
}
```

See `docs/assignment-2/api.md` for endpoint and request examples.

## Quality gates

Run the same checks as CI:

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py spectacular --file docs\assignment-2\openapi.yml --validate
.\.venv\Scripts\coverage.exe run manage.py test
.\.venv\Scripts\coverage.exe report --fail-under=85
Set-Location frontend
npm test
npm run typecheck
npm run build
```

Tests cover successful, invalid, permission, IDOR, XSS-as-text, SQL-injection
input, CSRF, MFA/session tampering, transaction rollback, cache failure and
export authorisation paths. The coverage configuration excludes migrations,
tests and framework bootstrap files rather than inflating results with generated
code. See `docs/assignment-2/test-plan.md` for the access matrix and evidence
plan.

Verified on 29 September 2026: 318 Django tests, 96.3% branch coverage (86.0%
minimum among reported key files), 6 files/31 Vitest cases, zero-warning OpenAPI
validation, TypeScript checking and a production build all passed. An executable
architecture test also prevents domain-to-HTTP imports,
external HTTP outside `integrations/` and direct frontend API calls outside the
shared client.

## Production deployment

The complete learner-lab procedure is in
[`docs/assignment-3/deployment-runbook.md`](docs/assignment-3/deployment-runbook.md).
Use the separate [security checklist](docs/assignment-3/security-checklist.md)
and [report evidence guide](docs/assignment-3/report-evidence-guide.md) while
collecting the final AWS evidence. Reviewed artifacts include:

- Nginx HTTPS redirect, TLS, sensitive-path denial, static serving and protected
  media hand-off.
- A hardened, auto-starting systemd/uWSGI service sized for the small EC2 host.
- Separate PostgreSQL migration/runtime roles, least-privilege grants and
  immutable-audit database triggers.
- A hidden-input migration helper and a five-concurrent-client HTTPS verifier.
- UFW, AWS security-group, key-only SSH, reboot and terminal `psql` evidence
  procedures.

Repository checks can prove the configuration and application behavior, but the
team must still capture the real hostname, certificate, EC2 reboot, firewall,
`psql` and concurrency output from its own AWS Learner Lab before submission.

## Repository map

| Path | Contents |
|---|---|
| `accounts/` | identity, MFA, lockout, sessions and profile |
| `projects/` | projects, invitations, roles and ownership |
| `tasks/` | tasks, assignments, comments and reports |
| `meetings/` | bounded scheduling, lifecycle, attendance and reminders |
| `activity/` | append-only evidence, insights, notifications and exports |
| `integrations/` | resilient Nager.Date cache and private email-delivery boundaries |
| `api/` | REST authentication, serializers, views, errors and schema |
| `web/` | public shell and custom moderation centre |
| `frontend/` | React/TypeScript source and tests |
| `deploy/` | Nginx, uWSGI, systemd, PostgreSQL and verification assets |
| `docs/assignment-2/` | rubric, API, testing and demo evidence |
| `docs/assignment-3/` | deployment and security evidence |

## Deliberate scope limits

- Contribution figures are factual counts, never grades or quality scores.
- Public-holiday advice is Australian and advisory; meeting creation still works
  when the provider or cache is unavailable.
- CSV/PDF export is synchronous and limited to a 366-day course-scale dataset.
- Modern Web option 1 is used; WebSocket functionality is intentionally absent.
- Account recovery and LMS integration are outside the approved scope.
