# StudyCrew local models and GPU deployment

This pack supplies model setup and a GPU inference service. It is not evidence
of a public deployment. The PowerShell scripts serve the local application only
on `127.0.0.1`; Docker configuration needs validation on the actual deployment
host. A public school launch still needs the domain, server, SMTP, TLS,
PostgreSQL and access checks described in [launch operations](../../docs/launch-operations.md).

The Qwen chat/embedding models below belong to the local desktop/GPU profile.
The small AWS Learner Lab instead uses the separate
[compatible chat with local MiniLM embeddings profile](compatible-local-embeddings.md).

## Windows local setup

Use PowerShell 7 after installing the documented Python dependencies and
building the frontend. From the repository root:

```powershell
.\scripts\Setup-StudyCrewAI.ps1
.\scripts\Start-StudyCrewAI.ps1 -Port 8003
# Optional separate demonstration database:
.\scripts\Start-StudyCrewAI.ps1 -Demo -Port 8002
```

Setup pins the official portable Ollama `v0.40.3` Windows AMD64 archive to
SHA-256 `e5ecff02dfc7cae8ddf6d6b7a7ac5f727ffeedf4491f44ae75ff5b0820dbbbd5`.
It compares a new download with the official GitHub release asset digest before
extraction. Cached ZIP files must also match the checksum. It installs no UI,
login item or service and changes no user or machine environment variables.
The runtime goes in `var/ai/runtime`, model blobs in `var/ai/models`, and logs
and a synthetic setup receipt in `var/ai/`. These paths stay on the workspace
drive; for this checkout that is F:. The scripts also recognize an already
verified runtime at `var/ai/ollama-v0.40.3/ollama.exe`; setup reuses it when the
cached release archive has the pinned digest, avoiding a second extracted copy.

The selected local tags are `qwen3.5:9b-q4_K_M` and
`qwen3-embedding:0.6b`. The explicit chat quantization tag avoids choosing a
different runtime variant through a moving default tag. Model tags may still
be updated upstream: the setup receipt records installed model digests, and a
deployment record should retain them before upgrades. Reserve at least 16 GiB
free for a fresh runtime/model installation. The chat file is about 6.6 GB;
that download size does not establish its complete RAM or VRAM requirement.

Setup pulls models only into a server it started with the workspace model path.
If an existing healthy loopback server already has both tags, it reuses them
without pulling. If either tag is missing, setup stops with a clear message:
the existing server's model-store location cannot be verified, so it does not
download several gigabytes into a potentially full C: drive. Quit that service
yourself and rerun setup. Neither script discovers and terminates other Python
or Ollama processes. Their retained process objects identify their own children;
Ctrl+C/failure cleanup stops only those children and restores process settings.

Both scripts reject an existing port 11434 listener on a non-loopback address.
Cloud features, CLI history and request debug logging are disabled for servers
the scripts create. Existing reused services keep their own server settings;
configure those flags independently before using private project material.

The launcher configures hybrid retrieval, an 8,192-token context, up to 1,200
output tokens, thinking disabled, one parallel inference request per model,
up to two loaded models and ten-minute keep-alive. It warms chat and embedding
with synthetic text before starting web/worker processes. Setup reports
`nvidia-smi` inventory when available; `ollama ps` reports actual GPU/CPU
offload. GPU availability and model residency must be measured, not inferred
from the presence of a graphics card. CPU/offloaded inference may exceed the
default 20-second model and 24-second Agent budgets. Adjust only within the
backend's supported limits after testing representative requests.

These launchers use the existing local SQLite datasets and file-based email.
Normal mode preserves existing accounts; demo mode selects the separate demo
database. They do not configure public SMTP or seed a production database.

## GPU service beside the production web host

The preferred small deployment keeps the existing hardened Django/uWSGI,
Nginx, delivery worker, SMTP and PostgreSQL runtime roles, and adds GPU inference
on the same host. The Dockerfile builds only the inference service and never
copies the repository, private files, database or application environment.
Install Docker Compose and the NVIDIA Container Toolkit on the real GPU host.
Check available GPU memory and reserve a data disk with at least 16 GiB free.

```sh
sudo install -d -m 0750 /srv/studycrew/ai/models
cp deployment/ai/.env.example /srv/studycrew/ai/compose.env
docker compose --env-file /srv/studycrew/ai/compose.env -f deployment/ai/compose.yaml config
docker compose --env-file /srv/studycrew/ai/compose.env -f deployment/ai/compose.yaml build
# Explicit temporary network access for public model downloads:
docker compose --env-file /srv/studycrew/ai/compose.env -f deployment/ai/compose.yaml --profile setup run --rm model-download
docker compose --env-file /srv/studycrew/ai/compose.env -f deployment/ai/compose.yaml up -d ollama
docker compose --env-file /srv/studycrew/ai/compose.env -f deployment/ai/compose.yaml exec ollama ollama list
```

