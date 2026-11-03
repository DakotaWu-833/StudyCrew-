# StudyCrew

StudyCrew is a private collaboration workspace for university project teams. It
combines project membership, a task board, meeting coordination and factual
contribution evidence so a team can find delivery risk early without turning
activity counts into grades.

This repository contains the complete Assignment 2 implementation and the
reviewed Assignment 3 deployment/security configuration. Assignment 1 design
artifacts remain under `design/`, `database/` and `deliverables/`.

**Assignment 3 final submission branch: `advance`.** The AWS deployment uses the
reviewed release from this branch. Assess `advance` for the A3 code submission.

## Implemented functionality

- Email registration and login with 12-character password rules, Argon2 hashes,
  persistent account/IP lockout, expiring single-use email OTP and idle session
  expiry.
- Personal profile with private photo upload, worldwide IANA time-zone search
  and password-plus-email-code verification when changing the sign-in address.
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

The `advance` branch extends this baseline with account recovery and privacy,
private courses and terms, assignment planning and reviews, availability polls,
meeting minutes and actual action tasks, discussions and mentions, broad search,
notification preferences, reliable queues, support and operational tooling.
It also includes consent-based team recruiting, private project file versions,
and previewed assignment CSV exchange. The latest local enhancements add private
file previews and text-version comparisons, a 30-day recycle bin, recurring tasks,
explainable team recommendations, task time records and factual workload views,
polling project chat, and explicitly selected offline task edits with field-by-field
conflict resolution. The UI remains in English; interface language switching is
outside this change. Project knowledge and the assistant add cited retrieval,
model-selected read tools and task drafts that users explicitly review and
confirm before saving. See [local expansion details](docs/advance-local-expansion.md).
See [the advance feature and acceptance checklist](docs/advance-readiness.md)
and [local operation and deployment instructions](docs/launch-operations.md).

For the local version using PowerShell 7 after dependencies and the
frontend build are available:

```powershell
.\scripts\Start-Advance.ps1 -Port 8003
.\scripts\Start-Advance.ps1 -Demo -Port 8002
```

The first command serves existing local accounts and data at
`http://127.0.0.1:8003/app/`, with sign-in codes under `var/emails/`. The second
runs an isolated demo at `http://127.0.0.1:8002/app/`, with sign-in codes under
`var/advance-preview-emails/`. Each runs the web app and independent worker;
choose one for the intended dataset. These commands do not publish a public
service or configure real SMTP. The `advance` implementation is developed and
verified locally. Publishing its Git history does not deploy a public service.

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
| `USE_X_ACCEL_REDIRECT` | protected Nginx hand-off for production avatars and exports |

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
- `/recruiting/`, `/files/`, `/learning-exchange/`
- `/productivity/`, `/chat/` and `/offline/`
- `/knowledge/` for project retrieval, assistant requests and reviewed task creation

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

## Project knowledge (local advance)

Open a project and choose **Knowledge** to search its latest private files and
meeting notes. Source search works immediately without a model or API key.
Install the updated `requirements/dev.txt` before running the application.

Knowledge parses the latest TXT, CSV, text-bearing PDF and DOCX files and active
meeting notes, chunks the text, and returns labelled excerpts with file versions
and PDF page numbers. Default retrieval is local BM25 with English words and
Chinese character bigrams. Optional `hybrid` retrieval combines BM25 with the
configured embedding model, exact cosine similarity and reciprocal-rank fusion.

Embedding vectors are cached in a database JSON field keyed by project, content
SHA-256 and a hashed namespace of model name, vector dimension and
`RAG_EMBEDDING_REVISION` (the installed embedding-model weight digest). Retrieval
rebuilds the current authorised source list
and uses only vectors matching those current chunks; cached vectors are not a
source of historical text. This is a bounded small-corpus implementation, without
pgvector or an approximate-nearest-neighbour index. It checks at most 200 current
chunks semantically and reports when that window is exceeded. If embedding
generation or its shared retrieval budget fails, the response uses BM25 and
includes a fallback warning. A successful hybrid response reports
`retrieval: "hybrid"`; a fallback reports `"bm25"`.

The backend supports optional Ollama and compatible chat-completion services.
Generation is disabled by default (`RAG_PROVIDER=disabled`,
`RAG_RETRIEVAL_MODE=bm25`); the UI distinguishes source search from generated
answers. After completing the backend/frontend setup above, use PowerShell 7
for the selected local chat and embedding models:

```powershell
.\scripts\Setup-StudyCrewAI.ps1
.\scripts\Start-StudyCrewAI.ps1 -Port 8003
# Or choose the separate demonstration dataset:
.\scripts\Start-StudyCrewAI.ps1 -Demo -Port 8002
```

