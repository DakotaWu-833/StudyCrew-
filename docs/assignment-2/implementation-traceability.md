# StudyCrew implementation traceability

This matrix maps each SRS requirement to an observable interface, its primary
implementation boundary and executable evidence. `Implemented` means present in
the current source tree and covered by the verified test baseline; it does not
replace the required demonstration video.

## Functional requirements

| Requirement | Observable implementation | Primary code | Automated evidence | Demo |
| --- | --- | --- | --- | --- |
| FR-AUTH-01 Register | Registration creates an inactive account/profile; email OTP activates it and opens the workspace | `accounts/forms.py`, `accounts/services.py`, `accounts/views.py`, `accounts/models.py` | `accounts/tests/test_models_and_forms.py`, `accounts/tests/test_services.py`, `accounts/tests/test_views_and_middleware.py` | S2 |
| FR-AUTH-02 Sign in/out | Password then OTP, rotated database session, MFA marker, POST logout and inactivity expiry | `accounts/services.py`, `accounts/session_security.py`, `accounts/middleware.py`, `accounts/views.py` | `accounts/tests/test_services.py`, `accounts/tests/test_views_and_middleware.py`, `api/tests/test_auth_and_errors.py` | S2 |
| FR-PROF-01 Profile | Current user reads/updates display name, course, IANA zone, biography and avatar URL | `accounts/forms.py`, `api/serializers.py`, `api/views.py`, `frontend/src/pages/ProfilePage.tsx` | `accounts/tests/test_models_and_forms.py`, `accounts/tests/test_views_and_middleware.py`, `api/tests/test_auth_and_errors.py` | S2 |
| FR-PROJ-01 Create project | Project and sole owner membership are one atomic write | `projects/models.py`, `projects/services.py`, `api/views.py`, `frontend/src/pages/DashboardPage.tsx` | `projects/tests/test_models.py`, `projects/tests/test_services.py`, `api/tests/test_project_and_task_api.py` | S3 |
| FR-PROJ-02 Invite/join | Normalised seven-day invitation, hashed one-use token, matching-email accept/decline and membership creation | `projects/services.py`, `projects/selectors.py`, `api/views.py`, `frontend/src/pages/InvitationsPage.tsx` | `projects/tests/test_services.py`, `api/tests/test_membership_activity_api.py` | S3 |
| FR-PROJ-03 Membership admin | Owner-only member/facilitator changes, soft removal and explicit atomic ownership transfer | `projects/policies.py`, `projects/services.py`, `api/views.py`, `frontend/src/pages/ProjectOverviewPage.tsx` | `projects/tests/test_policies.py`, `projects/tests/test_services.py`, `api/tests/test_membership_activity_api.py` | S3 |
| FR-TASK-01 Task management | Create/read/edit, combined filters and evidence-preserving archive in the React board/detail views | `tasks/models.py`, `tasks/services.py`, `tasks/selectors.py`, `api/views.py`, `frontend/src/pages/TasksPage.tsx` | `tasks/tests/test_models.py`, `tasks/tests/test_selectors.py`, `tasks/tests/test_services.py`, `api/tests/test_project_and_task_api.py` | S4 |
| FR-TASK-02 Assignment | Atomic replacement of unique, same-project task assignees | `tasks/models.py`, `tasks/services.py`, `api/views.py`, `frontend/src/pages/TaskDetailPage.tsx` | `tasks/tests/test_models.py`, `tasks/tests/test_services.py`, `api/tests/test_project_and_task_api.py` | S4 |
| FR-TASK-03 Progress | Assignee/owner transitions, required blocker note and controlled completion timestamp | `tasks/models.py`, `tasks/services.py`, `api/views.py`, `frontend/src/pages/TasksPage.tsx` | `tasks/tests/test_models.py`, `tasks/tests/test_services.py`, `api/tests/test_project_and_task_api.py` | S4 |
| FR-COLL-01 Discussion | Plain-text comments, author edit/delete, owner/facilitator moderation, report workflow and retained timestamps | `tasks/models.py`, `tasks/services.py`, `api/views.py`, `frontend/src/pages/TaskDetailPage.tsx` | `tasks/tests/test_services.py`, `api/tests/test_comment_meeting_collaboration_api.py`, `web/tests/test_control.py` | S4, S8 |
| FR-MEET-01 Schedule | Timezone-aware create/edit, end-after-start validation and evidence-preserving cancellation | `meetings/models.py`, `meetings/services.py`, `api/views.py`, `frontend/src/pages/MeetingsPage.tsx` | `meetings/tests/test_models.py`, `meetings/tests/test_services.py`, `api/tests/test_comment_meeting_collaboration_api.py` | S5 |
| FR-MEET-02 RSVP | One attendance row per meeting/member, upserted response and accurate counts | `meetings/models.py`, `meetings/services.py`, `meetings/selectors.py`, `api/views.py` | `meetings/tests/test_models.py`, `meetings/tests/test_selectors.py`, `meetings/tests/test_services.py` | S5 |
| FR-CONTR-01 Activity evidence | Typed append-only event is written in the same transaction as each audited action | `activity/models.py`, `activity/services.py`, domain `services.py` modules | `activity/tests/test_activity.py`, `projects/tests/test_services.py`, `tasks/tests/test_services.py`, `meetings/tests/test_services.py` | S6 |
| FR-CONTR-02 Insights | Date/type filters, zero-member-inclusive factual counts, accessible table and capped event drill-down | `activity/insights.py`, `activity/selectors.py`, `api/views.py`, `frontend/src/pages/ContributionsPage.tsx` | `activity/tests/test_insights_and_exports.py`, `api/tests/test_membership_activity_api.py` | S6 |
| FR-NOTIF-01 Notifications | Deduplicated, self-suppressed invitation/assignment/mention/meeting notices and recipient-only read action | `activity/models.py`, `activity/services.py`, `activity/selectors.py`, `frontend/src/pages/NotificationsPage.tsx` | `activity/tests/test_activity.py`, `tasks/tests/test_services.py`, `api/tests/test_membership_activity_api.py` | S7 |
| FR-SEARCH-01 Search/filter | Debounced case-insensitive text with AND-combined status, priority, assignee and due filters scoped to one project | `tasks/selectors.py`, `api/views.py`, `frontend/src/pages/TasksPage.tsx` | `tasks/tests/test_selectors.py`, `api/tests/test_project_and_task_api.py`, `frontend/src/app/debounce.test.ts` | S4 |
| FR-EXPORT-01 Export | Authorised 366-day CSV/PDF snapshot, ready/failed state, 24-hour expiry and protected download | `activity/exports.py`, `activity/models.py`, `api/views.py`, `frontend/src/pages/ContributionsPage.tsx` | `activity/tests/test_insights_and_exports.py`, `api/tests/test_membership_activity_api.py` | S6 |
| FR-SEC-01 Authorisation | Post-OTP session plus server-side current-membership/role checks on every protected object | `api/authentication.py`, domain `policies.py`/`selectors.py`, `api/exceptions.py` | `api/tests/test_auth_and_errors.py`, `api/tests/test_project_and_task_api.py`, `projects/tests/test_policies.py` | S2–S9 |
| FR-MOD-01 Site moderation | Narrow two-permission custom panel for report resolution and account suspension/restoration with a separate audit ledger | `accounts/policies.py`, `tasks/services.py`, `web/views.py`, `templates/web/control.html` | `web/tests/test_control.py`, `tasks/tests/test_services.py` | S8 |

