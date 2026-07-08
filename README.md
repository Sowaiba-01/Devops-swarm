# 🤖 DevOps Swarm AI

> **A production-grade multi-agent system that autonomously resolves GitHub issues — reads the issue, writes code in an isolated cloud sandbox, runs tests, self-corrects up to 3×, and opens a draft PR. No human in the loop.**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2-4A90D9?style=flat-square)
![Groq](https://img.shields.io/badge/Groq-Llama_3.3_70B-F55036?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![E2B](https://img.shields.io/badge/E2B-Cloud_Sandbox-FF6B35?style=flat-square)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql&logoColor=white)

---

## What this actually does

You assign a GitHub issue. The swarm autonomously:

1. **Reads** the issue and the entire repository structure via GitHub API
2. **Plans** the implementation — which files to change, how to test it
3. **Writes** the code in an E2B cloud sandbox (isolated, safe, reproducible)
4. **Runs** the test suite. If tests fail, it reads the errors and **tries again** (up to 3 iterations)
5. **Reviews** its own code — security scan + quality check
6. **Opens a draft PR** on GitHub with full test output and review notes

You get a PR link. You review and merge. That's it.

---

## Architecture

```
GitHub Issue
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│                    LangGraph StateGraph                  │
│                                                         │
│  START → [SUPERVISOR] ──────────────────────────────┐  │
│               │                                     │  │
│          ┌────┴────┐                                │  │
│          ▼         │                                │  │
│     [ARCHITECT]    │  Reads repo structure          │  │
│      ReAct loop    │  Produces implementation plan  │  │
│          │         │                                │  │
│          └────►[SUPERVISOR]                         │  │
│               │                                     │  │
│          ┌────┴────┐                                │  │
│          ▼         │                                │  │
│       [CODER]      │  Clones repo → writes code     │  │
│      ReAct loop    │  Runs tests → commits          │  │
│     (up to 3×)     │  Pushes branch to GitHub       │  │
│          │         │                                │  │
│          └────►[SUPERVISOR]                         │  │
│               │                                     │  │
│          ┌────┴────┐                                │  │
│          ▼         │                                │  │
│     [REVIEWER]     │  Reads diff → security scan    │  │
│      ReAct loop    │  APPROVED or NEEDS_REVISION    │  │
│          │         │                                │  │
│          └────►[SUPERVISOR]                         │  │
│               │                                     │  │
│          ┌────┴────┐                                │  │
│          ▼         │                                │  │
│      [PR NODE]     │  Opens draft PR on GitHub      │  │
│          │         │                                │  │
│         END ◄──────┘                                │  │
└─────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Deterministic supervisor** — routing is pure Python (`if/else` on `state["phase"]`), not an LLM call. This makes the control flow predictable and debuggable.
- **ReAct pattern per agent** — each agent runs a Reason → Act → Observe loop with tool calls until it reaches a conclusion, not a single-shot prompt.
- **E2B cloud sandboxes** — code runs in an isolated Linux VM, not the host machine. Sandboxes are long-lived (30 min) and keyed by `run_id` so they survive across multiple agent steps.
- **Push before sandbox dies** — the coder node pushes to GitHub immediately after committing, before handing back to the supervisor. Eliminates the "not a git repo" failure mode from sandbox timeout.
- **WebSocket pub/sub** — every agent thought, tool call, and result streams to the frontend in real time via a per-run-id connection manager.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Agent orchestration** | LangGraph StateGraph | Explicit state machine with conditional routing — not a black-box chain |
| **LLM** | Groq + Llama 3.3 70B | Free-tier inference at 500 tokens/sec — fast enough for real-time streaming |
| **Code execution** | E2B cloud sandboxes | Isolated Linux VM per run — safe, reproducible, no host contamination |
| **Backend** | FastAPI + async SQLAlchemy | Async throughout — WebSocket + HTTP from one process |
| **Database** | PostgreSQL 16 | Run history, agent logs, persistent across restarts |
| **Real-time** | WebSocket (native FastAPI) | Per-run pub/sub — frontend sees every agent thought live |
| **Frontend** | Next.js 14 App Router | Client components only where needed (polling, WebSocket) |
| **Deployment** | Docker Compose | Three services, one command |

---

## Project Structure

```
devops-swarm/
├── backend/
│   └── app/
│       ├── agents/
│       │   ├── graph.py        # LangGraph StateGraph definition
│       │   ├── nodes.py        # ReAct loop, 4 agent nodes
│       │   ├── prompts.py      # System prompts per agent
│       │   └── state.py        # Shared TypedDict state
│       ├── tools/
│       │   ├── github_tools.py # GitHub API: read repo, create branch, open PR
│       │   └── e2b_tools.py    # Sandbox: write/run code, git operations
│       ├── db/
│       │   ├── models.py       # Run + AgentLog SQLAlchemy models
│       │   └── database.py     # Async engine + session factory
│       ├── ws_manager.py       # WebSocket connection manager (pub/sub)
│       ├── webhooks.py         # GitHub webhook + /trigger test endpoint
│       └── main.py             # FastAPI app, lifespan, CORS
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx        # Dashboard — stats + activity feed + run table
│       │   └── runs/[id]/      # Run detail — live agent stream
│       └── components/
│           ├── AgentStream.tsx # WebSocket terminal (live + archived)
│           ├── RunHistory.tsx  # Timeline feed + compact table
│           ├── TriggerModal.tsx
│           └── StatusBadge.tsx
├── docker-compose.yml
└── init.sql
```

---

## Quickstart

**Requirements:** Docker Desktop, a Groq API key (free), an E2B API key (free), a GitHub PAT.

```bash
# 1. Clone
git clone https://github.com/Sowaiba-01/Devops-swarm.git
cd Devops-swarm

# 2. Configure
cp .env.example .env
# Edit .env — fill in GROQ_API_KEY, E2B_API_KEY, GITHUB_PAT

# 3. Run
docker compose up --build
```

Open **http://localhost:3000** → click **[ RUN SWARM ]** → enter your GitHub repo + any open issue → watch the agents work in real time.

**Getting free API keys:**
- Groq: [console.groq.com](https://console.groq.com) → API Keys → Create (free, 14,400 req/day)
- E2B: [e2b.dev](https://e2b.dev) → Dashboard → API Keys (free tier available)
- GitHub PAT: Settings → Developer Settings → Tokens (classic) → check `repo` + `workflow`

---

## How the self-correction loop works

The coder node doesn't just write code and hope. After each write, it runs the test suite and reads the output:

```
Iteration 1:
  write_file("auth.py", ...) → run_tests() → "FAILED: assertion error line 42"
  → Read error → fix the code → run_tests() again

Iteration 2:
  write_file("auth.py", fixed version) → run_tests() → "passed 12/12"
  → git_commit_all("fix: auth token refresh") → git_push(branch)
```

If all 3 iterations fail, the PR is still opened — with the failing test output attached — so a human can take over with full context.

---

## Live Agent Stream

Every event in the swarm is streamed to the frontend over WebSocket:

```
08:14:22  [architect]  THOUGHT   I need to first understand the repo structure...
08:14:23  [architect]  TOOL▸     list_directory("")
08:14:24  [architect]  RESULT    📁 src  📄 requirements.txt  📄 README.md
08:14:31  [architect]  THOUGHT   The issue requires adding rate limiting...
08:14:55  [coder]      TOOL▸     setup_workspace()
08:14:58  [coder]      RESULT    Cloned owner/repo to /workspace. Installed Python deps.
08:15:12  [coder]      TOOL▸     write_file("middleware/rate_limit.py", ...)
08:15:44  [coder]      TOOL▸     run_tests()
08:15:51  [coder]      RESULT    passed 14/14 ✓
08:16:03  [reviewer]   TOOL▸     get_git_diff()
08:16:22  [reviewer]   THOUGHT   The changes look clean. No hardcoded secrets...
08:16:30  [pr]         RESULT    PR #8 created: https://github.com/owner/repo/pull/8
```

---

## API

```
POST /trigger          Fire a run without a GitHub webhook (for testing)
GET  /runs             List all runs (last 30 by default)
GET  /runs/{id}        Get a single run with full metadata
GET  /runs/{id}/logs   Get all stored agent logs for a run
WS   /ws/{run_id}      WebSocket stream — real-time agent events
POST /webhook          GitHub webhook endpoint (for production use)
```

---

## Engineering challenges solved

**E2B sandbox timeout** — Sandboxes die between agent node calls if the gap is too long. Fixed with: (1) 30-minute sandbox timeout, (2) module-level sandbox dict keyed by `run_id` so the same instance is reused across nodes, (3) git push happens inside `coder_node` right after commit while the sandbox is warm — not in the PR node minutes later.

**Groq malformed tool calls** — Llama 3.3 occasionally generates `<function=name{...}>` syntax when the model writes a long prose response before calling a tool. Fixed with: (1) all prompts start with "Call tools immediately. Do NOT write any explanation before your first tool call.", (2) `_react_loop()` catches `BadRequestError` and injects a corrective message to retry.

**GitHub `main` vs `master`** — PR creation fails with 422 if the base branch is wrong. Fixed by auto-detecting `default_branch` from the GitHub repo API before creating the PR.

**Async E2B SDK in async FastAPI** — E2B's Python SDK is synchronous. Wrapping every call in `asyncio.to_thread()` prevents blocking the event loop.

---

## What I'd build next

- **GitHub App webhook** — trigger automatically when an issue is labeled `swarm` instead of manually calling `/trigger`
- **Slack / Discord notification** — post the PR link to a channel when done
- **Multi-repo queue** — run parallel swarms across multiple repos with a job queue (Celery or ARQ)
- **Cost tracking** — log Groq token usage per run for budget visibility
- **Eval harness** — benchmark the swarm on a fixed set of synthetic issues to track quality regressions

---

## Built by

**Sowaiba Arshad** — AI/ML Engineer

Designed and implemented the full stack: LangGraph multi-agent topology, ReAct tool-calling loop, E2B sandbox integration, FastAPI async backend, WebSocket real-time streaming, and Next.js neon dashboard.

📧 sowaibaworkspace@gmail.com  
🐙 [github.com/Sowaiba-01](https://github.com/Sowaiba-01)

---

*This project demonstrates: multi-agent orchestration, LLM tool-use, cloud sandbox execution, async Python, real-time WebSocket streaming, and full-stack deployment with Docker.*
