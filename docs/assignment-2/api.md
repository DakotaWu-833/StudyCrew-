# StudyCrew REST API

This document describes the implemented version 1 JSON interface. The generated
OpenAPI source is available at [`/api/schema/`](../../config/urls.py) while the
server is running and is also checked into the repository as
[`openapi.yml`](openapi.yml).

## Conventions

- Base path: `/api/v1/`
- Media type: `application/json`, except an export download (CSV or PDF), avatar
  upload (`multipart/form-data`) or avatar image response (`image/jpeg`).
- Identifiers: UUID strings.
- Date-times: timezone-aware ISO 8601/RFC 3339 strings.
- Dates: `YYYY-MM-DD`.
- Collection responses are paginated as
  `{"count": n, "next": url|null, "previous": url|null, "results": [...]}`.
  The configured page size is 50; the supplied React client follows same-origin
  `next` links until the complete result set is loaded.
- Successful creates return `201 Created`; reads and updates return `200 OK`;
  successful soft-deletes return `204 No Content`.
- All paths retain the trailing slash shown below.

## Authentication and CSRF

`GET /api/v1/health/` is public. Every other version 1 endpoint requires a
Django database-backed session that was established only after both the
password and email one-time-code steps completed. A password-only session, a
missing MFA marker, or a tampered marker receives `401`.

StudyCrew intentionally does not expose a JSON password-login endpoint. Sign in
through `/account/login/`, enter the six-digit code at `/account/verify/`, then
use the API from the same browser session. In local development the default
file email backend writes the message containing the code beneath `var/emails/`.
The `seed_demo` command prints newly generated local passwords once; no password
is committed to the repository.

The browser sends the `sessionid` cookie automatically. For `POST`, `PUT`,
`PATCH`, and `DELETE`, it must also copy the `csrftoken` cookie into the
`X-CSRFToken` header. The React client implements this in
`frontend/src/api/client.ts`; omitting the header is rejected with `403`.
Production additionally relies on HTTPS origin/referer validation.

For a local API inspection tool, first complete MFA in the browser and copy the
two cookie values from that localhost session. Do not share or record them.
Replace only the placeholders in this example:

```bash
curl --request POST http://127.0.0.1:8000/api/v1/projects/ \
  --header "Accept: application/json" \
  --header "Content-Type: application/json" \
  --header "X-CSRFToken: <csrftoken>" \
  --cookie "sessionid=<sessionid>; csrftoken=<csrftoken>" \
  --data '{"name":"COMP3609 delivery","description":"Plan the final submission","due_at":"2026-10-25T23:59:00+11:00"}'
```

Safe `GET` requests still require the session cookie but not the CSRF header:

```bash
curl --header "Accept: application/json" \
  --cookie "sessionid=<sessionid>" \
  http://127.0.0.1:8000/api/v1/me/
```

## Error contract

API errors use one stable envelope. Validation errors add a `fields` object;
authentication, permission and not-found responses deliberately avoid internal
details.

```json
{
  "error": {
    "code": "validation_error",
    "message": "Please correct the highlighted fields.",
    "fields": {
      "title": ["Ensure this field has at least 3 characters."]
    }
  }
}
```

| HTTP status | `error.code` | Meaning |
| --- | --- | --- |
| 400 | `validation_error` | Input, domain rule, or database constraint rejected the request. |
| 401 | `not_authenticated` | The session is absent, expired, or has not completed MFA. |
| 403 | `permission_denied` | The authenticated user lacks the required membership, role, ownership, or CSRF proof. |
| 404 | `not_found` | The resource does not exist or is unavailable at that route. |
| 405 | `method_not_allowed` | The resource does not implement that HTTP verb. |
| 429 | `throttled` | A configured request throttle rejected the request. |
| 503 | `service_unavailable` | Invitation delivery failed and was rolled back, or a reminder batch was not fully confirmed and no successful-send audit event was recorded. The action can be retried. |
| 500 | `server_error` | A safe generic failure; exception text and traceback are logged, not returned. |

## Endpoint reference

### System and current account

