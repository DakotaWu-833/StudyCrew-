# StudyCrew Software Requirements Specification

## 1. Purpose and scope

StudyCrew helps university project teams coordinate work and maintain a factual,
reviewable record of contribution. The product boundary includes account access,
project membership, task collaboration, meeting coordination, notifications,
activity evidence and export. It does not grade students, infer contribution
quality, replace the learning-management system or message people outside the
application during the MVP.

The requirements use the IEEE 830-1998 functional-requirement structure: each
item identifies its trigger/input, required processing, observable output and
verifiable acceptance condition. "Shall" denotes a mandatory system behaviour.

## 2. Actors and common rules

- **Visitor:** a person who is not authenticated.
- **Member:** an authenticated user who belongs to a project.
- **Project owner:** the single member permitted to administer a project.
- **System clock:** UTC timestamps stored by the server and rendered in the
  authenticated user's selected IANA time zone.
- **Authorisation rule:** unless stated otherwise, project data is visible only
  to current members of that project.

## 3. Functional requirements

### FR-AUTH-01 - Register an account

**Requirement.** The system shall create a user account when a visitor submits a
unique, syntactically valid email address, a display name of 2-80 characters and
a password of at least 12 characters.

- **Input/trigger:** visitor submits the registration form.
- **Processing:** normalise the email to lowercase, reject an existing email,
  hash the password with the configured one-way password algorithm, create one
  user and one profile in a transaction, and start an authenticated session.
- **Success output:** redirect to the empty project dashboard within 2 seconds
  under normal test load and display a registration confirmation.
- **Failure output:** preserve non-secret form fields and identify each invalid
  field without revealing whether a different account is active.
- **Acceptance:** valid input creates exactly one `users` row and one `profiles`
  row; duplicate email or invalid input creates neither row.

### FR-AUTH-02 - Sign in and sign out

**Requirement.** The system shall authenticate a registered user from an email
and password and shall terminate that user's current session on sign-out.

- **Input/trigger:** sign-in or sign-out submission.
- **Processing:** compare the password using the configured hash verifier,
  rotate the session identifier after successful sign-in, and invalidate the
  server-side session on sign-out.
- **Success output:** show the project dashboard after sign-in and the public
  sign-in view after sign-out.
- **Failure output:** return one generic credential error and create no session.
- **Acceptance:** an invalid password cannot access an authenticated route; a
  signed-out session cannot be reused to access one.

### FR-PROF-01 - Maintain a profile

**Requirement.** The system shall allow an authenticated user to view and update
their display name, course, time zone, biography and avatar URL.

- **Input/trigger:** user submits profile fields.
- **Processing:** validate lengths, permit only a recognised IANA time zone and
  update only the profile associated with the authenticated user.
- **Success output:** show the saved profile values on refresh.
- **Failure output:** identify invalid fields and leave stored values unchanged.
- **Acceptance:** a user can update their own profile but cannot update another
  profile by changing a URL or request identifier.

### FR-PROJ-01 - Create a project

**Requirement.** The system shall allow an authenticated user to create a project
with a name of 3-100 characters, optional description and due date.

- **Input/trigger:** user submits the new-project form.
- **Processing:** create the project and an `owner` membership for the creator in
  one transaction.
- **Success output:** open the new project overview showing the creator as owner.
- **Failure output:** show validation errors and create no partial project.
- **Acceptance:** successful creation produces exactly one project and one owner
  membership; the project is absent from non-members' dashboards.

### FR-PROJ-02 - Invite and join members

**Requirement.** The system shall allow a project owner to invite an email
address and shall allow the matching authenticated user to accept or decline the
invitation before its expiry.

- **Input/trigger:** owner sends an invitation; invitee accepts or declines.
- **Processing:** prevent duplicate pending invitations and existing-member
  invitations, expire invitations after 7 days, and create membership only on a
  valid acceptance.
- **Success output:** show the pending invitation to both parties and, after
  acceptance, show the new member in the roster.
- **Failure output:** reject expired, cancelled, duplicate or unauthorised use.
- **Acceptance:** one accepted invitation creates one membership and cannot be
  accepted a second time.

### FR-PROJ-03 - Administer project membership

**Requirement.** The system shall allow the project owner to change a member
between `member` and `facilitator` roles or remove that member, but shall not
allow removal or demotion of the sole owner.

- **Input/trigger:** owner submits a role change or removal.
- **Processing:** verify current ownership and target membership, then update or
  soft-remove the membership with an audit event.
