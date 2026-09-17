# StudyCrew REST API

This document describes the implemented version 1 JSON interface. The generated
OpenAPI source is available at [`/api/schema/`](../../config/urls.py) while the
server is running and is also checked into the repository as
[`openapi.yml`](openapi.yml).

## Conventions

- Base path: `/api/v1/`
- Media type: `application/json`, except an export download, which returns CSV or
  PDF bytes.
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
| 503 | `service_unavailable` | Invitation email delivery failed; its database transaction was rolled back and can be retried. |
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
| `GET /api/schema/` | None | Public generated OpenAPI 3 document; this route is outside the versioned API. |

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
| `GET /api/v1/projects/{project_id}/insights/` | `range_start`, `range_end`, optional `event_type` | Project members; per-member factual totals and up to 200 drill-down events. Omitted dates default to the latest 30 days in the requesting user's profile time zone. |

An insight range cannot exceed 366 days. Zero-activity current members remain in
the result. `events_truncated: true` tells the client that the 200-event display
limit was reached.

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

Task statuses are `todo`, `in_progress`, `blocked`, and `done`; priorities are
`low`, `medium`, `high`, and `urgent`. The `due` filter accepts `overdue`,
`upcoming`, or `none`. A blocked task requires a 3–500 character blocker note.

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
| `GET /api/v1/meetings/?project={project_id}` | Required `project`, optional `page` | Project members; retained cancelled meetings are included. |
| `POST /api/v1/meetings/` | `project`, `title`, timezone-aware `starts_at`, `ends_at`; optional `location`, `agenda` | Any active project member. End must be after start. |
| `GET /api/v1/meetings/{meeting_id}/` | None | Project members. |
| `PUT /api/v1/meetings/{meeting_id}/` | All of `title`, `starts_at`, `ends_at`, `location`, `agenda` | Organiser, project facilitator, or project owner; complete replacement in a non-archived project. |
| `PATCH /api/v1/meetings/{meeting_id}/` | Any meeting fields except `project` | Organiser, project facilitator, or project owner; partial update in a non-archived project. |
| `DELETE /api/v1/meetings/{meeting_id}/` | None | Organiser, project facilitator, or project owner; soft-cancels it. |
| `PUT /api/v1/meetings/{meeting_id}/rsvp/` | `response`, optional `availability_note` | Any active project member; upserts one RSVP. |
| `GET /api/v1/meetings/{meeting_id}/holiday/` | None | Project members; returns a non-blocking Australian public-holiday advisory. |

RSVP values are `pending`, `accepted`, and `declined`. The holiday endpoint is
the only path that consults Nager.Date. It uses the meeting date in
`Australia/Sydney`, caches a validated response by calendar year, and returns
one of `live`, `cache`, `stale`, or `unavailable` in `source`. Provider failure
still returns `200` with `available: false`; it never prevents meeting CRUD.

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
- Delete operations retain collaboration/audit evidence through archive,
  cancellation, removal, or body-redaction states.
- The API provides no bulk write endpoint and no WebSocket interface. The
  selected modern-web option is the routed React/TypeScript client with Fetch
  and React Query.