| Method and path | Input | Access and result |
| --- | --- | --- |
| `GET /api/v1/health/` | None | Public database liveness result: `{"status":"ok","database":"ok"}`. |
| `GET /api/v1/me/` | None | Current user summary, email, profile and `site_moderator` capability. |
| `GET /api/v1/profile/` | None | Read the current user's profile. |
| `PUT /api/v1/profile/` | Full profile body | Replace writable profile fields for the current user. |
| `PATCH /api/v1/profile/` | Any of `display_name`, `course_code`, `time_zone`, `biography`, `avatar_url` | Partially update only the current user's profile. Email and `updated_at` are read-only. |
| `POST /api/v1/profile/avatar/` | Multipart `avatar` (JPG, PNG or WebP, at most 2 MB) | Re-encodes the current user's photo to a bounded square JPEG and returns the updated profile. |
| `GET /api/v1/users/{user_id}/avatar/` | None | Current user or a current teammate in a shared active project; serves the photo privately. |
| `GET /api/v1/time-zones/` | None | Global IANA time-zone list as `{count, results: [{value, label, offset}]}`; labels include current GMT offsets. |
| `POST /api/v1/account/email-change/request/` | `new_email`, `current_password` | Verifies the current password and emails a short-lived six-digit code to the new address. Returns `request_id` and `new_email`, never the code. |
| `POST /api/v1/account/email-change/confirm/` | `request_id`, `code` | Consumes a valid one-time code, switches the current user's sign-in address and notifies the old address. |
| `GET /api/schema/` | None | Public generated OpenAPI 3 document; this route is outside the versioned API. |

The current profile form intentionally omits the legacy `course_code` and
`avatar_url` fields, but the existing JSON profile contract retains them for
older clients. Email is never changed through profile `PUT` or `PATCH`; it uses
the password-and-new-address-verification flow above. The configured local
email backend writes verification messages under `var/emails/`; production
requires SMTP delivery. Avatar images are accessed through the authenticated
API route, not a public `/media/` URL.

### Projects and contribution evidence

| Method and path | Input or filters | Access and result |
| --- | --- | --- |
| `GET /api/v1/projects/` | Optional `scope=active|archived|all`, plus `page`; default `active` | List projects in which the current user has a retained membership. |
| `POST /api/v1/projects/` | `name`, optional `description`, optional `due_at` | Any active authenticated user; creates the project and its owner membership atomically. |
| `GET /api/v1/projects/{project_id}/` | None | Any current member, including retained read-only history after archive. |
| `PUT /api/v1/projects/{project_id}/` | All of `name`, `description`, `due_at` | Project owner only; complete replacement. Archived projects reject writes. |
| `PATCH /api/v1/projects/{project_id}/` | Any of `name`, `description`, `due_at` | Project owner only; partial update. Archived projects reject writes. |
| `DELETE /api/v1/projects/{project_id}/` | None | Project owner only; soft-archives the project and retains evidence. |
| `GET /api/v1/projects/{project_id}/activity/` | `page` | Project members; paginated immutable activity events. |
| `GET /api/v1/projects/{project_id}/insights/` | `range_start`, `range_end`, optional `event_type` | Project members; factual member totals and work charts. Omitted dates default to the latest 30 days in the requesting user's profile time zone. |
| `GET /api/v1/projects/{project_id}/timeline/` | `range_start`, `range_end`, optional `event_type`, `search`, `member`, `page` | Project members; server-filtered activity, returned five events at a time. |

An insight range cannot exceed 366 days. Zero-activity current members remain in
the result. The timeline search matches member names, activity types and target
types; `member` filters by actor. Its `events_total`, `events_page`,
`events_pages` and `events_page_size` describe the filtered result. The
activity-type filter changes the member `total_events` and timeline, while the
timeline's search/member filters narrow only the timeline. Work-distribution
charts and trend series are part of the insights response; there is no separate
chart endpoint, contribution score, grade or ranking field. Evidence exports
continue to include the complete matching event set and are not subject to the
five-event display page size.

Archived projects are omitted from the default active list and are available
through `scope=archived` or `scope=all`. The workspace exposes them in an
Archived projects section. Retained members may read and export historical
evidence, but task, comment, meeting, invitation and membership mutations are
rejected.

### Tasks

