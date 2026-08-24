"""
Data access for runs and agent logs.

All persistence lives here so the agent layer never builds SQL and the API layer
never touches ORM internals. Keeping it in one place also makes the sequence
numbering of log events — which the dashboard relies on for ordering — a single
enforceable invariant.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact
from app.db.database import session_scope
from app.db.models import AgentLog, LogType, Run, RunStatus, new_id, utcnow

# Persisted log bodies are capped so one runaway tool result cannot bloat a row.
MAX_LOG_CONTENT_CHARS = 16_000

# Per-run monotonic counters for log ordering.
_seq_counters: dict[str, int] = defaultdict(int)
_seq_lock = asyncio.Lock()


async def _next_seq(run_id: str) -> int:
    async with _seq_lock:
        _seq_counters[run_id] += 1
        return _seq_counters[run_id]


def forget_run_sequence(run_id: str) -> None:
    """Release the counter once a run reaches a terminal state."""
    _seq_counters.pop(run_id, None)


# ── Runs ───────────────────────────────────────────────────────────────


async def create_run(
    *,
    run_id: str,
    owner: str,
    repo: str,
    issue_number: int,
    issue_title: str,
    installation_id: int = 0,
) -> Run:
    async with session_scope() as session:
        run = Run(
            id=run_id,
            repo_owner=owner,
            repo_name=repo,
            issue_number=issue_number,
            issue_title=issue_title[:500],
            installation_id=installation_id,
            status=RunStatus.QUEUED.value,
            phase="architect",
            created_at=utcnow(),
        )
        session.add(run)
        await session.flush()
        await session.refresh(run)
        return run


async def mark_running(run_id: str) -> None:
    await _update_run(run_id, status=RunStatus.RUNNING.value, started_at=utcnow())


async def set_phase(run_id: str, phase: str) -> None:
    await _update_run(run_id, phase=phase)


async def mark_succeeded(
    run_id: str,
    *,
    pr_url: str | None,
    branch_name: str | None,
    iteration_count: int,
    tests_passed: bool | None,
    review_verdict: str | None,
) -> None:
    await _update_run(
        run_id,
        status=RunStatus.SUCCESS.value,
        phase="done",
        pr_url=pr_url,
        branch_name=branch_name,
        iteration_count=iteration_count,
        tests_passed=tests_passed,
        review_verdict=review_verdict,
        completed_at=utcnow(),
    )
    forget_run_sequence(run_id)


async def mark_cancelled(run_id: str, reason: str = "Cancelled by operator request.") -> None:
    await _update_run(
        run_id,
        status=RunStatus.CANCELLED.value,
        phase="done",
        error_message=reason[:2000],
        completed_at=utcnow(),
    )
    forget_run_sequence(run_id)


async def mark_failed(run_id: str, error_message: str, **extra: Any) -> None:
    await _update_run(
        run_id,
        status=RunStatus.FAILED.value,
        phase="done",
        error_message=redact(error_message)[:2000],
        completed_at=utcnow(),
        **extra,
    )
    forget_run_sequence(run_id)


async def _update_run(run_id: str, **values: Any) -> None:
    async with session_scope() as session:
        await session.execute(update(Run).where(Run.id == run_id).values(**values))


async def get_run(session: AsyncSession, run_id: str) -> Run | None:
    result = await session.execute(select(Run).where(Run.id == run_id))
    return result.scalar_one_or_none()


async def list_runs(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    repo: str | None = None,
) -> tuple[Sequence[Run], int]:
    """
    Return one page of runs plus the *total* matching count.

    The previous endpoint reported `len(page)` as the total, so the dashboard's
    counter stopped climbing at the page size.
    """
    filters = []
    if status:
        filters.append(Run.status == status)
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        filters.extend([Run.repo_owner == owner, Run.repo_name == name])

    count_stmt = select(func.count()).select_from(Run)
    page_stmt = select(Run).order_by(Run.created_at.desc(), Run.id.desc())
    for f in filters:
        count_stmt = count_stmt.where(f)
        page_stmt = page_stmt.where(f)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(page_stmt.limit(limit).offset(offset))).scalars().all()
    return rows, int(total)


async def run_stats(session: AsyncSession) -> dict[str, int]:
    """Aggregate counts by status, computed in the database rather than in JS."""
    result = await session.execute(select(Run.status, func.count()).group_by(Run.status))
    counts = {status: int(count) for status, count in result.all()}
    total = sum(counts.values())
    return {
        "total": total,
        "queued": counts.get(RunStatus.QUEUED.value, 0),
        "running": counts.get(RunStatus.RUNNING.value, 0),
        "success": counts.get(RunStatus.SUCCESS.value, 0),
        "failed": counts.get(RunStatus.FAILED.value, 0),
        "cancelled": counts.get(RunStatus.CANCELLED.value, 0),
    }


async def reconcile_orphaned_runs() -> int:
    """
    Fail runs left mid-flight by a crash or redeploy.

    Runs execute in-process, so anything still marked running at boot has no
    executor behind it and would otherwise sit "in progress" forever.
    """
    async with session_scope() as session:
        result = await session.execute(
            update(Run)
            .where(Run.status.in_([RunStatus.RUNNING.value, RunStatus.QUEUED.value]))
            .values(
                status=RunStatus.FAILED.value,
                phase="done",
                error_message="Interrupted: the service restarted while this run was executing.",
                completed_at=utcnow(),
            )
        )
        return int(result.rowcount or 0)


# ── Logs ───────────────────────────────────────────────────────────────


async def append_log(
    *,
    run_id: str,
    agent: str,
    log_type: str,
    content: str,
    extra: dict | None = None,
) -> dict:
    """
    Persist one agent event and return the payload to broadcast.

    Content is redacted here, at the one point where agent output crosses into
    storage and the network.
    """
    seq = await _next_seq(run_id)
    safe_content = redact(content)[:MAX_LOG_CONTENT_CHARS]
    safe_extra = extra or {}
    timestamp = utcnow()

    async with session_scope() as session:
        session.add(
            AgentLog(
                id=new_id(),
                run_id=run_id,
                seq=seq,
                agent=agent,
                log_type=log_type,
                content=safe_content,
                extra=json.dumps(safe_extra) if safe_extra else None,
                timestamp=timestamp,
            )
        )

    return {
        "seq": seq,
        "run_id": run_id,
        "agent": agent,
        "type": log_type,
        "content": safe_content,
        "timestamp": timestamp.isoformat(),
        **safe_extra,
    }


async def list_logs(
    session: AsyncSession,
    run_id: str,
    *,
    limit: int,
    after_seq: int = 0,
) -> Sequence[AgentLog]:
    stmt = (
        select(AgentLog)
        .where(AgentLog.run_id == run_id, AgentLog.seq > after_seq)
        .order_by(AgentLog.seq)
        .limit(limit)
    )
    return (await session.execute(stmt)).scalars().all()


VALID_LOG_TYPES = frozenset(t.value for t in LogType)
VALID_STATUSES = frozenset(s.value for s in RunStatus)
