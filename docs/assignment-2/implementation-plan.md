# StudyCrew Assignment 2 implementation plan

This plan converts the Assignment 1 design into a testable Django product. The
assignment brief, Django models/migrations, executable tests and API schema are
the implementation sources of truth. The earlier hand-written SQL remains a
design artefact and is not used to initialise the application.

## Locked decisions

- Django 5.2 LTS and Django REST Framework provide the MVT backend and JSON API.
- PostgreSQL is the production database; SQLite is the zero-configuration local
  default. Both paths are exercised by Django migrations.
- The authenticated workspace uses a small React/TypeScript client built by
  Vite. Public and security-sensitive account flows use Django templates.
- The client calls only the same-origin, versioned `/api/v1/` surface. Internal
  Python code never calls its own HTTP endpoints.
- Business writes live in explicit `transaction.atomic()` services. Views and
  serializers coordinate input/output; they do not duplicate domain rules.
- Core business workflows do not use signals. Audit events and notifications
  are visible calls within the same transaction as the source change.
- Server database sessions are used instead of JWT. Password complexity,
  persistent lockout and email one-time-code MFA are enforced on the server.
- Modern Web option 1 is implemented. WebSocket is deliberately out of scope.
- The only external integration is the Nager.Date public-holiday service. It is
  backend-only, cached, time-bounded and never required to create a meeting.
- Django's developer admin is not mounted. A limited `/control/` panel serves
  authorised site moderators and records every mutation.

## Directed dependency boundaries

```text
Browser UI ──HTTPS/JSON──> web + api (HTTP adapters)
                               │
                               v
                  domain selectors + transaction services
                    │              │              │
                    │              │              └──> integrations
                    │              └──> activity.services (event sink)
                    └──> Django models

activity.insights/exports (read model) ──read only──> project/task/meeting tables
```

The two activity paths are deliberately separate. Write services call the
dependency-light `activity.services` event sink inside their existing database
transaction. The event sink never calls back into a source domain. Conversely,
`activity.insights` is a read-only reporting model that queries source tables;
source domains never invoke it. This prevents callback loops while keeping the
audited write explicit and atomic.

React calls only the versioned same-origin `/api/v1/` contract; Python code does
not call its own HTTP endpoints. `web/` and `api/` are adapters and may depend on
domain modules, while domain code may not import either adapter. Models use
string relationships where appropriate and never import sibling-domain models.
Only `integrations/` may import an external HTTP client. These rules are enforced
by `config/tests/test_architecture.py`, so a future reverse dependency fails CI.

## Delivery stages and exit gates

1. **Foundation** — settings, environment sample, dependencies, safe errors,
   static/media paths and security headers pass `manage.py check`.
2. **Identity and access** — registration, login, logout, profile, password
   policy, rate-limit/lockout and one-time-code MFA pass normal and abuse tests.
3. **Projects** — creation, invitation, membership roles/removal and ownership
   transfer pass transaction and access-control tests.
4. **Collaboration** — task CRUD/archive, assignment, status workflow, plain-text
   comments, meeting CRUD/cancel and RSVP pass model/service tests.
5. **Evidence** — immutable activity, notifications, insights, search and
   authorised CSV/PDF export reconcile with stored rows.
6. **Interfaces** — four resource families expose documented REST CRUD; all
   dynamic workspace actions use Fetch with loading, success and error states.
7. **Administration** — site moderators can review reports and suspend/restore
   users through a custom, permission-limited interface with audit records.
8. **Quality** — migrations are stable, all tests pass, key backend files and the
   total backend exceed 85% meaningful coverage, the production client builds,
   and security/deployment checks are green.
9. **Delivery evidence** — README, API guide, test report, demo seed command,
   deployment runbook and report evidence map are complete and reproducible.

## Definition of done

No stage is complete merely because a page renders. It is complete only when its
normal, boundary, failure, duplicate-request and authorisation tests pass; its
user-visible error is understandable; and its README/report evidence can be
reproduced from a clean checkout without a committed database or secret.
