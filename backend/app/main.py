

import datetime
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import swarm_graph
from app.agents.nodes import handle_error
from app.agents.state import SwarmState
from app.config import settings
from app.db.database import get_db, init_db
from app.db.models import AgentLog, Run
from app.webhooks import router as webhook_router
from app.ws_manager import manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — runs once on startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    WHY THIS EXISTS:
    FastAPI needs to know when to create DB tables (startup) and clean up (shutdown).
    asynccontextmanager turns a generator into a context manager.
    Everything before 'yield' = startup. Everything after = shutdown.
    """
    logger.info("Initializing database tables...")
    await init_db()
    logger.info("Database ready.")
    yield
    logger.info("Shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DevOps Swarm API",
    description="Autonomous DevOps & Code-Review Agentic Swarm",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: allows the Next.js frontend (port 3000) to call this API (port 8000)
# Without this, browsers block cross-origin requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)


# ---------------------------------------------------------------------------
# /trigger  — Manual test trigger (bypasses GitHub App, uses PAT)
# ---------------------------------------------------------------------------

class TriggerRequest(BaseModel):
    """
    WHY PYDANTIC:
    FastAPI automatically validates this JSON body. If 'repo' is missing,
    it returns a 422 error before our code even runs. Free input validation.
    """
    repo: str           # "owner/repo-name"
    issue_number: int   # any number, e.g. 1
    issue_title: str
    issue_body: str = "No description provided."


async def _run_swarm_bg(run_id: str, state: SwarmState) -> None:
    """Wrapper so background task errors are caught and persisted."""
    try:
        await swarm_graph.ainvoke(state)
    except Exception as exc:
        await handle_error(run_id, exc)


@app.post("/trigger", status_code=202)
async def trigger_run(
    body: TriggerRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    WHAT THIS DOES:
    Lets you fire the full swarm without a GitHub App or webhook.
    Uses your GitHub Personal Access Token from .env directly.

    HOW TO CALL IT from the dashboard's Trigger button, or curl:
      curl -X POST http://localhost:8000/trigger \\
        -H "Content-Type: application/json" \\
        -d '{"repo":"you/your-repo","issue_number":1,"issue_title":"Fix the bug","issue_body":"Details here"}'
    """
    if not settings.GITHUB_PAT:
        raise HTTPException(
            status_code=400,
            detail="GITHUB_PAT not set in .env. Add it to use the /trigger endpoint."
        )

    parts = body.repo.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="repo must be 'owner/repo-name'")

    owner, repo_name = parts
    run_id = str(uuid.uuid4())

    # Persist the run immediately so the dashboard shows it right away
    async with db as session:
        session.add(Run(
            id=run_id,
            repo_owner=owner,
            repo_name=repo_name,
            issue_number=body.issue_number,
            issue_title=body.issue_title,
            installation_id=0,   # 0 = PAT mode, not GitHub App
            status="running",
            created_at=datetime.datetime.utcnow(),
        ))
        await session.commit()

    initial_state: SwarmState = {
        "run_id": run_id,
        "installation_id": 0,
        "repo_owner": owner,
        "repo_name": repo_name,
        "issue_number": body.issue_number,
        "issue_title": body.issue_title,
        "issue_body": body.issue_body,
        "github_token": settings.GITHUB_PAT,   # PAT used directly
        "phase": "architect",
        "plan": None,
        "branch_name": None,
        "test_output": None,
        "test_passed": None,
        "review_notes": None,
        "pr_url": None,
        "repo_context": None,
        "iteration": 0,
        "max_iterations": settings.MAX_CORRECTION_ITERATIONS,
        "status": "running",
        "error_message": None,
    }

    # WHY background_tasks:
    # The webhook must return 202 immediately (GitHub has a 10s timeout).
    # The swarm takes minutes. background_tasks runs AFTER the response is sent.
    background_tasks.add_task(_run_swarm_bg, run_id, initial_state)

    logger.info("Triggered swarm run_id=%s for %s#%d", run_id, body.repo, body.issue_number)
    return {"status": "accepted", "run_id": run_id}


# ---------------------------------------------------------------------------
# GET /runs  — List runs with optional status filter
# ---------------------------------------------------------------------------

@app.get("/runs")
async def list_runs(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,   # ?status=running  or  ?status=success
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    WHY select().order_by(desc(...)):
    We want newest runs first. SQLAlchemy's desc() = SQL 'ORDER BY created_at DESC'.
    Paging via limit/offset = SQL 'LIMIT 20 OFFSET 0'.
    """
    query = select(Run).order_by(desc(Run.created_at)).limit(limit).offset(offset)
    if status:
        query = query.where(Run.status == status)

    result = await db.execute(query)
    runs = result.scalars().all()

    return {
        "runs": [
            {
                "id": r.id,
                "repo": f"{r.repo_owner}/{r.repo_name}",
                "issue_number": r.issue_number,
                "issue_title": r.issue_title,
                "status": r.status,
                "pr_url": r.pr_url,
                "branch_name": r.branch_name,
                "iteration_count": r.iteration_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in runs
        ],
        "total": len(runs),
    }


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": run.id,
        "repo": f"{run.repo_owner}/{run.repo_name}",
        "issue_number": run.issue_number,
        "issue_title": run.issue_title,
        "status": run.status,
        "pr_url": run.pr_url,
        "branch_name": run.branch_name,
        "iteration_count": run.iteration_count,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/logs
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}/logs")
async def get_run_logs(
    run_id: str,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(AgentLog)
        .where(AgentLog.run_id == run_id)
        .order_by(AgentLog.timestamp)
        .limit(limit)
    )
    logs = result.scalars().all()
    return {
        "logs": [
            {
                "id": log.id,
                "agent": log.agent,
                "log_type": log.log_type,
                "content": log.content,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
            for log in logs
        ]
    }


# ---------------------------------------------------------------------------
# WS /ws/{run_id}  — Real-time agent thought stream
# ---------------------------------------------------------------------------

@app.websocket("/ws/{run_id}")
async def websocket_endpoint(run_id: str, websocket: WebSocket) -> None:
    """
    WHY WEBSOCKET (not HTTP polling):
    HTTP polling = client asks "anything new?" every N seconds. Wasteful.
    WebSocket = server pushes the moment something happens. Zero latency.

    Our ConnectionManager keeps a dict of run_id -> [WebSocket, WebSocket, ...].
    When an agent emits a thought, manager.broadcast() sends it to ALL
    open tabs watching that run simultaneously.
    """
    await manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()   # keeps connection alive
    except WebSocketDisconnect:
        manager.disconnect(run_id, websocket)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}
