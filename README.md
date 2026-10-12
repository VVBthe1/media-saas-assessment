# Tenant Provisioning Control Plane

**Tech stack:** FastAPI, SQLAlchemy async, Postgres, RabbitMQ.

Architecture overview and design decisions are in [section 6](#6-architecture).

## 1. Initial setup

**Prerequisites:** Docker Compose v2 only. `docker compose up` starts **postgres**, **rabbitmq**, **api**, **worker**, and **simulator** only (Compose profile `testing` services are not started on `up`).

```bash
git clone https://github.com/VVBthe1/media-saas-assessment.git && cd media-saas-assessment
```

Copy `.env.example` to `.env` only if you need to change published ports or credentials.

## 2. Boot and verification

Start the stack:

```bash
docker compose up --build
```

**Test command** (brief lifecycle suite; stack must be up — second terminal if `up` is in the foreground):

```bash
docker compose --profile testing run --rm e2e
```

Quality gates (lint, format, bandit, pytest — no stack required; run separately):

```bash
docker compose --profile testing run --rm check
```

Rebuild `check` / `e2e` images after changing `tests/` or `scripts/` (`--build`).

Use the default **simulator** at **`fail-rate=0`** (section 3 demos with other flags will break the lifecycle part).

## 3. Components


| Service     | Reachable at                                                                                                               |
| ----------- | -------------------------------------------------------------------------------------------------------------------------- |
| `api`       | [http://127.0.0.1:8000](http://127.0.0.1:8000) — Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)      |
| `worker`    | Console app (no HTTP); logs: `docker compose logs -f worker`                                                               |
| `simulator` | Console app (no HTTP); logs: `docker compose logs -f simulator`                                                            |
| `postgres`  | `127.0.0.1:5432` (user `postgres`, password `postgres`, database `control_plane`)                                          |
| `rabbitmq`  | `amqp://guest:guest@127.0.0.1:5672/` — management UI: [http://127.0.0.1:15672](http://127.0.0.1:15672) (`guest` / `guest`) |


If a URL above fails, try `localhost` instead of `127.0.0.1` (or the reverse).

**Logs**

```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f simulator
```

**Postgres shell**

```bash
docker compose exec postgres psql -U postgres -d control_plane
```

**Simulator with custom flags** (stack already running):

The default `simulator` service uses **`--fail-rate=0`**, **`--min-delay-ms=0`**, **`--max-delay-ms=0`** (no artificial delay, always `done`). Flags are read **once at process start**; change behavior by stopping the compose `simulator` and starting a new process with different args (examples below).

**Assumptions (how the flags behave):**

| Flag | Range / default | Effect |
|------|-----------------|--------|
| `--fail-rate` | `0.0`–`1.0`, default `0` | After each task message, once `in_progress` is published, the simulator draws **once** per task: with probability `fail-rate` it publishes `failed`, otherwise `done`. Independent per task (e.g. `0.3` ≈ 30% of tasks fail). |
| `--min-delay-ms` | non-negative int, default `0` | With `--max-delay-ms`, defines a **random pause in milliseconds** between publishing `in_progress` and publishing `done` or `failed`. If `min > max`, the simulator swaps them. `0`/`0` means no pause. |
| `--max-delay-ms` | non-negative int, default `0` | Upper bound for that pause (uniform random between min and max, inclusive). |

Flow for every consumed task: `in_progress` → optional delay → `done` or `failed` (never skip `in_progress`).

**Demos** (custom fail-rate or delay — not compatible with e2e; stop the compose `simulator` first):

```bash
docker compose stop simulator
docker compose ps --status running | grep simulator || true   # should print nothing
```

Slow provisioning (2–5s) and partial failures:

```bash
docker compose run --rm --build simulator \
  python -m simulator --fail-rate=0.3 --min-delay-ms=2000 --max-delay-ms=5000
```

Guaranteed failed deploy (then `DELETE` via API — see curls in section 5):

```bash
docker compose run --rm simulator python -m simulator --fail-rate=1 --min-delay-ms=0 --max-delay-ms=0
```

Deterministic **failed** state without simulator timing (after `POST /tenants`, use `id` from the response):

```bash
pip install -r requirements.txt   # asyncpg; skip if using a venv that already has deps
python3 scripts/seed_failed_deploy.py '<tenant-uuid>'
```

The automated e2e suite calls the same script; prefer `--fail-rate=1` for manual demos when you can.

### Publish progress to RabbitMQ (manual)

Brief negative / messaging demos; stack up; **worker** must be running. Progress uses exchange `task_updates`, routing key `task.progress`, JSON body `update_id`, `task_id`, `status` (`in_progress` | `done` | `failed`). Full schema: [Messaging](#messaging).

```bash
# Host (published ports): needs aio-pika from requirements.txt
export BROKER_URL=amqp://guest:guest@127.0.0.1:5672/

# After POST /tenants — pick the deploy task id from GET /tenants/{id}/tasks
TASK_ID='<task-uuid>'
python3 scripts/publish_task_progress.py --task-id "$TASK_ID" --status in_progress --update-id "$(uuidgen)"
python3 scripts/publish_task_progress.py --task-id "$TASK_ID" --status done --update-id "$(uuidgen)"
```

Or via Docker (no local venv; uses internal broker URL):

```bash
docker compose --profile testing run --rm e2e python scripts/publish_task_progress.py \
  --task-id '<task-uuid>' --status in_progress --update-id "$(uuidgen)"
```

Use a **new** `--update-id` per distinct delivery; repeat the same id to test idempotency. Out-of-order cases (e.g. `in_progress` after `done`) are automated in `scripts/e2e_suite.py`.

Restore the default simulator after a demo:

```bash
docker compose up -d simulator
```



## 4. Local development

Optional. Sections [1–2](#1-initial-setup) are the reviewer path (Docker only). Use this section to run services or scripts on your machine.

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Test suite and quality gates

Local (same steps as the Docker `check` service):

```bash
pip install -r requirements-test.txt -r requirements-lint.txt
black --check --line-length 100 src tests scripts/
pylint src
bandit -r src -ll -q
PYTHONPATH=src pytest -q
```

Pylint prints warnings and conventions; Docker `check` only fails on pylint **errors/fatals** (not on warning-only exit codes) and still runs bandit and pytest afterward.

#### Security scan (Bandit)

The brief’s optional **security scanner** is [Bandit](https://bandit.readthedocs.io/) (`bandit==1.8.2` in `requirements-lint.txt`), run as part of `check`:

```bash
bandit -r src -ll -q
```

| | |
|--|--|
| **Scope** | Recursively scans **`src/`** only (application code). Not `tests/`, `scripts/`, or `migrations/`. |
| **`-ll`** | Report issues from **low** severity upward and **low** confidence upward (stricter than Bandit’s default filter). |
| **`-q`** | Quiet output unless findings exist. |
| **Typical findings** | Common Python issues Bandit models with static rules, e.g. hardcoded passwords/tokens, `subprocess` with `shell=True`, weak or deprecated crypto/hashing, unsafe `pickle`/`yaml.load`, `assert` used as runtime control flow, and similar patterns in the [Bandit plugin list](https://bandit.readthedocs.io/en/latest/plugins/index.html). |
| **Not covered** | Dependency/CVE scanning (no `pip-audit` / OSV), containers or Compose hardening, TLS/mTLS, authz (out of scope), or proving absence of secrets in git history. Dev broker/DB credentials in Compose are documented as local-only. |

A clean `check` run means Bandit reported no issues at the configured threshold. **Black** (format) and **pylint** (lint) are separate steps in the same command; they are not security scanners.

Pytest only: `pip install -r requirements-test.txt` then `PYTHONPATH=src pytest -q`.

In Docker (profile `testing`):

```bash
docker compose --profile testing run --rm check   # quality gates only, no running stack
docker compose --profile testing run --rm e2e     # lifecycle only (stack must be up)
```

### E2E on the local machine

With the stack on published ports (`127.0.0.1:8000`, `5432`, `5672`) — e.g. after `docker compose up` or the processes below — and the compose **simulator** at **`fail-rate=0`**:

```bash
source .venv/bin/activate
python3 scripts/e2e_suite.py
```

Optional: `API_BASE`, `BROKER_URL`, `E2E_DATABASE_URL` (defaults match Compose on localhost). For e2e in Docker, use [section 2](#2-boot-and-verification).

### API, worker, and simulator on the host

```bash
docker compose up -d postgres rabbitmq
cp .env.example .env
PYTHONPATH=src alembic upgrade head
```

Three terminals (`.venv` activated, `PYTHONPATH=src`):

```bash
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

```bash
python -m backend.workers
```

```bash
python -m simulator
```

## 5. Project layout

```
.
├── docker-compose.yaml
├── Dockerfile
├── alembic.ini
├── .env.example
├── requirements.txt
├── requirements-test.txt
├── requirements-lint.txt
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── scripts/
│   ├── e2e_suite.py
│   ├── publish_task_progress.py
│   └── seed_failed_deploy.py
├── src/
│   ├── backend/
│   │   ├── app.py
│   │   ├── routes.py
│   │   ├── broker.py
│   │   ├── db.py
│   │   ├── settings.py
│   │   ├── events/
│   │   ├── exceptions/
│   │   ├── models/
│   │   ├── services/
│   │   └── workers/
│   │       └── __main__.py
│   └── simulator/
│       └── __main__.py
└── tests/
    ├── test_concurrency.py
    ├── test_messaging.py
    └── test_state_machines.py
```

## 6. Architecture

### Overview

```mermaid
flowchart LR
  Client --> API
  API --> DB[(Postgres)]
  API -->|after commit| MQ[(RabbitMQ)]
  MQ --> Sim[Simulator]
  Sim -->|task.progress| MQ
  MQ --> Worker
  Worker --> DB
```

The API handles tenant mutations and publishes tasks after commit. The simulator consumes new tasks and publishes progress. The worker consumes progress and updates tasks and tenants in Postgres.

### State machines (Copied from brief for reference.)

Task:

```mermaid
stateDiagram-v2
    accepted --> in_progress : result
    in_progress --> done : result
    in_progress --> failed : result
```

Tenant:

```mermaid
stateDiagram-v2
    provisioning --> active : deploy done
    provisioning --> failed : deploy failed
    active --> updating : PATCH
    updating --> active : update done
    updating --> failed : update failed
    active --> destroying : DELETE
    destroying --> destroyed : destroy done
    destroying --> failed : destroy failed
    failed --> destroying : DELETE
```

DELETE is allowed from `active` or `failed` (see `failed → destroying` above).

### HTTP API

| Method | Path | Notes |
|--------|------|--------|
| `GET` | `/health` | Health check → `200` |
| `GET` | `/tenants` | List → `200`; `offset`, `limit`, optional `status` filter |
| `POST` | `/tenants` | Create → `202` |
| `GET` | `/tenants/{id}` | Get → `200` |
| `PATCH` | `/tenants/{id}` | Body: `name`, `version` → `202` |
| `DELETE` | `/tenants/{id}` | Delete → `202` |
| `GET` | `/tenants/{id}/tasks` | Paginated task list → `200` |
| `GET` | `/tasks` | Paginated global task list → `200` |
| `GET` | `/tasks/{id}` | Get → `200` |

Mutations return the tenant resource. Tasks are not created over HTTP; they follow tenant mutations and worker progress.

Tenant and task `created_at` / `updated_at` are ISO 8601 UTC with millisecond precision and a `Z` suffix in JSON.

Interactive reference: Swagger UI at http://127.0.0.1:8000/docs .

**API usage examples** (stack running; set `API` and reuse `TENANT_ID` / `version` from JSON responses):

```bash
API=http://127.0.0.1:8000

# List tenants (optional ?status=active&status=provisioning, offset, limit)
curl -sS "$API/tenants"

# Create tenant → 202; starts deploy task (simulator drives provisioning → active)
curl -sS -X POST "$API/tenants" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Acme Corp","slug":"acme-corp"}'

export TENANT_ID='<id-from-create-response>'
export VERSION='<version-from-create-response>'

# Update tenant (only when status is active; bump version on every successful mutation)
curl -sS -X PATCH "$API/tenants/$TENANT_ID" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"Acme Corporation\",\"version\":$VERSION}"

# Delete tenant (from active or failed) → destroy task
curl -sS -X DELETE "$API/tenants/$TENANT_ID"

# List tasks for a tenant
curl -sS "$API/tenants/$TENANT_ID/tasks"
```

### Messaging

After each mutating tenant API call, the API commits to Postgres then publishes a task. Progress messages use a separate exchange; the worker applies them to Postgres.

| Flow | Exchange | Queue / routing key | Payload |
|------|----------|-------------------|---------|
| Task published on create/update/delete | `tasks` | `tasks.created` / `task.created` | `id`, `type`, `tenant_id`, `status` |
| Progress from simulator | `task_updates` | `task.progress` / `task.progress` | `update_id`, `task_id`, `status` |

Which key deduplicates what

| Concern | Key | Where it lives |
|---------|-----|----------------|
| Duplicate progress delivery | `update_id` on the progress message | `processed_updates.id` (one row per `update_id`; not scoped to tenant or task) |
| Concurrent tenant PATCH/DELETE | `version` on the tenant | `tenants.version` (optimistic locking on API) |
| Duplicate slug on create | `slug` | unique constraint on `tenants.slug` |

Task publish messages are not deduplicated by a separate store: each successful API mutation creates one task with a new `id` and sends one message.

Progress consumer (brief requirements):

- Idempotent: duplicate `update_id` is ignored after the first successful handling.
- Order-tolerant: invalid or late steps do not move task or tenant backward; terminal tasks are not reopened.
- Resilient: transient DB errors are retried with backoff; malformed or permanently invalid messages are rejected so the consumer keeps running. Message consumption is at-least-once from RabbitMQ; idempotency handles redelivery.

Late or invalid progress (for example `in_progress` after `done`) does not change task or tenant state, per the task state diagram. A new `update_id` for such a message is still recorded in `processed_updates` so redelivery stays safe.

**Manual broker publish** — commands in [§3 Publish progress to RabbitMQ (manual)](#publish-progress-to-rabbitmq-manual). Script: `scripts/publish_task_progress.py`.

### HTTP errors

All API error responses include:

```json
{"error": {"code": "...", "message": "..."}}
```

| `error.code` | Typical HTTP status |
|--------------|---------------------|
| `tenant_not_found` | 404 |
| `task_not_found` | 404 |
| `tenant_already_exists` | 409 |
| `tenant_update_not_allowed` | 409 |
| `tenant_version_conflict` | 409 |
| `invalid_slug`, `invalid_tenant_name` | 422 |
| `validation_error` | 422 (plus FastAPI `detail` list: `loc`, `msg`, `type`) |

### Decisions

| Topic | Choice | Why |
|-------|--------|-----|
| Authentication / authorization | Out of scope | Brief focuses on provisioning state, concurrency, and messaging; API and broker are open on localhost for the exercise. A production service would add tenant-scoped auth, mTLS or credentials on the broker, and secrets management. |
| HTTP error shape | `error.code` / `error.message` on all failures | Domain errors use that object only; validation adds FastAPI’s `detail` alongside it. |
| When tasks are published | After DB `commit` | Task row and tenant state are durable before the broker sees the message. If the API crashes after commit but before publish, that task may exist in DB without a message (no separate “pending publish” table). |
| Progress idempotency | `update_id` in `processed_updates` | Broker may deliver the same progress more than once. |
| Progress ordering | Task state diagram | Invalid transitions are ignored; terminal tasks never go back to non-terminal statuses. |
| One open task per tenant | Partial unique index on `tasks` where status is `accepted` or `in_progress` | Enforces at most one open task per tenant in the database. |
| Tenant `version` | Bumped on PATCH, DELETE, and worker tenant status apply | Optimistic locking for API; worker status changes count as mutations. |
| Concurrent PATCH | Update only if `version` still matches | Two PATCHes with the same `version` → one `202`, one `409` `tenant_version_conflict`. |
| Concurrent create (same slug) | Unique `slug` | Two parallel creates → one `202`, one `409` `tenant_already_exists`. |
| Worker errors | Retry temporary DB errors a few times with backoff; reject bad messages | Consumer keeps running; one bad message does not block the queue. |
| Simulator | Separate process, CLI flags | `--fail-rate`, `--min-delay-ms`, `--max-delay-ms` for failure and delay without code changes. |
| Persistence | Postgres data in a Compose volume | Tenants and tasks survive `docker compose` restarts. |
| Security scan | Bandit in Docker `check` (see [Security scan (Bandit)](#security-scan-bandit)) | Brief quality gates; optional but wired with lint/format/tests. |
| Logging | `backend/logging_config.py` (`configure_logging`) | One timestamped format on stderr for `api`, `worker`, `simulator`, and uvicorn access lines so async steps are easy to line up in `docker compose logs`. |

### Assumptions

- No authentication or authorization on HTTP or RabbitMQ (see Decisions above).
- Postgres holds durable tenant/task state; RabbitMQ may redeliver messages.
- Slugs stay unique for destroyed tenants; reusing a slug returns `tenant_already_exists`.
- Dev credentials in Compose (`guest`, `postgres`) are for local use only.
