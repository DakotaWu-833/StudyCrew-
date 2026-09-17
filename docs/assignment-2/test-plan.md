# StudyCrew Assignment 2 test plan

## 1. Purpose and acceptance threshold

This plan verifies the implemented Assignment 2 product at model, service,
selector, HTTP API and browser-client boundaries. A green run requires all of
the following:

- no unapplied model changes and no Django system-check errors;
- every Django and Vitest test passes;
- branch-aware backend coverage is at least 85% overall and in every reported
  key application file;
- the OpenAPI document validates without warnings or errors; and
- TypeScript checking and the Vite production build succeed.

Coverage is a supporting measure, not a substitute for assertions. The suite
therefore includes normal, boundary, invalid, duplicate, rollback, permission
and provider-failure cases.

## 2. Verified baseline

The following results were reproduced from the current source tree on
16 September 2026:

| Gate | Result |
| --- | --- |
| Django tests | **275 passed** |
| Backend coverage | **96.3% total branch coverage**; every reported non-100% key file was at least 86.0% |
| Frontend tests | **4 files / 18 tests passed** |
| Migration drift | `makemigrations --check --dry-run` passed |
| Django checks | `manage.py check` passed |
| API contract | OpenAPI generation and validation passed with zero warnings/errors |
| TypeScript | Typecheck passed |
| Production client | Vite build passed; 84 modules transformed |

The final team commit must reproduce these results in CI. PostgreSQL, Nginx and
the live AWS host are Assignment 3 deployment evidence and are not claimed by
this local Assignment 2 baseline.

## 3. Reproduction commands