Search/filter and export were labelled post-MVP options in the original SRS;
both and the assignment-required moderation panel were implemented after the
core quality gates and are included in the delivered product.

## Data-model evidence

| App | Meaningful tables | Count |
| --- | --- | ---: |
| Accounts | `User`, `Profile`, `LoginThrottle`, `EmailOTPChallenge` | 4 |
| Projects | `Project`, `ProjectMembership`, `ProjectInvitation` | 3 |
| Tasks | `Task`, `TaskAssignment`, `TaskComment`, `ContentReport` | 4 |
| Meetings | `Meeting`, `MeetingAttendance` | 2 |
| Activity | `ActivityEvent`, `Notification`, `ExportJob`, `SiteAuditEvent` | 4 |
| Integrations | `ApiCacheEntry` | 1 |
| **Total** | Excludes Django session/content-type/permission tables | **18** |

The schema demonstrates one-to-one (`User`–`Profile`), one-to-many (for
example, `Project`–`Task` and `Task`–`TaskComment`) and explicit many-to-many
relationships (`User`–`Project` through membership, `User`–`Task` through
assignment, and `User`–`Meeting` through attendance). Migrations define the
unique, check and lookup constraints used by the corresponding model tests.

## Assignment rubric cross-reference

| Rubric area | Repository evidence | Verification |
| --- | --- | --- |
| Django MVT and maintainability | Domain apps separate models, transactional services, read selectors and policies; `api/` and `web/` are HTTP boundaries; templates contain no business mutation; an AST/source guard enforces directed dependencies | Django check plus 275 tests |
| Relational data model | 18 meaningful tables; `User`–`Profile` one-to-one, project/task/user foreign keys, and explicit membership/assignment/attendance junction tables; migrations carry constraints/indexes | Model and migration tests |
| Authentication/security | Argon2 configuration, 12-character complexity, persistent account/IP lockout, 30-minute idle expiry, account activation and email OTP MFA | Account and API authentication suites |
| REST JSON API | Eight routed resource families plus health/profile/account helpers and custom actions; CRUD verbs, stable errors, pagination, session/MFA/CSRF and object permissions | `api/tests/`; `openapi.yml`; `api.md` |
| Custom admin | `/control/` provides report resolution and user suspension/restoration to a two-permission non-superuser moderator; developer admin is absent | `web/tests/test_control.py` |
| AJAX/frontend | Same-origin Fetch client plus complete pagination and React Query mutations/invalidations power project, task, comment, meeting, invitation, notification and export actions; the control centre updates metrics and audit evidence in-place | frontend source, 18 Vitest cases and browser demo |
| CSS/JavaScript quality | Unified public/account/workspace/control styling, reusable UI/state/confirmation components, focus/live-region semantics and responsive layouts | Typecheck, production build and 45-view-width browser audit |
| External API | Fixed backend-only Nager.Date endpoint, validated year cache, three-second timeout, stale/unavailable fallback; not on meeting write path | `integrations/tests/test_nager_date.py` |
| Modern Web option 1 | React 19, TypeScript, Vite, React Router and TanStack Query with feature pages and reusable components | frontend tests/typecheck/build |
| Working functionality | Profile, project/invitation/membership, task/assignment/status, comments/reports, meetings/RSVP, evidence/export and notifications | S2–S8 plus functional test suites |
| Testing | Normal, edge, invalid, permission, rollback, failure and complete vertical-journey assertions across key files | 275 tests, 96.3% branch coverage |

## Delivery evidence still owned by the team

The repository can prove implementation and automated behaviour. It cannot
prove the following submission facts until the team supplies them:

- course-organisation GitHub history from each member's own USYD account,
  reviewed pull requests and final main-branch CI URL;
- the completed Canvas report using the supplied template;
- the uploaded ten-minute video showing every report claim; and
- each team member's ability to explain their own work in the Week 12 interview.
