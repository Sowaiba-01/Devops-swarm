# DevOps Swarm AI

Autonomous multi-agent system that resolves GitHub issues end-to-end — reads the issue, searches the web for docs, writes and tests code in an isolated cloud sandbox, self-corrects up to 3×, and opens a draft PR. Zero human input required.
---

## What it does

You open a GitHub issue. The swarm:

1. Fetches the **full repository file tree + key config files** in one shot before planning starts
2. Checks **issue comments** for additional context
3. Searches the **live web** for documentation and library APIs it needs
4. Writes code in an **isolated E2B cloud sandbox** — never touches your machine
5. Runs the test suite. On failure, reads the exact error, **auto-installs missing packages**, fixes the code, and retries up to 3×
6. Posts the **implementation plan as a GitHub comment** so you see what's coming before a line is written
7. Runs a **security scan** — detects hardcoded secrets, SQL injection risks, path traversal
8. Opens a **draft PR** with test output and full review notes
9. Posts a **completion comment** on the original issue with the PR link

The repo owner gets two GitHub notifications: one when the plan is posted, one when the PR is ready.

---

## Architecture

```
GitHub Issue Opened
       │
       ▼
 GitHub Webhook ──► POST /webhook  (HMAC-SHA256 validated)
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    LangGraph StateGraph                           │
│                                                                  │
│  START ──► SUPERVISOR ──────────────────────────────────────┐   │
│                │                                            │   │
│        ┌───────┴────────┐                                   │   │
│        ▼                │                                   │   │
│   [ARCHITECT]           │  • Pre-fetches full file tree     │   │
│   ReAct loop            │  • Reads key config files         │   │
│   + GitHub tools        │  • Checks issue comments          │   │
│        │                │  • Posts plan as GitHub comment   │   │
│        └──────► SUPERVISOR                                  │   │
│                │                                            │   │
│        ┌───────┴────────┐                                   │   │
│        ▼                │                                   │   │
│    [CODER]              │  • Clones repo into E2B sandbox   │   │
│   ReAct loop            │  • Greps codebase for patterns    │   │
│   + E2B tools           │  • Searches web for docs          │   │
│   + Web tools           │  • Fetches live documentation     │   │
│   (up to 3×)            │  • Auto-installs missing packages │   │
│        │                │  • Runs linter before commit      │   │
│        └──────► SUPERVISOR                                  │   │
│                │                                            │   │
│        ┌───────┴────────┐                                   │   │
│        ▼                │                                   │   │
│   [REVIEWER]            │  • Reads full git diff            │   │
│   ReAct loop            │  • Runs bandit security scan      │   │
│   + E2B tools           │  • Scans for hardcoded secrets    │   │
│        │                │  • APPROVED or NEEDS_REVISION     │   │
│        └──────► SUPERVISOR                                  │   │
│                │                                            │   │
│        ┌───────┴────────┐                                   │   │
│        ▼                │                                   │   │
│   [PR CREATOR]          │  • Opens draft PR on GitHub       │   │
│        │                │  • Posts completion comment       │   │
│       END ◄─────────────┘  • Closes E2B sandbox             │   │
└──────────────────────────────────────────────────────────────────┘
       │
       ▼
WebSocket stream ──► Next.js dashboard (live agent thought feed)
PostgreSQL       ──► Run history, agent logs, PR links
```

**Key design decisions:**

**Deterministic supervisor** — routing is pure Python `if/else` on `state["phase"]`, never an LLM call. The control flow is predictable and debuggable. No prompt-based routing that can hallucinate a wrong next step.

**ReAct per agent** — each agent runs Reason → Act → Observe loops with real tool calls until it reaches a conclusion, not a single-shot prompt. The coder can call `search_web()`, read the result, call `fetch_url()` on a docs page, read that, then write the code — all in one pass.

**Context injection before reasoning** — the architect receives the full repo file tree automatically before its ReAct loop starts. It doesn't waste tool calls on blind exploration; it already knows what exists and reads only the relevant files.

**Push before sandbox timeout** — git push happens inside `coder_node` immediately after commit, while the sandbox is warm. The PR node does a safety-net retry. Eliminates the "not a git repo" class of failures from sandbox expiry.

**Auto-recovery** — if tests fail with `ModuleNotFoundError`, the system installs the package and retries without counting it as an iteration.

---

## Tool Arsenal

### E2B Sandbox Tools (15 tools)

