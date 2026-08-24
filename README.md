# DevOps Swarm

A multi-agent system that resolves GitHub issues end to end: it reads the
repository, writes an implementation plan, implements it in an isolated cloud
sandbox, runs the test suite, reviews its own diff for security defects, and
opens a draft pull request that states honestly whether the tests passed.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-4A90D9?style=flat-square)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/tests-159%20passing-success?style=flat-square)

---

## What it does

Open an issue on a connected repository, or trigger a run from the console:

1. **Architect** fetches the file tree and the files the issue touches, then
   posts an implementation plan as an issue comment — before a line is written,
   so a human can object first.
2. **Coder** clones into an [E2B](https://e2b.dev) sandbox, implements the plan,
   lints, commits, and runs the tests. On failure it reads the actual error,
   installs missing dependencies, and retries — up to three rounds.
3. **Reviewer** reads the complete diff against the base commit, runs a security
   scan, and returns an explicit `APPROVED` or `NEEDS_REVISION`.
4. **PR** opens a draft pull request stating the test outcome and the review
   verdict, then comments the link back on the issue.

Every agent thought, tool call and result streams to the console over a
WebSocket and is persisted, so a run can be replayed after the fact.

---

## Architecture

```
GitHub issue opened
        │
        ├── POST /webhook   (HMAC-SHA256 verified, deliveries de-duplicated)
        └── POST /trigger   (API key + repository allowlist)
        │
        ▼
   RunExecutor ──── concurrency ceiling, graceful drain, guaranteed terminal state
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  LangGraph StateGraph                                        │
│                                                              │
│  START ─▶ SUPERVISOR ─┬─▶ ARCHITECT ─┐                       │
│              ▲        ├─▶ CODER ─────┤                       │
│              │        ├─▶ REVIEWER ──┤                       │
│              └────────┴──────────────┘                       │
│                       └─▶ PR ─▶ END                          │
│                                                              │
│  Only the supervisor writes `phase`. Attempts are counted so │
│  an agent returning nothing fails the run with a readable    │
│  message instead of looping to the recursion limit.          │
└──────────────────────────────────────────────────────────────┘
        │
        ├─▶ PostgreSQL      runs + agent_logs (Alembic-migrated)
        ├─▶ WebSocket       live stream, resumable by sequence number
        └─▶ /metrics        Prometheus: RED signals + swarm counters
```

**Repository layout**

```
backend/
  app/
    api/          HTTP + WebSocket routes
    agents/       graph, nodes, prompts, state
    core/         logging, redaction, security, rate limiting, metrics
    db/           models, repository
    services/     run executor
    tools/        GitHub REST tools, E2B sandbox tools, sandbox registry
  alembic/        schema migrations
  tests/          159 tests
frontend/
  src/app/        App Router pages
  src/components/ console UI
  src/lib/        typed API client, polling + stream hooks
```

---

## Quick start

```bash
cp .env.example .env
```

Fill in the three required keys (all have free tiers):

| Key | Where |
|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) |
| `E2B_API_KEY` | [e2b.dev](https://e2b.dev) |
| `GITHUB_PAT` | GitHub → Settings → Developer settings → Personal access tokens |

Then:

```bash
docker compose up --build
```

The console is at <http://localhost:3000> and the API at
<http://localhost:8000> (interactive docs at `/docs` outside production).
Migrations run as their own service before the API starts.

### Running without Docker

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cd frontend && npm ci && npm run dev
```

---

## Security model

The trigger endpoint spends your GitHub credentials against whatever repository
it is handed, so two controls gate it and both are validated at startup:

- **`API_KEYS`** — comma-separated keys required on every mutating endpoint.
  Empty means no authentication, which is allowed in development and refused
  when `ENVIRONMENT=production`.
- **`REPO_ALLOWLIST`** — `owner/repo` entries the swarm may act on. `*` is
  refused in production.

Other properties worth knowing about:

- **Credentials never enter a command string.** The GitHub token reaches git
  through an environment-backed credential helper, never a remote URL, and never
  lands in `.git/config`.
- **Everything an agent emits is redacted** at the single point where it crosses
  into the database and the WebSocket — token shapes, `user:pass@host` URLs,
  `Authorization` headers and PEM blocks, plus every credential registered for
  the live run.
- **Model-generated strings never reach a shell unquoted.** Commit messages,
  search patterns and package names go through `shlex.quote`; the two tools that
  execute generated Python read their input from the environment instead of
  interpolating it into source.
- **Webhooks fail closed.** An unset `GITHUB_WEBHOOK_SECRET` rejects every
  delivery rather than accepting all of them.
- Both containers run as a non-root user with `no-new-privileges`.

> If you ran an earlier version of this project, rotate your GitHub, Groq and
> E2B keys. Prior builds embedded the GitHub token in git remote URLs and
> streamed raw command output to the database and browser, so a failed push
> could persist the token in plain text.

---

## Configuration

Everything is environment-driven; see `.env.example` for the annotated set.
The values you are most likely to change:

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` enforces auth, allowlist and CORS |
| `MAX_CONCURRENT_RUNS` | `3` | Each run holds a billed sandbox |
| `MAX_CORRECTION_ITERATIONS` | `3` | Coder retries after a failing test run |
| `TOOL_RESULT_CHAR_BUDGET` | `6000` | Tool output handed back to the model |
| `RATE_LIMIT_TRIGGERS_PER_HOUR` | `20` | Per API key, or per IP when unauthenticated |
| `LOG_FORMAT` | `console` | Use `json` in production |

---

## Operations

| Endpoint | Purpose |
|---|---|
| `GET /health` | Readiness — round-trips the database |
| `GET /health/live` | Liveness — no I/O, safe for restart policies |
| `GET /metrics` | Prometheus exposition |

Metrics cover HTTP RED signals plus run outcomes, per-agent node duration, LLM
call outcomes, tool latency, active sandboxes and open WebSockets. Every log
line and error response carries a `request_id`, also returned in the
`X-Request-ID` header.

**Scaling note.** WebSocket fan-out and the run executor are per-process, so the
service runs one worker per replica and scales behind a sticky-session load
balancer. Moving `ConnectionManager.broadcast` to Redis pub/sub and `submit()`
to a durable queue removes that constraint; both are single-file changes.

---

## Development

```bash
cd backend
ruff check . && ruff format --check . && mypy app && pytest
```

```bash
cd frontend
npm run lint && npm run typecheck && npm run build
```

CI runs all of the above, plus a secret scan, a vulnerability scan, both Docker
image builds, and a smoke test that boots the full stack and asserts the API
reports `"database":"up"`.

### Adding a migration

Models are the source of truth; migrations are generated from them.

```bash
cd backend
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

CI applies and rolls back every migration, so a one-way migration fails the
build.

---

Built by Sowaiba Arshad.
