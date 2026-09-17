# StudyCrew 10-minute Assignment 2 demonstration

This shot list demonstrates the claims in the report through visible outcomes.
Keep the browser zoom at 100%, enlarge terminal text, and rehearse once so the
recording finishes within ten minutes.

## Preparation (not recorded)

1. Run migrations, build the client, and execute `manage.py seed_demo
   --reset-passwords`. Copy the generated passwords to a temporary local note;
   do not show or commit that note.
2. Start Django at `http://127.0.0.1:8000/`. Keep `var/emails/` available for the
   local one-time codes.
3. In a second browser profile, register a new invitee account and leave it
   signed in but not in the seeded project.
4. Create a site moderator with `manage.py create_site_moderator`, using the
   hidden password prompts, and sign it in in a third browser profile.
5. Keep the primary browser signed out at `/account/login/`. Open the invitee at
   `/app/invitations/` and the moderator at `/control/`, ready to refresh.
6. Use the seeded owner `owner@studycrew.local` in the primary browser. Have the
   random password ready to paste. A local OTP may be shown only after entry;
   never expose a reusable password, session cookie or secret key.

The seeded `COMP3609 Group Project` contains four roles/users, four task states,
comments, a meeting, RSVP data and contribution history. This makes the demo
repeatable without committing a database.

## Timed recording

### S1 — 0:00–0:30: purpose and boundaries

- Show the public home page and state the problem in one sentence: StudyCrew
  coordinates a private student project and keeps factual, reviewable evidence
  of contributions without grading people.
- Point out the main workflows: projects, tasks, meetings, notifications and
  evidence.

**Marker sees:** a coherent product goal and a custom interface.

### S2 — 0:30–1:25: authentication and profile

- Sign in as `owner@studycrew.local`. After the password step, show that access
  is not granted until the six-digit email OTP is accepted.
- Briefly identify the visible password guidance, then complete OTP from the
  newest local email. Do not intentionally trigger the full lockout during the
  timed recording.
- Open **Profile**, change the IANA time zone, save, and show the success state.

**Say:** password complexity, persistent account/IP lockout, a 30-minute idle
session limit and expiring, hashed, attempt-limited, single-use OTP are enforced
by Django, not by JavaScript.

### S3 — 1:25–2:35: project, invitation and role boundaries

- Open `COMP3609 Group Project` and show the owner, facilitator and member
  roster.
- Invite the prepared invitee email and show the seven-day pending invitation.
- Switch to the invitee browser, refresh **Invitations**, accept, and show the
  project appear. Return to the owner browser and show the new roster row.
- Change that user between member and facilitator, then restore the intended
  role. Point out ownership transfer as an explicit separate action.

**Marker sees:** invitation acceptance is identity-bound and role controls are
shown only to the owner. Mention that the database constraint preserves one
active owner.

### S4 — 2:35–4:25: task board, assignment and comments

- Open **Tasks**. Show the seeded `todo`, `in progress`, `blocked` and `done`
  columns, then filter by text and priority and clear the filters.
- Create one task with priority and due date; open it, assign two current
  members (including the prepared invitee), and save.
- Move it to **Blocked**, supply a meaningful blocker note, then move it to
  **Done** and show the completion state.
- Add a plain-text comment, select the invitee as a mention, then edit it. Show
  the existing comment thread and report another user's comment for moderation.
- Archive the demonstration task, switch **Record state** to **Archived**, and
  reopen it to prove retained evidence remains discoverable and read-only.

**Marker sees:** multiple AJAX mutations, loading/success/error feedback,
multi-member assignment, guarded transitions, plain-text discussion and no
full-page reload.

### S5 — 4:25–5:30: meetings and resilient external API

- Open **Meetings**, create a meeting with start/end time and agenda, then edit
  its title or agenda to demonstrate the update workflow. Change the owner's
  RSVP with an availability note. First submit an end time before the start,
  show the safe field/domain feedback, correct it, and show the totals updating.
- Select **Check public holiday** and show the Australian advisory plus its
  source (`live`, `cache`, `stale` or `unavailable`).
- Explain that Nager.Date is called only by Django, cached by calendar year and
  never blocks meeting create/update/cancel if the provider is slow or down.

**Marker sees:** meeting CRUD/RSVP and a meaningful, non-critical backend-only
external integration with a visible fallback.

### S6 — 5:30–6:40: factual contribution evidence and export

- Open **Contributions**. Change the date range and activity-type filter.
- Show that every current member remains in the accessible table, including a
  zero count when applicable, and that the timeline reconciles to stored
  actions.
- Create a CSV export and a PDF export; download one and briefly show the project,
  date range, member totals and event detail.

**Say:** the figures are immutable factual counts, not a grade or qualitative
score. Exports expire after 24 hours and remain membership-authorised.

### S7 — 6:40–7:15: notifications

- Switch to the invitee browser and open **Notifications**. Show the unread
  badge and invitation, assignment, mention or meeting notification generated
  by the earlier actions.
- Mark one notification read and show the unread count update immediately.

**Marker sees:** recipient-isolated state changes without navigation reload.

### S8 — 7:15–8:15: custom site moderation

- Switch to the moderator browser and refresh `/control/`.
- Resolve the comment report created in S4, include a resolution note, and show
  the queue count and new immutable site-audit row update without a page reload.
- Suspend and restore the prepared invitee. Show that the interface exposes
  only these narrow operations, not secrets or developer configuration.
- Navigate once to `/admin/` and show that Django's built-in developer admin is
  not mounted.

**Marker sees:** a custom user-facing admin surface with least-privilege
permissions, self/superuser protections and an audit trail.

### S9 — 8:15–9:05: REST API and failure safety

- Open `/api/schema/` or the checked-in OpenAPI file and point to the versioned
  project, task, comment, meeting, membership, notification and export resource
  families.
- In browser developer tools, show one successful JSON request with the correct
  HTTP verb and one validation response using the stable
  `error.code/message/fields` envelope.
- State that protected calls require the post-OTP server session and unsafe
  requests require the same-origin CSRF token.

**Marker sees:** documented JSON CRUD with consistent validation,
authentication and permissions.

### S10 — 9:05–9:40: responsive and accessible behaviour

- Switch developer tools to 360 px. Open navigation, the task board and one
  table; show there is no page-level horizontal overflow and controls remain
  usable.
- Tab through two controls to show the focus indicator and point to the live
  status/error announcements.
- Refresh a nested task URL to show client routing survives a direct load.

### S11 — 9:40–10:00: reproducible quality result

- Show a prepared, readable terminal excerpt with: 275 Django tests passed,
  96.3% total branch coverage, 4 files / 18 frontend tests passed, OpenAPI validation
  with zero warnings/errors, TypeScript passing and the Vite production build.
- End on the dashboard and state that install, configuration, API and exact
  reproduction commands are in the root README.

## Recording checklist

- [ ] Duration is 9:30–10:00 and the cursor/text are readable at 1080p.
- [ ] Every feature claimed in the report is visibly operated, not only named.
- [ ] A validation/permission failure and recovery are shown.
- [ ] Owner, invitee and moderator browser sessions are visually distinguishable.
- [ ] No password, secret key, cookie, private email content or persistent token
      appears in the video; retrieve the local single-use OTP off-camera.
- [ ] Audio identifies the architectural reason for server-side security,
      transaction services, cached external data and soft-retained evidence.
- [ ] Final Canvas upload plays correctly from start to finish.