| Tool | What it does |
|---|---|
| `setup_workspace()` | Clones repo, installs deps (pip/npm/go/cargo auto-detected) |
| `write_file(path, content)` | Write any file relative to `/workspace` |
| `read_file(path)` | Read any file in the sandbox |
| `list_files(path)` | Directory listing |
| `find_in_files(pattern, extensions)` | **grep across entire codebase** — finds existing patterns before writing |
| `search_web(query)` | **Live DuckDuckGo search** — looks up docs, errors, best practices |
| `fetch_url(url)` | **Fetches any webpage** — reads official docs, Stack Overflow, READMEs |
| `install_package(name)` | pip/npm install inside sandbox |
| `run_command(cmd)` | Arbitrary shell command from `/workspace` |
| `run_linter()` | flake8 / eslint / go vet — catches errors before commit |
| `run_tests()` | pytest / npm test / go test / cargo test — auto-detected |
| `run_security_scan()` | bandit + hardcoded secret pattern scan |
| `get_git_diff()` | Full diff of all changes |
| `git_commit_all(message)` | Stage + commit everything |
| `git_push(branch)` | Push to GitHub with auth |

### GitHub API Tools (10 tools)

| Tool | What it does |
|---|---|
| `get_full_repo_context()` | **Full file tree + key config files in one call** |
| `get_issue_comments(number)` | Fetch all issue comments for extra context |
| `get_file_contents(path)` | Read any file from GitHub |
| `list_directory(path)` | Browse repo structure |
| `search_code(query)` | GitHub code search |
| `get_repo_structure(depth)` | Tree view |
| `create_branch(name)` | Branch off default branch |
| `create_pull_request(...)` | Opens draft PR, auto-detects default branch |
| `add_issue_comment(number, body)` | Post comments on issues |
| `create_or_update_file(...)` | Direct file commits via API |

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Agent orchestration | LangGraph StateGraph | Explicit state machine — not a black-box chain. Deterministic routing. |
| LLM | Groq + Llama 3.3 70B | ~500 tok/s inference — fast enough for real-time streaming. Free tier. |
| Code execution | E2B cloud sandboxes | Isolated Linux VM per run. 30-min timeout. No host contamination. |
| Web search | DuckDuckGo API | No API key needed. Runs inside the sandbox via urllib. |
| Backend | FastAPI + async SQLAlchemy | Fully async — WebSocket + HTTP from one process. |
| Database | PostgreSQL 16 | Run history + agent logs. Persistent across restarts. |
| Real-time | WebSocket pub/sub | Per-run ConnectionManager. Frontend sees every agent thought live. |
| Auth | GitHub App + HMAC-SHA256 | Production-grade webhook validation. JWT → installation token exchange. |
| Frontend | Next.js 14 App Router | Client components only where needed. Auto-polls 3s when runs are live. |
| Deployment | Docker Compose | Three services, one command. |

---

## Project Structure

```
devops-swarm/
├── backend/
│   └── app/
│       ├── agents/
│       │   ├── graph.py        # LangGraph StateGraph — 5 nodes, conditional edges
│       │   ├── nodes.py        # ReAct loops, context injection, auto-recovery
│       │   ├── prompts.py      # System prompts per agent
│       │   └── state.py        # Shared TypedDict — 18 fields
│       ├── tools/
│       │   ├── e2b_tools.py    # 15 sandbox tools incl. search_web, fetch_url
│       │   └── github_tools.py # 10 GitHub API tools incl. get_full_repo_context
│       ├── db/
│       │   ├── models.py       # Run + AgentLog SQLAlchemy models
│       │   └── database.py     # Async engine, session factory
│       ├── ws_manager.py       # WebSocket ConnectionManager (pub/sub per run)
│       ├── webhooks.py         # GitHub webhook — HMAC validation, dispatch
│       └── main.py             # FastAPI app, /trigger, /runs, /ws endpoints
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx        # Dashboard — stats row + timeline feed + run table
│       │   └── runs/[id]/      # Run detail — live WebSocket agent stream
│       └── components/
│           ├── AgentStream.tsx # Terminal-style live log viewer
│           ├── RunHistory.tsx  # Timeline cards + compact table
│           ├── TriggerModal.tsx
│           └── StatusBadge.tsx
├── docker-compose.yml
└── init.sql
```

---

## Quickstart

**Requirements:** Docker Desktop, Groq API key (free), E2B API key (free), GitHub PAT.

```bash
git clone https://github.com/Sowaiba-01/Devops-swarm.git
cd Devops-swarm
cp .env.example .env
# Fill in GROQ_API_KEY, E2B_API_KEY, GITHUB_PAT
docker compose up --build
```

Open **http://localhost:3000** → click **[ RUN SWARM ]** → fill in your repo + issue → watch every agent thought stream live.

