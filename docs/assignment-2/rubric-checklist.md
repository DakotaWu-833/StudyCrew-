# Assignment 2 full-mark acceptance checklist

Status key: `[x]` is supported by the current repository and verified local
quality run; `[ ]` requires final team, GitHub, report, video or fresh-checkout
evidence. Latest repository verification: 16 September 2026 — 275 Django tests,
96.3% branch coverage, 4 files/18 frontend tests, zero-warning OpenAPI
validation, TypeScript check and production build all passed.

## Backend

- [x] Django MVT structure is modular, named consistently and free of hidden
      business logic in signals or templates.
- [x] Development and production settings are environment-driven; safe 400,
      403, 404 and 500 pages never expose a traceback.
- [x] Eighteen meaningful tables exist, including one-to-one, one-to-many and
      many-to-many relationships, constraints and appropriate indexes.
- [x] Registration, secure login and POST logout are complete.
- [x] Password complexity, persistent account/IP lockout and idle-session expiry
      are enforced server-side.
- [x] Email one-time-code MFA is expiring, attempt-limited, hashed at rest and
      required before creating an authenticated session.
- [x] Eight JSON resource families support documented CRUD/actions with correct
      HTTP verbs, validation, CSRF-aware authentication and object permissions.
- [x] A custom site-admin panel has narrow permissions and an immutable audit
      trail; Django's developer admin is not exposed.

## Frontend and functionality

- [x] Relevant project, task, comment, meeting, invitation, notification and
      moderation operations complete without full-page reloads.
- [x] The interface implements explicit loading, success, validation, empty and
      error states, reusable components and responsive layout rules.
- [x] Fifteen public/account/workspace/moderator surfaces pass local
      360/768/1440 px overflow and control-labelling checks; all surfaces use
      one visual system and contextual confirmation instead of browser prompts.
- [x] Custom CSS and TypeScript/JavaScript are organised and accessible; keyboard
      focus and an ARIA live region support dynamic changes.
- [x] Nager.Date is called only by the backend, cached by year, constrained by a
      short timeout and has stale/unavailable fallbacks.
- [x] Modern Web option 1 is evidenced by React, Vite, routing, query caching,
      feature modules and reusable components. WebSocket is not implemented.
- [x] At least five authenticated workflows are complete: profile,
      project/invitation, tasks, comments, meetings, evidence and notifications.
- [ ] The final video records operation at 360 px, 768 px and 1440 px, including
      keyboard focus, a validation error and recovery, nested-route refresh and
      the SRS search/insight timing budgets under the seeded dataset.

## Project management and testing

- [x] `.gitignore` excludes secrets, databases, environments, caches, logs and
      generated test output.
- [ ] Team members use their own USYD GitHub identities, descriptive branches,
      reviewable pull requests and meaningful commits throughout development.
- [x] Django TestCase tests cover normal, edge, failure, permission and
      transaction behaviour for key models, services, APIs and pages.
- [x] The documented and tested access matrix includes visitor, incomplete-MFA,
      non-member, member, facilitator, owner and site moderator.
- [x] Backend branch coverage is 96.3% overall and every reported non-100% key
      file is at least 86%.
- [x] `makemigrations --check`, Django checks, 275 backend tests, OpenAPI
      validation, 18 frontend tests, typecheck and production build pass in the
      current source tree.
- [ ] The same gates pass in CI from the final course-organisation main-branch
      commit.

## Submission evidence

- [x] README covers overview, exact dependency versions, local setup,
      environment variables, database initialisation, API examples and demo data.
- [x] API, test, traceability and timed demonstration guides are present and
      reproducible without a committed database or secret.
- [ ] The final main-branch commit is pushed to the course organisation before
      25 October 2026, 11:59 pm, with every member using their own USYD account.
- [ ] The Canvas report follows the supplied template without missing headings.
- [ ] A ten-minute video visibly demonstrates every claimed function.
- [ ] Every team member can explain their implementation during the Week 12
      technical interview.
