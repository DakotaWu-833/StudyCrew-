# Academic workflow integration

Register `campus.apps.CampusConfig` in `INSTALLED_APPS`, and include `campus.urls`
under `/api/v1/campus/`. All views use the application's default authenticated
MFA session and CSRF policies; none grant anonymous project reads.

Frontend routes:

- `/app/campus/`: `CampusPage` (private courses/terms, personal tasks, search, join requests).
- `/app/projects/:projectId/plan/`: `ProjectPlanPage` (assignment planning and submission).
- `/app/projects/:projectId/resources/`: `ResourcesPage` (links, tags, pinning and search).

The pages import their own `campus.css`. Their API client uses the existing
same-origin `apiFetch` and CSRF header handling. Project pages derive manager
actions from the current membership role, while the backend checks permission
again on every mutation.

## Domain integration

`Term` and `Course` belong to the reporting user. The university name is a label,
not an enrolment claim, directory or permission source. `ProjectCourse` permits
multiple course associations. Private project reads remain scoped by active
`ProjectMembership`.

Existing `Project` and `Task` are extended through related tables. Templates and
subtasks call existing `tasks.services.create_task`; internal task deadlines use
the existing task `due_at`; assignment handover uses `replace_assignees`; owner
handover calls the existing transactional `transfer_ownership`. Existing audit
event types are reused with an explicit `campus_action` in safe metadata.

Call `campus.services.validate_task_completion(task)` in the existing
`transition_task` service before changing `task.status` to `done`. A validation-only
pre-save signal also protects direct ORM saves. It performs no hidden mutation.
It checks unfinished prerequisites, child tasks, checklist entries and nominated
reviewer approval. Reopen completed tasks before changing academic plans.

Team agreement and submission confirmations refer to a specific revision.
Editing their content invalidates previous revision confirmations. Recording a
submission receipt requires all checklist entries checked, all current tasks
finished/archived, and confirmation from every current active member. Receipt
links are user-provided evidence; this application does not submit to a university
or independently verify its receipt.

## Joining and leaving

Only an owner creates or revokes join links. Tokens are shown once and only their
SHA-256 digest is stored. Expiry is at most 30 days, capacity at most 50 approved
joins, creation at most five per project per hour, and token attempts at most ten
per authenticated account per hour. Join links require owner approval; a pending
applicant cannot read the private project's name/content through these APIs.
Revocation rejects pending requests. Approved joins count against link capacity.

Self-leave is transactional: owners nominate an active successor, current task
responsibilities are handed to another active member, review nominations are
cleared, and access is removed. Historical events remain in the existing ledger.

## Archival, copy and links

Term archival archives the user's personal organisation label and prevents new
course associations to it. It does not remove shared project history. Term copy
is restricted to projects the actor owns in that term. It clones descriptions,
task relationships, unchecked checklists, milestones, agreement text and resource
links into new private projects, and resets members, dates, reviews, completion,
confirmations and receipts.

Resource links accept public HTTP/HTTPS URLs without credentials; local/private
IP literals and local hostnames are rejected. The server does not fetch links.
Document access remains controlled by its external provider. Authors or managers
may edit/delete their links. Archived projects remain read-only.

## Verification

Run `python manage.py test campus tasks`, `npm run typecheck`, and
`npm test -- src/api/campus.test.ts`. The workflows cover private metadata and
IDOR, graph cycles, template tasks and old completion routes, deadline order,
peer review, revision confirmations, submission gates, safe links, scoped search,
transactional leave/handover, approval/revocation/limits, term copying and CSRF.