Run from the repository root after following the README setup:

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py spectacular --file docs\assignment-2\openapi.yml --validate
.\.venv\Scripts\coverage.exe erase
.\.venv\Scripts\coverage.exe run manage.py test
.\.venv\Scripts\coverage.exe report --fail-under=85
Set-Location frontend
npm test
npm run typecheck
npm run build
```

The same gates are encoded in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).
Coverage uses branch measurement and the exclusions recorded in
[`.coveragerc`](../../.coveragerc); migrations, tests and framework bootstrap
files are excluded, but application models, services, selectors and HTTP views
are measured.

## 4. Automated suite inventory

| Area | Test methods | Primary behaviour under test |
| --- | ---: | --- |
| `accounts/tests/` | 49 | registration, Argon2-compatible password policy, OTP lifecycle, hashed lockout keys, session/MFA handling, profile ownership, password change and demo seed |
| `projects/tests/` | 53 | relational constraints, owner creation, delivered/rolled-back invitations, roles, assignment-safe removal, ownership transfer, archive guards and project isolation |
| `tasks/tests/` | 26 | validation, filtering, assignment atomicity, status rules, comments, mentions, reports and archived task/project protection |
| `meetings/tests/` | 30 | time constraints, permissions, edit/cancellation, RSVP note upsert, archive guards, time-zone preservation and holiday advisory boundary |
| `activity/tests/` | 23 | immutable events, notification membership isolation, factual insights, truncation, lossless CSV/PDF export, expiry and safe failure |
| `integrations/tests/` | 10 | cache hit, one fetch per year, timeout, stale fallback, malformed payload and unavailable provider |
| `api/tests/` | 60 | JSON CRUD, strict declared-field write contracts, validated combined queries, pagination, archive history, MFA/CSRF/IDOR/schema and one complete invitation-to-export acceptance journey |
| `web/tests/` | 22 | client-route shell, custom moderator permissions and creation, suspension, report resolution, legacy-profile resilience and audit trail |
| `config/tests/` | 2 | safe 400/403/404/500 pages plus executable directed-dependency boundaries |
| `frontend/src/**/*.test.ts` | 18 | CSRF-aware fetch client, complete pagination, actionable field errors, resource URL/verb construction, 300 ms debounce/cancellation and locale/IANA-zone/DST-safe date formatting |

Total: 275 Django test methods and 18 Vitest cases. Test data is created inside
isolated Django test databases; no committed SQLite file is required.

## 5. Access-control matrix

`Allow` means the role is permitted when other domain conditions are valid.
`Deny` means the server returns 401 or 403 without protected content. A site
moderator receives no automatic access to a private project.

| Operation | Visitor | Password only / bad MFA marker | Outsider | Member | Facilitator | Owner | Site moderator without membership |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Public home, register, login, health | Allow | Allow | Allow | Allow | Allow | Allow | Allow |
| Private API/data | Deny | Deny | Allow own account only | Allow | Allow | Allow | Allow own account only |
| Create a project | Deny | Deny | Allow | Allow | Allow | Allow | Allow |
| Read a selected private project | Deny | Deny | Deny | Allow | Allow | Allow | Deny |
| Edit/archive project; invite; roles; ownership | Deny | Deny | Deny | Deny | Deny | Allow | Deny |
| Task create/edit/archive | Deny | Deny | Deny | Allow | Allow | Allow | Deny |
| Task transition | Deny | Deny | Deny | Assigned member only | Assigned facilitator only | Allow | Deny |
| Read/add task comments | Deny | Deny | Deny | Allow | Allow | Allow | Deny |
| Edit/delete another user's comment | Deny | Deny | Deny | Deny | Allow | Allow | Deny |
| Create a meeting / RSVP | Deny | Deny | Deny | Allow | Allow | Allow | Deny |
| Edit/cancel another organiser's meeting | Deny | Deny | Deny | Deny | Allow | Allow | Deny |
| Insights and own authorised export | Deny | Deny | Deny | Allow | Allow | Allow | Deny |
| `/control/` user/report moderation | Deny | Deny | Deny | Deny | Deny | Deny | Allow |

Representative executable evidence is in
[`api/tests/test_auth_and_errors.py`](../../api/tests/test_auth_and_errors.py),
[`api/tests/test_project_and_task_api.py`](../../api/tests/test_project_and_task_api.py),
[`projects/tests/test_policies.py`](../../projects/tests/test_policies.py) and
[`web/tests/test_control.py`](../../web/tests/test_control.py).

## 6. Security and resilience regression set

| Risk | Expected result | Automated evidence |
| --- | --- | --- |
| Weak or reused-form password input | Rejected by server-side validators; only a password hash is stored | `accounts/tests/test_models_and_forms.py`, `accounts/tests/test_services.py` |
| Password guessing | Generic response; persistent account and IP counters lock repeated failures | `accounts/tests/test_services.py`, `accounts/tests/test_views_and_middleware.py` |
| OTP replay, expiry or guessing | Hashed, short-lived, attempt-limited challenge is consumed and cannot be replayed | `accounts/tests/test_services.py` |
| Session or MFA-marker tampering | Protected API returns 401 | `api/tests/test_auth_and_errors.py` |
| Cross-site mutation | Missing CSRF proof returns 403; a valid same-origin token succeeds | `api/tests/test_auth_and_errors.py` |
| IDOR / cross-project UUID | Request is denied and private content is absent | `api/tests/test_project_and_task_api.py`, `tasks/tests/test_selectors.py` |
| XSS payload in a comment | Stored and rendered as plain text, never active markup | `api/tests/test_comment_meeting_collaboration_api.py` |
| SQL-injection-shaped search | Treated as search data and returns no cross-project rows | `api/tests/test_project_and_task_api.py` |
| Partial transactional write | Source mutation rolls back when required evidence recording fails | `projects/tests/test_services.py`, `meetings/tests/test_services.py` |
| Audit modification | Application update/delete is rejected | `activity/tests/test_activity.py` |
| External API timeout/bad payload | Fresh cache, then validated stale cache, otherwise advisory unavailable; meeting CRUD continues | `integrations/tests/test_nager_date.py`, `meetings/tests/test_services.py` |
| Export URL guessing, expiry or path tampering | Download is denied and no unrelated path is served | `activity/tests/test_insights_and_exports.py`, `api/tests/test_membership_activity_api.py` |
| Unexpected server exception | Stable generic error; no traceback or exception text in response | `api/tests/test_exception_handler.py`, `config/tests/test_error_views.py` |

## 7. Manual browser acceptance before submission

Use a freshly seeded workspace and complete the [demo script](demo-script.md).
Capture the final run rather than relying only on screenshots.

A local Chromium engineering pass on 16 September covered 15 public, account,
workspace and moderator surfaces at 360, 768 and 1440 px. Forced horizontal
scrolling remained at zero on every page; automated DOM checks found no
duplicate IDs, unnamed buttons or unlabelled form controls. The table below
remains for the team's final recorded acceptance evidence, including the human
keyboard and timing observations that automation cannot replace.

| Check | 360 px | 768 px | 1440 px |
| --- | :---: | :---: | :---: |
| No page-level horizontal overflow | [ ] | [ ] | [ ] |
| Navigation, forms, task board and tables remain operable | [ ] | [ ] | [ ] |
| Keyboard-only focus order and visible focus indicator | [ ] | [ ] | [ ] |
| Loading, empty, validation, success and provider-unavailable states are understandable | [ ] | [ ] | [ ] |
| Refreshing a nested `/app/.../` route returns the workspace rather than 404/500 | [ ] | [ ] | [ ] |

Also verify in a current Chromium browser that:

1. a task creation, filter, status change and comment update occur without a
   full-page navigation;
2. a network or validation failure leaves prior data visible and offers a clear
   message/retry path;
3. the `aria-live`/status message announces dynamic results; and
4. timestamps change when the user's IANA time-zone preference changes.

With the standard `seed_demo` dataset, also capture the browser Network panel
showing that text search waits approximately 300 ms after the final keystroke
and completes within one second, while contribution insights complete within
three seconds. Record the browser, machine and observed times; these SRS timing
budgets are manual acceptance evidence rather than meaningful unit-test claims.

## 8. Final evidence record

Before the deadline, attach the CI run URL and the following terminal excerpts
to the report evidence appendix: test counts, coverage total/key-file minimum,
OpenAPI zero-warning result, TypeScript result and Vite build result. Do not
commit `.coverage`, `htmlcov/`, a database, credentials, OTP messages or browser
session cookies.