**Free API keys:**
- Groq: [console.groq.com](https://console.groq.com) → API Keys → Create (free, fast)
- E2B: [e2b.dev](https://e2b.dev) → Dashboard → API Keys
- GitHub PAT: Settings → Developer Settings → Tokens (classic) → check `repo` + `workflow`

---

## API Reference

```
POST /trigger              Fire a run manually (uses GITHUB_PAT, no webhook needed)
POST /webhook              GitHub App webhook (HMAC-SHA256 validated)
GET  /runs                 List all runs (paginated, ?status= filter)
GET  /runs/{id}            Run detail with full metadata
GET  /runs/{id}/logs       All stored agent logs for a run
WS   /ws/{run_id}          Real-time WebSocket agent event stream
GET  /health               Health check
```

---

## Live Agent Stream

Every event streams to the dashboard in real time over WebSocket:

```
08:14:21  [architect]  THOUGHT   Fetching full repository context...
08:14:24  [architect]  TOOL▸     get_full_repo_context()
08:14:26  [architect]  RESULT    REPOSITORY: owner/repo | TOTAL FILES: 47 | FILE TREE: ...
08:14:27  [architect]  TOOL▸     get_file_contents("src/middleware/auth.py")
08:14:29  [architect]  THOUGHT   The issue requires adding rate limiting. I'll modify...
08:14:55  [architect]  STATUS    Implementation plan posted as GitHub comment.
08:15:01  [coder]      TOOL▸     setup_workspace()
08:15:04  [coder]      RESULT    Cloned owner/repo. Installed Python deps.
08:15:05  [coder]      TOOL▸     find_in_files("def authenticate", "py")
08:15:06  [coder]      RESULT    src/auth.py:14: def authenticate(token: str) -> User:
08:15:08  [coder]      TOOL▸     search_web("fastapi rate limiting middleware 2024")
08:15:10  [coder]      RESULT    SUMMARY: slowapi is the recommended rate limiting...
08:15:11  [coder]      TOOL▸     fetch_url("https://slowapi.readthedocs.io/en/latest/")
08:15:14  [coder]      RESULT    SlowAPI — A rate limiting extension for FastAPI...
08:15:44  [coder]      TOOL▸     write_file("src/middleware/rate_limit.py", ...)
08:15:46  [coder]      TOOL▸     run_linter()
08:15:48  [coder]      RESULT    exit_code: 0  (no issues)
08:15:49  [coder]      TOOL▸     git_commit_all("feat: add rate limiting middleware")
08:15:52  [coder]      TOOL▸     run_tests()
08:15:59  [coder]      RESULT    passed 14/14
08:16:03  [reviewer]   TOOL▸     get_git_diff()
08:16:18  [reviewer]   TOOL▸     run_security_scan()
08:16:24  [reviewer]   THOUGHT   No hardcoded secrets. No SQL injection risk...
08:16:31  [reviewer]   STATUS    Verdict: APPROVED
08:16:35  [system]     STATUS    PR #9 created: https://github.com/owner/repo/pull/9
08:16:36  [system]     STATUS    Success comment posted on GitHub issue.
```

---

## Engineering Challenges Solved

**E2B sandbox timeout** — Sandboxes timeout between agent steps if the gap is too long. Fixed with: 30-minute timeout, module-level sandbox dict keyed by `run_id` so the same instance is reused, and git push happening inside `coder_node` immediately after commit while the sandbox is warm.

**Groq malformed tool calls** — Llama 3.3 generates `<function=name{...}>` syntax when it writes prose before calling a tool. Fixed by: all prompts open with "Call tools immediately, no prose first", and `_react_loop()` catches `BadRequestError` and injects a corrective retry message.

**main vs master branch** — PR creation fails with 422 if the base branch is wrong. Fixed by auto-detecting `default_branch` from the GitHub repo API before creating the PR.

**No web access** — the biggest limitation of earlier AI agents. Fixed by `search_web()` (DuckDuckGo, no API key) and `fetch_url()` (urllib inside the sandbox) — the coder can now read any documentation page during execution.

**Missing package failures** — tests fail with `ModuleNotFoundError` when the plan requires a package not in requirements.txt. Fixed by auto-detecting the error pattern and calling `install_package()` automatically before retrying.

**Blind codebase exploration** — agents wasted ReAct iterations doing `list_directory("")` → `list_directory("src")` → `list_directory("src/utils")`. Fixed by `get_full_repo_context()` which returns the complete file tree + key config files in one API call, injected before the ReAct loop starts.

---

## GitHub App Setup (Production)

To trigger automatically when issues are opened (no manual button):

1. Deploy to Railway/Render — get a public URL
2. Register at **github.com/settings/apps** → set webhook URL to `https://your-url/webhook`
3. Permissions: Issues (read), Contents (read+write), Pull Requests (read+write)
4. Subscribe to: `Issues` events
5. Generate private key → add to `.env` as `GITHUB_PRIVATE_KEY`
6. Install on any repo → open an issue → swarm runs automatically

This is the same architecture used by Dependabot, GitHub Copilot, and Devin.

---