| Method and path | Input or filters | Access and result |
| --- | --- | --- |
| `GET /api/v1/tasks/?project={project_id}` | Required `project`; optional `q`, `status`, `priority`, `assignee`, `due`, `page` | Project members; active tasks only. |
| `POST /api/v1/tasks/` | Required `project`, `title`; optional `description`, `priority`, `due_at` | Any active project member. |
| `GET /api/v1/tasks/{task_id}/` | None | Project members; an archived task remains retrievable by its ID. |
| `PUT /api/v1/tasks/{task_id}/` | All of `title`, `description`, `priority`, `due_at` | Any current member of a non-archived project; complete replacement. `project` cannot be moved. |
| `PATCH /api/v1/tasks/{task_id}/` | Any of `title`, `description`, `priority`, `due_at` | Any current member of a non-archived project; partial update. |
| `DELETE /api/v1/tasks/{task_id}/` | None | Any active project member; soft-archives it. |
| `PUT /api/v1/tasks/{task_id}/assignees/` | `assignee_ids: UUID[]` | Any active project member; replaces the complete assignee set. Every assignee must be a current member of the same project. |
| `POST /api/v1/tasks/{task_id}/transition/` | `status`, and `blocker_note` when blocked | The project owner or a current assignee. |
| `POST /api/v1/tasks/{task_id}/send-reminder/` | Empty JSON object | Project owner or facilitator only; emails each eligible current assignee other than the sender and returns `recipient_count` plus `sent_at`. |

Task statuses are `todo`, `in_progress`, `blocked`, and `done`; priorities are
`low`, `medium`, `high`, and `urgent`. The `due` filter accepts `overdue`,
`upcoming`, or `none`. A blocked task requires a 3–500 character blocker note.

Task reminder recipients are derived by the server from active, email-verified
project memberships and current assignments. The endpoint accepts no address or
recipient identifier, rejects archived tasks/projects and an empty eligible set,
and applies a 60-second cooldown to the same task. The integration sends a
separate plain-text message to each recipient so no teammate address appears in
another recipient's headers.

Example transition:

```http
POST /api/v1/tasks/95e97cf8-29ef-4474-9cbe-0b269c17ea2d/transition/
Content-Type: application/json
X-CSRFToken: <csrftoken>

{
  "status": "blocked",
  "blocker_note": "Waiting for the deployment hostname"
}
```

### Task comments and reports

| Method and path | Input or filters | Access and result |
| --- | --- | --- |
| `GET /api/v1/comments/?task={task_id}` | Required `task`, optional `page` | Project members. Soft-deleted entries remain as evidence with an empty body and `is_deleted: true`. |
| `POST /api/v1/comments/` | `task`, `body`, optional `mentioned_user_ids` | Project members. Mentioned IDs must be current members of the same project. |
| `GET /api/v1/comments/{comment_id}/` | None | Project members. |
| `PUT` or `PATCH /api/v1/comments/{comment_id}/` | `body` | The author, or a project owner/facilitator moderating another member's comment. |
| `DELETE /api/v1/comments/{comment_id}/` | None | The author, or a project owner/facilitator; soft-deletes the body. |
| `POST /api/v1/comments/{comment_id}/report/` | `reason`, optional `details` | Project members; one pending report per reporter/comment. |

Report reasons are `abuse`, `privacy`, `spam`, and `other`. Selecting `other`
requires details at the domain-validation layer. Site-wide report resolution is
intentionally handled by the separate, least-privilege `/control/` interface,
not by this project API.

### Meetings and public-holiday advisory