Setup prepares portable Ollama and the tags `qwen3.5:9b-q4_K_M` for chat/tool
calling and `qwen3-embedding:0.6b` for retrieval. Runtime/model files stay under
the workspace's ignored `var/ai/` directory. The launcher enables hybrid
retrieval with 1,024-dimensional embeddings, warms both models with synthetic
text, reads the installed embedding digest into the cache revision, applies
migrations and starts the local web app and delivery worker.
Use one dataset/port for the intended run. Setup and launch do not publish a
service, establish answer quality or prove GPU residency.

This Qwen setup is the separate local desktop/GPU profile. The small AWS Learner
Lab deployment uses Groq `openai/gpt-oss-20b` for chat/tools and local
`all-minilm:l6-v2` with 384-dimensional embeddings. See the
[split chat and embedding configuration](deployment/ai/compatible-local-embeddings.md)
for that profile and its English/context limitations.

For manual configuration of an already-running local Ollama service:

```powershell
$env:RAG_PROVIDER = 'ollama'
$env:RAG_BASE_URL = 'http://127.0.0.1:11434'
$env:RAG_MODEL = 'qwen3.5:9b-q4_K_M'
$env:RAG_RETRIEVAL_MODE = 'hybrid'
$env:RAG_EMBEDDING_MODEL = 'qwen3-embedding:0.6b'
$env:RAG_EMBEDDING_DIMENSIONS = '1024'
$studyCrewTags = Invoke-RestMethod -Uri "$env:RAG_BASE_URL/api/tags" -NoProxy -MaximumRedirection 0 -TimeoutSec 5
$studyCrewEmbedding = @($studyCrewTags.models | Where-Object name -eq $env:RAG_EMBEDDING_MODEL)
if ($studyCrewEmbedding.Count -ne 1 -or $studyCrewEmbedding[0].digest -notmatch '^[0-9a-f]{64}$') {
    throw 'Verify the installed embedding model digest before enabling its cache.'
}
$env:RAG_EMBEDDING_REVISION = $studyCrewEmbedding[0].digest
.\scripts\Start-Advance.ps1 -Port 8003
```

For manual/production configuration, verify the installed digest and update
`RAG_EMBEDDING_REVISION` whenever weights change, including when a model tag is
reused. Changing the dimension or revision selects a different cache namespace.

For a compatible service, set `RAG_PROVIDER=compatible`, `RAG_BASE_URL` to its
API base including `/v1`, `RAG_MODEL` to the served model, and `RAG_API_KEY` if
required. For hybrid retrieval alongside compatible chat, independently select
the Ollama embedding provider/base as described in the
[split configuration](deployment/ai/compatible-local-embeddings.md). Use
`RAG_RETRIEVAL_MODE=bm25` when no embedding service is configured. Non-loopback
endpoints require HTTPS. The configured chat service receives the question and
selected private excerpts; embedding requests send candidate chunk text to the
separately selected embedding endpoint. Keys and credentials stay on the server.
Environment configuration alone does not install models or provision hardware.
`.env.example` is a reference, not auto-loaded.

See [local setup and GPU deployment](deployment/ai/README.md) for model storage,
process ownership, GPU/CPU checks and the separate inference deployment pack.
The existing [school deployment runbook](docs/assignment-3/deployment-runbook.md)
still governs the web application's production controls. A short architecture
walkthrough and demonstration sequence are in
[the AI project showcase](docs/ai-project-showcase.md).

The project API exposes:

- `GET /api/v1/knowledge/projects/{id}/` for available capabilities.
- `POST /api/v1/knowledge/projects/{id}/search/` for source excerpts.
- `POST /api/v1/knowledge/projects/{id}/ask/` for retrieval plus optional generation.

Both POST requests accept `question` (1–1000 characters) and optional
`max_sources` (1–6, default 5). Ask responses explicitly distinguish `answered`,
`no_evidence`, `model_unavailable` and `unverified_answer`. Missing/unavailable
models retain useful source excerpts. Answers with missing or unknown citation
labels are withheld. Valid citation labels establish which excerpts were used;
they do not prove every generated claim is correct. Check the original sources.

`knowledge/output_guardrails.py` also withholds RAG/Agent answers and generated
drafts that repeat recognizable credential literals from the selected source
excerpts, including labelled passwords and common API-token formats. Authorised
source previews retain the original text. This is limited source-derived pattern
matching, not complete data-loss prevention or comprehensive prompt-injection
protection.

