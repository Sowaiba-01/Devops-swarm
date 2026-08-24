"""Run lifecycle and read endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import initial_state
from app.config import settings
from app.core.logging import get_logger, run_id_var
from app.core.ratelimit import rate_limit_reads, rate_limit_triggers
from app.core.security import parse_repo, require_api_key, require_repo_allowed
from app.db import repository
from app.db.database import get_db
from app.schemas import (
    LogEntry,
    LogListResponse,
    PageMeta,
    RunDetail,
    RunListResponse,
    RunSummary,
    StatsResponse,
    TriggerRequest,
    TriggerResponse,
)
from app.services.runner import executor
from app.tools.sandbox import registry as sandbox_registry

logger = get_logger(__name__)
router = APIRouter(tags=["runs"])

RUN_ID = Path(..., min_length=36, max_length=36, description="Run UUID")


@router.post(
    "/trigger",
    response_model=TriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit_triggers)],
    summary="Start a swarm run against a GitHub issue",
)
async def trigger_run(
    body: TriggerRequest,
    caller: str = Depends(require_api_key),
) -> TriggerResponse:
    """
    Start a run using the configured GitHub PAT.

    Guarded by an API key and a repository allowlist: this endpoint spends the
    operator's GitHub credentials against whatever repository it is handed, so
    an open version of it lets any caller push branches and open pull requests
    as the operator.
    """
    if not settings.GITHUB_PAT:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GITHUB_PAT is not configured; the manual trigger is unavailable.",
        )

    owner, repo = parse_repo(body.repo)
    require_repo_allowed(owner, repo)

    if executor.in_flight >= settings.MAX_CONCURRENT_RUNS * 4:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many runs queued. Try again shortly.",
            headers={"Retry-After": "60"},
        )

    run_id = str(uuid.uuid4())
    run_id_var.set(run_id)

    await repository.create_run(
        run_id=run_id,
        owner=owner,
        repo=repo,
        issue_number=body.issue_number,
        issue_title=body.issue_title,
        installation_id=0,
    )

    executor.submit(
        run_id,
        dict(
            initial_state(
                run_id=run_id,
                installation_id=0,
                repo_owner=owner,
                repo_name=repo,
                issue_number=body.issue_number,
                issue_title=body.issue_title,
                issue_body=body.issue_body,
                github_token=settings.GITHUB_PAT,
                max_iterations=settings.MAX_CORRECTION_ITERATIONS,
            )
        ),
        source="manual",
    )

    logger.info("Run accepted for %s/%s#%d by caller=%s", owner, repo, body.issue_number, caller)
    return TriggerResponse(run_id=run_id, stream_url=f"/ws/{run_id}")


@router.get(
    "/runs",
    response_model=RunListResponse,
    dependencies=[Depends(rate_limit_reads)],
    summary="List runs, newest first",
)
async def list_runs(
    limit: int = Query(default=settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0, le=100_000),
    run_status: str | None = Query(default=None, alias="status"),
    repo: str | None = Query(default=None, description="Filter by 'owner/repo'"),
    db: AsyncSession = Depends(get_db),
) -> RunListResponse:
    if run_status and run_status not in repository.VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {', '.join(sorted(repository.VALID_STATUSES))}",
        )

    rows, total = await repository.list_runs(
        db, limit=limit, offset=offset, status=run_status, repo=repo
    )
    return RunListResponse(
        runs=[RunSummary.of(r) for r in rows],
        # `total` is the count of everything matching the filter. The previous
        # implementation returned the page length, so the dashboard's counter
        # stopped at the page size no matter how many runs existed.
        page=PageMeta(total=total, limit=limit, offset=offset, has_more=offset + len(rows) < total),
    )


@router.get(
    "/runs/stats",
    response_model=StatsResponse,
    dependencies=[Depends(rate_limit_reads)],
    summary="Aggregate run counts",
)
async def get_stats(db: AsyncSession = Depends(get_db)) -> StatsResponse:
    """
    Counts computed in the database.

    The dashboard previously derived these from whichever page of runs it had
    loaded, so "success rate" described the last 30 runs and silently changed
    meaning as the page size changed.
    """
    counts = await repository.run_stats(db)
    finished = counts["success"] + counts["failed"]
    return StatsResponse(
        **counts,
        success_rate=round(counts["success"] / finished * 100, 1) if finished else 0.0,
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunDetail,
    dependencies=[Depends(rate_limit_reads)],
    summary="Fetch one run",
)
async def get_run(run_id: str = RUN_ID, db: AsyncSession = Depends(get_db)) -> RunDetail:
    run = await repository.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return RunDetail.of(run)


@router.get(
    "/runs/{run_id}/logs",
    response_model=LogListResponse,
    dependencies=[Depends(rate_limit_reads)],
    summary="Fetch agent logs for a run",
)
async def get_run_logs(
    run_id: str = RUN_ID,
    limit: int = Query(default=500, ge=1, le=2000),
    after_seq: int = Query(
        default=0, ge=0, description="Return only events after this sequence number."
    ),
    db: AsyncSession = Depends(get_db),
) -> LogListResponse:
    """
    Replay a run's events.

    `after_seq` lets a client that already holds part of the stream fetch only
    what it is missing — used to backfill history when a WebSocket attaches to a
    run that is already in progress, and to recover after a reconnect without
    duplicating what is already on screen.
    """
    run = await repository.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    rows = await repository.list_logs(db, run_id, limit=limit, after_seq=after_seq)
    entries = [LogEntry.of(r) for r in rows]
    return LogListResponse(logs=entries, last_seq=entries[-1].seq if entries else after_seq)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunDetail,
    summary="Cancel a run that is still executing",
)
async def cancel_run(
    run_id: str = RUN_ID,
    caller: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> RunDetail:
    run = await repository.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.is_terminal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run is already {run.status} and cannot be cancelled.",
        )

    await repository.mark_cancelled(run_id)
    sandbox_registry.release(run_id)
    logger.info("Run cancelled by caller=%s", caller, extra={"run_id": run_id})

    await db.refresh(run)
    return RunDetail.of(run)