| Method and path | Input or filters | Access and result |
| --- | --- | --- |
| `GET /api/v1/meetings/?project={project_id}` | Required `project`; optional `scope=active|archived|all`, `search` (up to 120 characters), `state=all|scheduled|ended|cancelled|archived`, `page`, `page_size` (1–50, default 5) | Project members. Filtering occurs before server pagination, ordered by `starts_at` then `id`. `active` means every non-archived meeting, including retained cancelled/ended records; `archived` and `all` make historical evidence explicit. |
| `POST /api/v1/meetings/` | `project`, `title`, timezone-aware `starts_at`, `ends_at`; optional `location`, `agenda` | Any active project member. End must be after start and neither instant may exceed the inclusive ten-calendar-year horizon at validation time. |
| `GET /api/v1/meetings/{meeting_id}/` | None | Project members; includes `cancelled_at`, `archived_at` and derived `lifecycle_state`. |
| `PUT /api/v1/meetings/{meeting_id}/` | All of `title`, `starts_at`, `ends_at`, `location`, `agenda` | Organiser, project facilitator, or project owner; complete replacement of a scheduled meeting in a non-archived project. |
| `PATCH /api/v1/meetings/{meeting_id}/` | Any meeting fields except `project` | Organiser, project facilitator, or project owner; partial update of a scheduled meeting in a non-archived project. |
| `POST /api/v1/meetings/{meeting_id}/cancel/` | Empty JSON object | Organiser, project facilitator, or project owner; explicitly soft-cancels a scheduled meeting and retains attendance. |
| `DELETE /api/v1/meetings/{meeting_id}/` | None | Organiser, project facilitator, or project owner; archives only a cancelled or ended meeting. Repeating an archive is idempotent. |
| `POST /api/v1/meetings/{meeting_id}/restore/` | Empty JSON object | Organiser, project facilitator, or project owner; returns an archived record to the non-archived list in an active project. It retains its original cancelled/ended state and attendance. |
| `PUT /api/v1/meetings/{meeting_id}/rsvp/` | `response`, optional `availability_note` | Any active project member; upserts one RSVP only while the meeting is scheduled. |
| `GET /api/v1/meetings/{meeting_id}/holiday/` | None | Project members; returns a non-blocking Australian public-holiday advisory. |
| `POST /api/v1/meetings/{meeting_id}/send-reminder/` | Empty JSON object | Project owner or facilitator only; emails each eligible current project member other than the sender and returns `recipient_count` plus `sent_at`. |

Meeting lifecycle is `scheduled -> cancelled or ended -> archived`. `ended` is
derived when the current time reaches `ends_at`; cancellation and archival have
retained timestamps. Cancelled/ended meetings remain in the default non-archived
scope until explicitly archived, while archived meetings are read-only. The
ten-year limit uses calendar-year replacement rather than 3,650 days and safely
contracts 29 February to 28 February when the target year is not a leap year.

The workspace requests five records per page. Invalid page/page-size bounds,
unknown states and overlong search terms return `400`; a well-formed page beyond
the filtered result set returns `404`. Dashboard clients request batches of 50
and still follow `next` to collect every page. Restoring an archived record does not reopen an ended
session or undo its cancellation.

RSVP values are `pending`, `accepted`, and `declined`. A cancelled, ended or
archived meeting rejects RSVP changes. The holiday endpoint is the only path
that consults Nager.Date. It uses the meeting date in
`Australia/Sydney`, caches a validated response by calendar year, and returns
one of `live`, `cache`, `stale`, or `unavailable` in `source`. Provider failure
still returns `200` with `available: false`; it never prevents meeting CRUD.

Meeting reminder recipients are active, email-verified current project members
other than the sender and are derived entirely by the server. Cancelled, ended,
archived or archived-project meetings reject reminder dispatch, as does an empty
eligible set. A 60-second cooldown applies to each meeting.

Both reminder endpoints return this address-free shape after the mail backend
confirms every separate message:

```json
{
  "recipient_count": 3,
  "sent_at": "2026-09-20T06:45:00Z"
}
```

A confirmed dispatch appends one immutable `task_reminder_sent` or
`meeting_reminder_sent` event containing only the recipient count. A backend
exception or incomplete batch returns the safe `503` envelope and does not
append that success event. An external mail system may already have accepted a
subset before reporting an incomplete batch, so the API never falsely claims
that email delivery itself can be rolled back.

```json
{
  "meeting_date": "2026-10-05",
  "available": true,
  "is_public_holiday": true,
  "holiday_name": "Labour Day",
  "source": "cache",
  "message": "This meeting falls on Labour Day."
}
```

### Invitations and memberships

| Method and path | Input or filters | Access and result |
| --- | --- | --- |
| `GET /api/v1/invitations/` | Optional `project`, `page` | Without `project`, lists pending invitations matching the current user's email. With `project`, lists its invitations for the owner only. |
| `POST /api/v1/invitations/` | `project`, `invited_email` | Project owner only; creates a seven-day invitation and emails the authenticated acceptance link. |
| `DELETE /api/v1/invitations/{invitation_id}/` | None | Project owner only; cancels a pending invitation. |
| `POST /api/v1/invitations/{invitation_id}/accept/` | Empty JSON body | Only the active user whose normalised email matches the pending invitation. Creates or restores one member row. |
| `POST /api/v1/invitations/{invitation_id}/decline/` | Empty JSON body | Only the matching invitee. |
| `GET /api/v1/memberships/?project={project_id}` | Required `project`, optional `page` | Any active project member. |
| `PUT` or `PATCH /api/v1/memberships/{membership_id}/` | `role` (`member` or `facilitator`) | Project owner only. The owner role uses the transfer action instead. |
| `DELETE /api/v1/memberships/{membership_id}/` | None | Project owner only; soft-removes a non-owner and revokes project access. |
| `POST /api/v1/memberships/{membership_id}/transfer-ownership/` | Optional `previous_owner_role` (`member` or `facilitator`) | Current project owner only; atomically preserves exactly one owner. |

