"""
Request and response models.

Response shapes are declared explicitly rather than assembled as bare dicts, so
the OpenAPI document is accurate and the frontend's generated types cannot drift
from what the API actually returns.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import AgentLog, Run, ensure_utc

# ── Requests ───────────────────────────────────────────────────────────


class TriggerRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    repo: str = Field(
        ...,
        description="Target repository as 'owner/repo-name'.",
        examples=["octocat/hello-world"],
        min_length=3,
        max_length=200,
    )
    issue_number: int = Field(..., ge=1, le=1_000_000)
    issue_title: str = Field(..., min_length=1, max_length=500)
    issue_body: str = Field(default="No description provided.", max_length=50_000)

    @field_validator("issue_title", "issue_body")
    @classmethod
    def _no_control_characters(cls, v: str) -> str:
        # These end up in commit messages, branch names and PR bodies.
        return "".join(ch for ch in v if ch == "\n" or ch == "\t" or ch >= " ")


# ── Responses ──────────────────────────────────────────────────────────


class TriggerResponse(BaseModel):
    run_id: str
    status: Literal["accepted"] = "accepted"
    stream_url: str


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repo: str
    issue_number: int
    issue_title: str | None
    status: str
    phase: str | None
    pr_url: str | None
    branch_name: str | None
    iteration_count: int
    tests_passed: bool | None
    review_verdict: str | None
    created_at: dt.datetime | None
    started_at: dt.datetime | None
    completed_at: dt.datetime | None
    duration_seconds: float | None

    @classmethod
    def of(cls, run: Run) -> RunSummary:
        return cls(
            id=run.id,
            repo=run.repo_full_name,
            issue_number=run.issue_number,
            issue_title=run.issue_title,
            status=run.status,
            phase=run.phase,
            pr_url=run.pr_url,
            branch_name=run.branch_name,
            iteration_count=run.iteration_count,
            tests_passed=run.tests_passed,
            review_verdict=run.review_verdict,
            # Normalised so the client always receives an explicit UTC offset.
            created_at=ensure_utc(run.created_at),
            started_at=ensure_utc(run.started_at),
            completed_at=ensure_utc(run.completed_at),
            duration_seconds=run.duration_seconds,
        )


class RunDetail(RunSummary):
    error_message: str | None = None

    @classmethod
    def of(cls, run: Run) -> RunDetail:  # type: ignore[override]
        base = RunSummary.of(run).model_dump()
        return cls(**base, error_message=run.error_message)


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool


class RunListResponse(BaseModel):
    runs: list[RunSummary]
    page: PageMeta


class LogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    seq: int
    agent: str
    log_type: str
    content: str
    timestamp: dt.datetime | None

    @classmethod
    def of(cls, log: AgentLog) -> LogEntry:
        return cls(
            id=log.id,
            seq=log.seq,
            agent=log.agent,
            log_type=log.log_type,
            content=log.content,
            timestamp=ensure_utc(log.timestamp),
        )


class LogListResponse(BaseModel):
    logs: list[LogEntry]
    # Cursor for incremental polling: request the next page with ?after_seq=
    last_seq: int


class StatsResponse(BaseModel):
    total: int
    queued: int
    running: int
    success: int
    failed: int
    cancelled: int
    success_rate: float = Field(description="Successful runs as a share of finished runs.")


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    database: Literal["up", "down"]
    runs_in_flight: int
    sandboxes_active: int


class ErrorResponse(BaseModel):
    detail: str
    request_id: str | None = None