Every request rechecks the current account and project membership. File integrity
and scan requirements remain enforced. Selected sources and access are checked
again before model egress and after generation; changed or withdrawn sources
require a fresh question. Responses are private/no-store, and questions and
results are not saved to browser storage or a model history table. This feature
only reads material. Hybrid mode persists private embedding vectors in the
application database; it does not persist questions, generated answers or raw
retrieval chunks as a separate document index.

Default coverage is the latest 20 files and 40 active meeting notes, with a
5 MiB per-file / 20 MiB aggregate file budget, 32,000 characters per file and
the first 30 PDF pages. PDF/DOCX parsing runs in a separate process with a
3-second per-file timeout and an 8-second retrieval budget. A RAG question shares
a 24-second overall retrieval/generation budget. Model transport is capped at
15 seconds by default, or 20 seconds with the AI launcher, and also respects the
remaining question budget. Timed-out or truncated generation is withheld while
source excerpts remain available. These budgets leave intended headroom under
the existing 30-second web-worker timeout; verify actual queueing and runtime
overhead on the deployment host. Warnings identify partial searches, unreadable
files and formats without extractable text; OCR is not included. Uploaded
spreadsheets, slide decks and archives are not searched in this first release.

Automated RAG tests use local files and stub model/embedding responses to verify
retrieval, finite vectors, fusion/fallback, permissions, current-source checks,
citations and transport failures. Those checks do not establish real model
quality. Record real model digests, retrieval outcomes, answer checks and actual
timings separately.

