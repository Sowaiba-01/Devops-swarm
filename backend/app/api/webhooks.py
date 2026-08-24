"""
GitHub App webhook.

Signature verification happens before the body is parsed, and an unset
`GITHUB_WEBHOOK_SECRET` fails closed. Deliveries are also de-duplicated:
GitHub retries on any non-2xx or slow response, and without the guard a single
issue could start several concurrent runs — each with its own sandbox and PR.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.agents.state import initial_state
from app.config import settings
from app.core.logging import get_logger, run_id_var
from app.core.security import verify_github_signature
from app.db import repository
from app.services.runner import executor
from app.tools.github_tools import get_installation_token

logger = get_logger(__name__)
router = APIRouter(tags=["webhooks"])

HANDLED_ACTIONS = frozenset({"opened", "reopened"})
DEDUPE_TTL_SECONDS = 3600
DEDUPE_MAX_ENTRIES = 5000

_seen_deliveries: OrderedDict[str, float] = OrderedDict()


def _already_processed(delivery_id: str) -> bool:
    """Bounded, TTL'd set of delivery ids."""
    now = time.monotonic()
    while _seen_deliveries:
        oldest_id, seen_at = next(iter(_seen_deliveries.items()))
        if now - seen_at <= DEDUPE_TTL_SECONDS and len(_seen_deliveries) <= DEDUPE_MAX_ENTRIES:
            break
        _seen_deliveries.pop(oldest_id, None)

    if delivery_id in _seen_deliveries:
        return True
    _seen_deliveries[delivery_id] = now
    return False


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED, summary="GitHub App webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
) -> dict:
    payload_bytes = await request.body()

    # Verify against the raw bytes: re-serialising JSON would change them.
    if not verify_github_signature(payload_bytes, x_hub_signature_256):
        logger.warning("Rejected webhook delivery %s: bad signature", x_github_delivery)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature"
        )

    if x_github_delivery and _already_processed(x_github_delivery):
        logger.info("Ignoring duplicate delivery %s", x_github_delivery)
        return {"status": "duplicate", "delivery": x_github_delivery}

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Body is not valid JSON"
        ) from exc

    action = payload.get("action", "")
    if x_github_event != "issues" or action not in HANDLED_ACTIONS:
        return {"status": "ignored", "event": x_github_event, "action": action}

    try:
        issue = payload["issue"]
        repo_payload = payload["repository"]
        installation_id = int(payload["installation"]["id"])
        owner = repo_payload["owner"]["login"]
        name = repo_payload["name"]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Webhook payload is missing a required field: {exc}",
        ) from exc

    if not settings.repo_allowed(owner, name):
        logger.warning("Webhook for %s/%s rejected: not in REPO_ALLOWLIST", owner, name)
        return {"status": "ignored", "reason": "repository not allowlisted"}

    # Bots reopening issues, or the swarm's own comments, must not recurse.
    if (issue.get("user") or {}).get("type") == "Bot":
        return {"status": "ignored", "reason": "issue opened by a bot"}

    run_id = str(uuid.uuid4())
    run_id_var.set(run_id)

    try:
        github_token = await get_installation_token(installation_id)
    except Exception as exc:
        logger.error("Installation token exchange failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub authentication failed"
        ) from exc

    await repository.create_run(
        run_id=run_id,
        owner=owner,
        repo=name,
        issue_number=issue["number"],
        issue_title=issue.get("title") or "(untitled issue)",
        installation_id=installation_id,
    )

    executor.submit(
        run_id,
        dict(
            initial_state(
                run_id=run_id,
                installation_id=installation_id,
                repo_owner=owner,
                repo_name=name,
                issue_number=issue["number"],
                issue_title=issue.get("title") or "(untitled issue)",
                issue_body=issue.get("body") or "",
                github_token=github_token,
                max_iterations=settings.MAX_CORRECTION_ITERATIONS,
            )
        ),
        source="webhook",
    )

    logger.info("Webhook started a run for %s/%s#%s", owner, name, issue["number"])
    return {"status": "accepted", "run_id": run_id}