Use an absolute `OLLAMA_MODEL_DIR` on the chosen deployment data disk. The
regular service has an internal network, no registry egress, a read-only root
filesystem and a temporary writable directory. Only `127.0.0.1:11434` is
published on the host. The provisioning service has temporary download egress,
no published port and a loopback-only server inside its container. Provision
before regular startup; stop inference before rerunning model provisioning.
Pin the pulled base-image digest in your release record as well as its version
tag. Container health checks establish API reachability, not model readiness.
Warm both models with synthetic `/api/chat` (`think:false`) and `/api/embed`
requests and inspect `ollama ps` before testing real users.

Merge [the AI environment example](studycrew-ai.env.example) into the protected
application environment at `/etc/studycrew/studycrew.env`; do not replace the
existing production configuration. On the same host, Django uses the loopback
model endpoint. Retain real SMTP, PostgreSQL `studycrew_app` runtime credentials,
the distinct migration role, required malware scanning, TLS, secure cookies,
protected media handoff and privacy logging. After schema migrations, reapply
`deploy/postgresql/permissions.sql` and
`deployment/postgresql/launch-permissions.sql`, then run the launch permissions
verifier as `studycrew_app`. Apply any reviewed explicit privileges needed by
the new embedding-cache table before enabling cache cleanup.

Keep `deploy/uwsgi.ini` plus `deployment/uwsgi-privacy.ini` and the existing
Nginx privacy/token-route includes. Default 20/24-second AI budgets fit under
the existing 30-second uWSGI/Nginx limit only when local retrieval, queues and
model latency leave sufficient headroom. Test this under concurrency. If
measured work needs longer deadlines, change the application and upstream
timeouts together in a reviewed deployment change; do not claim success from
configuration checks alone. Maintain regular worker, backup and restore checks.

## Separate GPU host

If web and GPU hosts are separate, preserve the inference container's loopback
port and expose a private, authenticated HTTPS gateway on the GPU host. Restrict
gateway reachability to the web server using network/firewall policy. Use a
valid TLS certificate trusted by the application runtime and a protected bearer
credential configured as `RAG_API_KEY`; put the gateway origin in
`RAG_BASE_URL`. The current transport requires HTTPS for remote hosts and never
accepts credentials in the URL. Do not publish Ollama itself or its unauthenticated
API through a public domain. Direct client-certificate authentication needs an
appropriate gateway/sidecar; it is not implemented by the current Python adapter.
Benchmark network latency and queueing as part of the application deadline.

Hybrid retrieval caches embedding vectors as JSON in the application database,
keyed to project, source-content fingerprints, and a hashed namespace of model
name, vector dimension and `RAG_EMBEDDING_REVISION` weight digest. The native
launcher obtains the digest from `/api/tags`; verify and update the production
environment's revision whenever weights change. It ranks with exact cosine similarity plus
keyword retrieval. It is a bounded small-corpus implementation, not pgvector or
an approximate-nearest-neighbor service. Model files and cache vectors are
different artifacts. Retain project permissions, deletion/update invalidation
and receipt checks when backing up or replacing either. A source citation
establishes provenance; it does not prove a generated claim is correct.

RAG retrieval and generation share a 24-second application budget; Agent shares
its configured maximum of 24 seconds across all model/tool turns. Database and
source-integrity checks still need measured headroom under the 30-second web
worker limit. The model output checker withholds recognizable source-derived
credential literals; this is a limited pattern check, not general DLP or a proof
against all prompt injection. Valid citations alone do not establish entailment.

Use `manage.py purge_knowledge_data` to preview expired vector/receipt cleanup.
The explicit `--execute` run retains vectors for 14 days and receipts for 30 days
by default, with a bounded batch per table. Confirmed tasks remain. The launch
SQL's DELETE allowlist includes both knowledge tables; reapply it after migration
and verify using the actual runtime role before scheduling this maintenance.

## Verification boundary

`config.tests.test_ai_deployment` validates source-level isolation, pinned
downloads, process ownership and PowerShell syntax without launching services.
No local Docker/NVIDIA-container test or public server verification is implied
by those results. Release evidence should separately record real model digests,
GPU offload, warm/cold timings, multilingual source retrieval, cited RAG and
Agent runs, draft approval/receipt behavior, denied cross-project requests,
SMTP/TLS checks and an isolated backup restore on the actual deployment host.

Sources: [official Ollama release](https://github.com/ollama/ollama/releases/tag/v0.40.3),
[Ollama model storage, GPU offload and concurrency](https://docs.ollama.com/faq),
[Ollama Docker GPU setup](https://docs.ollama.com/docker), and
[the embedding API](https://docs.ollama.com/api/embed).