- **Success output:** refresh the roster and permission-dependent controls.
- **Failure output:** return a permission or sole-owner constraint message.
- **Acceptance:** a regular member receives HTTP 403 for the same operation; a
  removed member immediately loses project access.

### FR-TASK-01 - Manage tasks

**Requirement.** The system shall allow a current project member to create, view,
edit and archive a task with title, description, priority and optional due date.

- **Input/trigger:** member submits a task create, update or archive action.
- **Processing:** validate title length (3-120), priority (`low`, `medium`,
  `high`, `urgent`) and project membership; retain archived tasks for evidence.
- **Success output:** update the project board without a full page reload and
  display the task's latest values.
- **Failure output:** reject invalid or unauthorised changes without partial data.
- **Acceptance:** valid create/edit/archive actions are visible after refresh;
  archived tasks are excluded from the default board and remain exportable.

### FR-TASK-02 - Assign task responsibility

**Requirement.** The system shall allow a current project member to assign zero
or more current project members to a task and to remove assignees.

- **Input/trigger:** member submits the assignee selector.
- **Processing:** reject users outside the task's project, avoid duplicate
  assignments and apply additions/removals atomically.
- **Success output:** show the same assignees on the board and task detail view.
- **Failure output:** identify an ineligible assignee and preserve prior state.
- **Acceptance:** assigning two eligible users creates two unique junction rows;
  resubmitting the same selection creates no duplicates.

### FR-TASK-03 - Progress a task

**Requirement.** The system shall allow an assignee or project owner to move a
task among `todo`, `in_progress`, `blocked` and `done` states.

- **Input/trigger:** authorised user selects or drags a task to a state.
- **Processing:** require a blocker note of 3-500 characters for `blocked`, set
  `completed_at` only for `done`, and record the actor and transition.
- **Success output:** move the task to the selected board column and announce the
  change in an accessible live region.
- **Failure output:** return the task to its prior state with a reason.
- **Acceptance:** blocked without a note is rejected; moving to done sets one
  completion timestamp; reopening clears it.

### FR-COLL-01 - Discuss a task

**Requirement.** The system shall allow a current project member to add a plain-
text comment of 1-2000 characters to a task and edit or delete their own comment.

- **Input/trigger:** member submits a comment action.
- **Processing:** escape active content, retain created/edited timestamps and
  permit project owners to moderate with an audit event.
- **Success output:** append or update the comment thread in chronological order.
- **Failure output:** reject blank, oversized or unauthorised modifications.
- **Acceptance:** scripts render as text, not executable markup; a non-author,
  non-owner cannot modify the comment.

### FR-MEET-01 - Schedule a meeting

**Requirement.** The system shall allow a current project member to create,
update or cancel a meeting with title, start time, end time, location/link and
agenda.

- **Input/trigger:** member submits the meeting form.
- **Processing:** require the end after the start, store UTC, retain organiser,
  and mark cancellation rather than deleting attendance evidence.
- **Success output:** show the meeting in chronological project and calendar views.
- **Failure output:** identify invalid times or fields and preserve stored data.
- **Acceptance:** the same UTC meeting renders correctly in two test time zones;
  an end time equal to the start time is rejected.

### FR-MEET-02 - Respond to a meeting

**Requirement.** The system shall allow each current project member to set one
response (`pending`, `accepted`, `declined`) and an optional availability note
for a non-cancelled meeting.

- **Input/trigger:** member submits an RSVP.
- **Processing:** upsert one response for the meeting/member pair and timestamp it.
- **Success output:** update attendee counts and the member's displayed response.
- **Failure output:** reject non-members and responses to cancelled meetings.
- **Acceptance:** repeated changes update one row rather than creating duplicates;
  displayed counts equal the underlying response rows.

### FR-CONTR-01 - Record contribution evidence

**Requirement.** The system shall append an immutable activity event when an
authenticated member creates, updates or completes a task, comments, schedules a
meeting, responds to a meeting or changes membership.

- **Input/trigger:** successful completion of an audited action.
- **Processing:** record actor, project, event type, relevant entity reference and
  UTC timestamp in the same transaction as the source action.
- **Success output:** make the event available to the project activity feed.
- **Failure output:** roll back the source action if its required event cannot be
  recorded; never expose secret or deleted comment content in metadata.
- **Acceptance:** each audited source action creates exactly one matching event;
  application roles cannot update or delete event rows.