Membership responses use a Team-specific `user` summary: `id`, `display_name`,
`avatar_image_url`, `avatar_url` and `avatar_version`. An uploaded photo uses the
existing private avatar endpoint; the version matches the profile's `updated_at`
timestamp. Missing photos return an empty image URL, with the legacy `avatar_url`
available as a fallback. The Team displays initials when no usable image exists.
Profile updates invalidate cached member lists so a subsequent Team visit reads
the new identity. These read-only fields do not permit changing another member's
photo, expose private storage paths, or change other resources' user summaries.

The invitation create response additionally contains a `share_token`. It is
shown only on that response, stored only as a SHA-256 digest, and never returned
by later list calls. A registered matching user also receives an in-app
notification. Acceptance and decline are single-use; replay returns a safe
validation error.

### Notifications and exports

| Method and path | Input or filters | Access and result |
| --- | --- | --- |
| `GET /api/v1/notifications/` | Optional `unread=true`, `page` | Lists only the current user's notifications. |
| `GET /api/v1/notifications/{notification_id}/` | None | Notification recipient only. |
| `PATCH /api/v1/notifications/{notification_id}/read/` | Empty JSON body | Notification recipient only; idempotently marks it read. |
| `GET /api/v1/exports/` | Optional `page` | Lists only the current user's export jobs for projects they can still access. |
| `POST /api/v1/exports/` | `project`, `format`, `range_start`, `range_end` | Project member; generates a factual `csv` or `pdf` evidence file. |
| `GET /api/v1/exports/{export_id}/` | None | Requesting user only while still a project member. |
| `GET /api/v1/exports/{export_id}/download/` | None | Requesting user only; returns CSV or PDF when the job is ready and unexpired. |

Export ranges use the same 366-day limit as insights. Ready files expire after
24 hours. An internal generation failure is retained as `status: "failed"` with
a safe retry message rather than exposing the exception. In production the
authorised Django response delegates file bytes to Nginx using an internal
redirect; the media directory itself is not public.

## Project resource example

Request:

```http
POST /api/v1/projects/
Content-Type: application/json
X-CSRFToken: <csrftoken>

{
  "name": "COMP3609 delivery",
  "description": "Plan the final submission",
  "due_at": "2026-10-25T23:59:00+11:00"
}
```

Response (`201 Created`):

```json
{
  "id": "366c9e6a-c41b-4974-bad4-20b54685e2d6",
  "name": "COMP3609 delivery",
  "description": "Plan the final submission",
  "due_at": "2026-10-25T12:59:00Z",
  "created_by": {
    "id": "0ce03a38-9769-42cf-9851-836ed49aaf21",
    "display_name": "Alex Morgan"
  },
  "created_at": "2026-09-13T11:30:00Z",
  "updated_at": "2026-09-13T11:30:00Z",
  "archived_at": null,
  "current_user_role": "owner",
  "member_count": 1
}
```

## Deliberate API boundaries

- The API is a same-origin session API, not a public token API; JWT, OAuth and
  cross-origin credential login are out of scope.
- Account registration, password login, OTP verification, password change and
  logout are server-rendered security workflows under `/account/`.
- Project membership is checked for every project-owned object. A global site
  moderator does not bypass private project boundaries.
- Project “manager” actions mean a current project owner or facilitator. They do
  not grant the separate global site moderator access to reminders or project
  data.
- Transactional email is limited to OTPs, invitations and explicit task/meeting
  reminders. Reminder endpoints accept no caller-provided addresses and never
  expose recipient addresses in their response or audit metadata.
- Delete operations retain collaboration/audit evidence through archive,
  removal or body-redaction states. Meeting cancellation is a separate explicit
  action because `DELETE` represents terminal-state archival.
- The API provides no bulk write endpoint and no WebSocket interface. The
  selected modern-web option is the routed React/TypeScript client with Fetch
  and React Query.