With the local model service running, a separate terminal can run the disposable
synthetic evaluation:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_project_ai.py
```

The default report is `var/ai/evaluation-latest.json`; use `--output` with another
path to retain a separate run. The script creates a temporary SQLite database,
media and accounts, compares BM25/hybrid retrieval, calls the real models, and
exercises read-only Agent proposals plus an explicit approval/replay on synthetic
tasks. It does not use existing project data. This is a small smoke evaluation,
not a general accuracy estimate, load test or browser/deployment acceptance test.
Factual-term matches do not prove semantic correctness; manually inspect the
recorded answers, citations and missing-evidence/injection cases. No result is
claimed here.

### Project assistant

The project's **Assistant** page adds a bounded model tool-calling loop using the
same model configuration. Choose a model that supports tool calling; compatible
servers may also require their model-specific tool parser to be configured.
The assistant is unavailable by default while `RAG_PROVIDER=disabled`; Knowledge
source search remains usable without a model.

The model can select three server-authorised tools:

- `search_project_sources`: search current files and meeting notes within this project.
- `list_project_tasks`: read current task descriptions, statuses and deadlines.
- `propose_tasks`: prepare up to five source-cited task drafts in request memory.

No tool accepts a project ID from the model. The server binds every tool to the
signed-in user's selected project, validates every argument and rechecks access
and source currency before each model turn and before returning the result.
These model tools only read evidence and propose drafts: they cannot create or
change tasks, execute commands, open external URLs or send messages. Drafts are
explicitly unsaved, and existing task titles are omitted from proposals.
Questions, model answers, tool histories and unapproved draft text stay in
request/component memory.

Each eligible draft has a short-lived signed approval token. The user can edit
its title (3–120 characters) and description (up to 2,000 characters), select
**Create task**, then confirm the named task in a separate dialog. Only this
user-operated endpoint creates a real task through the existing task service:

`POST /api/v1/knowledge/projects/{id}/assistant/tasks/`

It accepts `approval_token`, `title` and `description`. The token expires after
600 seconds and binds the current user, project, proposal nonce and cited source
snapshots. The server rechecks account access, project archival state, source
currency and duplicate active task titles before creating the task. Archived
project drafts have `can_create=false`. Expired or changed-source drafts require
a fresh assistant request.

Creation and its unique user/project/token receipt are committed in one
transaction. Identical retries within the valid approval window return the
existing task with `created=false`; a different edited payload for the same
receipt is rejected. The UI retains the original confirmed token/payload after
failure, blocks concurrent duplicate confirmation and shows the created task
link. Approved task text and source references are stored as a normal task;
the database receipt stores token/payload digests and the resulting task ID.
This is explicit task creation by the user, separate from the model's tool loop.

`GET /api/v1/knowledge/projects/{id}/assistant/` returns available capabilities.
`POST` to the same endpoint accepts only `question` (1–1000 text characters).
Results include labelled source excerpts, a short tool-use trace, optional
unsaved drafts, and one of `completed`, `model_unavailable`, `no_evidence`,
`invalid_response` or `limit_reached`. Unknown tools, invalid arguments and
fabricated citations are stopped; partial runs withhold answers and task drafts.
For a final answer with missing/incorrect citation labels, the assistant may
make one citation-format correction using evidence it has already read. The
correction consumes an existing model turn and the same overall deadline;
it cannot call additional tools. If it still fails, the answer and drafts are
withheld.

Limits are four model turns, six tool calls, twelve retained source excerpts,
and at most twenty matching current tasks (the source budget may retain fewer).
`RAG_AGENT_TIMEOUT_SECONDS` defaults to 22 seconds, shared by retrieval and model
turns; a setting between 1 and 24 seconds is allowed. The AI launcher uses 24
seconds. These are application budgets, not measured latency guarantees; verify
upstream timeouts and queueing on the deployment host. Source and task snapshots are
rechecked after model calls; withdrawn or edited evidence requires a new request.
Tool labels and citation checks establish provenance, not factual accuracy.
Evaluate real model responses after configuring a provider.

### Derived-data maintenance

In the intended instance's database environment, inspect expired private
embedding vectors and approval receipts before deleting them:

```powershell
.\.venv\Scripts\python.exe manage.py purge_knowledge_data
# After reviewing the reported candidates:
.\.venv\Scripts\python.exe manage.py purge_knowledge_data --execute
```

The default dry run changes no data. Defaults retain vectors for 14 days and
receipts for 30 days from their creation time, with at most 1,000 deletions per
table in one execution. `--embedding-days`, `--receipt-days` and `--limit` override
the bounded settings. Created project tasks remain retained, and missing vectors
can be rebuilt when needed. Operators should run this maintenance explicitly or
configure and verify its schedule; backup retention is a separate policy.

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

Historical baseline verified locally on 1 October 2026: 374 Django tests, 96.2% combined statement/branch
coverage (86.7% minimum among reported files), 15 files/91 Vitest cases, zero-warning OpenAPI
validation, TypeScript checking and a production build all passed. An executable
architecture test also prevents domain-to-HTTP imports,
external HTTP outside `integrations/` and direct frontend API calls outside the
shared client.

Historical `advance` checks before the AI additions passed 836 backend tests, 36 frontend files/213 tests,
type checking, production build and strict zero-warning schema validation.
Combined coverage with branch measurement enabled is 91.8% (93.6% statements,
83.9% branches). Integrated browser and isolated SQLite recovery evidence are
tracked separately in [the local acceptance document](docs/advance-local-expansion.md);
the historical counts above do not cover the seven latest enhancements.

Task serialization stays at four database queries, including membership checks,
for 1, 5 and 10 records with identical output. The Meetings screen uses filtered
server pages of five records; dashboard full-list callers retain their existing
contract and request larger batches. Browser-rendered visual acceptance and live
production deployment remain separate checks, not implied by these local gates.

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
| `integrations/` | Nager.Date, private email and bounded chat/tool/embedding HTTP adapters |
| `knowledge/` | authorised corpus, BM25/hybrid retrieval, assistant tools, signed approvals and receipts |
| `recruiting/` | consent-based discovery, bounded applications and admission |
| `documents_store/` | private file uploads, version history, quotas and scanner boundary |
| `learning_exchange/` | explicit CSV preview/import and source-aware deduplication |
| `productivity/` | bounded recurring task generation, personal time records and factual workload |
| `project_chat/` | private polling conversations, bounded presence and message withdrawal |
| `offline_sync/` | account-bound, revision-checked and idempotent selected-task synchronization |
| `api/` | REST authentication, serializers, views, errors and schema |
| `web/` | public shell and custom moderation centre |
| `frontend/` | React/TypeScript source and tests |
| `deploy/` | Nginx, uWSGI, systemd, PostgreSQL and verification assets |
| `deployment/ai/` | optional GPU inference container and local-model setup/deployment guidance |
| `docs/assignment-2/` | rubric, API, testing and demo evidence |
| `docs/assignment-3/` | deployment and security evidence |

## Deliberate scope limits

- Contribution figures are factual counts, never grades or quality scores.
- Public-holiday advice is Australian and advisory; meeting creation still works
  when the provider or cache is unavailable.
- Evidence export supports the advance asynchronous worker and bounded course-scale datasets.
- Modern Web option 1 is used. Project chat polls every 2 seconds while visible
  and every 10 seconds in the background; it uses no WebSocket transport.
- Private offline task copies require explicit selection and stay in this
  browser's IndexedDB for at most 24 hours: up to 200 copies and 50 pending edits.
  Service Worker caching covers public code and the generic offline shell only,
  never API responses or the rest of a private workspace.
- Account recovery is implemented on `advance`. Assignment CSV exchange is
  manual; university OAuth, institution SSO and live LMS data synchronisation
  remain outside the implemented local scope.