### FR-CONTR-02 - View contribution insights

**Requirement.** The system shall allow a current project member to view per-
member activity counts, completed tasks, comments and meeting participation for a
selected project and date range of no more than 366 days.

- **Input/trigger:** member selects date range and optional activity type.
- **Processing:** aggregate immutable events and current task/attendance records;
  do not calculate a grade or qualitative score.
- **Success output:** render summary totals, an accessible table and drill-down
  event list within 3 seconds under the seeded test dataset.
- **Failure output:** identify invalid ranges and return no data for non-members.
- **Acceptance:** dashboard totals reconcile exactly with a reference SQL query;
  zero-activity members remain visible with zero values.

### FR-NOTIF-01 - Manage in-app notifications

**Requirement.** The system shall notify an authenticated user in-app when they
are invited, assigned a task, mentioned in a comment, or affected by a meeting
change, and shall allow each notification to be marked read.

- **Input/trigger:** a qualifying source event or mark-read action.
- **Processing:** create at most one notification per recipient/source event,
  suppress self-notification, and set `read_at` for the recipient only.
- **Success output:** update unread count and link to the authorised source view.
- **Failure output:** omit links to resources the recipient can no longer access.
- **Acceptance:** duplicate event handling creates one notification; one user
  cannot mark another user's notification as read.

### FR-SEARCH-01 - Search and filter project work

**Requirement.** The system shall allow a current project member to search task
titles/descriptions and filter by status, priority, assignee and due-date state.

- **Input/trigger:** member enters a query or changes a filter.
- **Processing:** combine filters with logical AND, use case-insensitive text
  matching and return only tasks in the selected authorised project.
- **Success output:** update results and report result count within 1 second after
  a 300 ms input debounce under the seeded test dataset.
- **Failure output:** show a clear empty state rather than stale results.
- **Acceptance:** test fixtures return the documented result set for each filter
  and no cross-project task is returned.

### FR-EXPORT-01 - Export contribution evidence

**Requirement.** The system shall allow a current project member to request a PDF
or CSV evidence export for an authorised project and date range.

- **Input/trigger:** member selects format and valid date range.
- **Processing:** create an export job, generate a snapshot containing project,
  range, generation time, member totals and underlying event rows, and expire the
  download after 24 hours.
- **Success output:** show job status and provide an authorised download when ready.
- **Failure output:** mark the job failed with a retry option and no partial file.
- **Acceptance:** exported totals match FR-CONTR-02 for the same inputs; expired or
  non-member download requests are denied.

### FR-SEC-01 - Enforce project authorisation

**Requirement.** The system shall verify authentication and current project
membership on every server-side read or mutation of project-scoped data.

- **Input/trigger:** any request containing or resolving to a project identifier.
- **Processing:** derive user identity only from the validated session and apply
  role checks before querying or mutating protected records.
- **Success output:** allow the request only when the stated permission holds.
- **Failure output:** return HTTP 401 when unauthenticated and HTTP 403 when
  authenticated but unauthorised, without returning protected record content.
- **Acceptance:** an automated access-control matrix test covers every protected
  route with visitor, non-member, member and owner identities.

## 4. MVP boundary

The proposed MVP includes FR-AUTH-01/02, FR-PROF-01, FR-PROJ-01/02,
FR-TASK-01/02/03, FR-COLL-01, FR-MEET-01/02, FR-CONTR-01/02, FR-NOTIF-01 and
FR-SEC-01. Search/filter and export are planned post-MVP enhancements if core
quality gates are met early.

MVP acceptance means all included requirements pass their stated acceptance
checks, protected routes pass the access-control matrix, seeded user journeys can
be completed on desktop and mobile widths, and no severity-1 defect remains.

## 5. Requirement quality audit

- **Correct and unambiguous:** one mandatory behaviour per requirement and
  controlled vocabulary for roles, states and priorities.
- **Complete:** normal, validation, permission and failure behaviour specified.
- **Consistent:** UTC storage, membership boundary and soft-retention rules apply
  across features.
- **Verifiable:** each item has an observable acceptance statement with counts,
  limits, response targets or authorisation outcomes.
- **Traceable:** IDs map to database tables, wireframe views and MVP scope in the
  final report traceability matrix.

## 6. Reference

IEEE Computer Society, *IEEE Std 830-1998: IEEE Recommended Practice for
Software Requirements Specifications*, 1998. The standard is superseded, but is
used because the assignment explicitly requires its Section 5.3.2 structure.

