import datetime
import hashlib
import hmac
import logging
import uuid
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from app.agents.graph import swarm_graph
from app.agents.nodes import handle_error
from app.agents.state import SwarmState
from app.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Run
from app.tools.github_tools import get_installation_token

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------

def _verify_github_signature(payload_bytes: bytes, signature_header: str | None) -> bool:
    """Return True if the payload matches the GitHub HMAC-SHA256 signature."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


# ---------------------------------------------------------------------------
# Background swarm runner
# ---------------------------------------------------------------------------

async def _run_swarm(run_id: str, initial_state: SwarmState) -> None:
    """Execute the LangGraph swarm; catch and persist top-level errors."""
    try:
        await swarm_graph.ainvoke(initial_state)
    except Exception as exc:
        await handle_error(run_id, exc)


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@router.post("/webhook", status_code=202)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not _verify_github_signature(payload_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()
    action = payload.get("action", "")

    # Only handle issue-opened / issue-reopened
    if event_type != "issues" or action not in ("opened", "reopened"):
        return {"status": "ignored", "event": event_type, "action": action}

    issue = payload["issue"]
    repo = payload["repository"]
    installation_id: int = payload["installation"]["id"]

    run_id = str(uuid.uuid4())

    # Persist Run record immediately so the dashboard can show it
    async with AsyncSessionLocal() as session:
        session.add(
            Run(
                id=run_id,
                repo_owner=repo["owner"]["login"],
                repo_name=repo["name"],
                issue_number=issue["number"],
                issue_title=issue["title"],
                installation_id=installation_id,
                status="running",
                created_at=datetime.datetime.utcnow(),
            )
        )
        await session.commit()

    logger.info(
        "Starting swarm run_id=%s for %s/%s#%d",
        run_id,
        repo["owner"]["login"],
        repo["name"],
        issue["number"],
    )

    # Fetch short-lived installation access token
    try:
        github_token = await get_installation_token(installation_id)
    except Exception as exc:
        logger.error("Failed to get installation token: %s", exc)
        raise HTTPException(status_code=500, detail="GitHub auth failed") from exc

    # Build initial swarm state
    initial_state: SwarmState = {
        "run_id": run_id,
        "installation_id": installation_id,
        "repo_owner": repo["owner"]["login"],
        "repo_name": repo["name"],
        "issue_number": issue["number"],
        "issue_title": issue["title"],
        "issue_body": issue.get("body") or "(no description provided)",
        "github_token": github_token,
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

    background_tasks.add_task(_run_swarm, run_id, initial_state)

    return {"status": "accepted", "run_id": run_id}
