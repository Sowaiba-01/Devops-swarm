"""
Database schema.

Timestamps are timezone-aware. The previous schema stored naive `utcnow()`
values, which serialise without an offset and are then parsed by the browser as
*local* time — every duration and "x minutes ago" in the dashboard was wrong by
the client's UTC offset.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    """Timezone-aware now. `datetime.utcnow()` is deprecated in 3.12+."""
    return dt.datetime.now(dt.UTC)


def new_id() -> str:
    return str(uuid.uuid4())


def ensure_utc(value: dt.datetime | None) -> dt.datetime | None:
    """
    Normalise a stored timestamp to an aware UTC value.

    `DateTime(timezone=True)` round-trips an offset on Postgres but not on
    SQLite, which the test suite uses — so a value read back may be naive
    depending on the backend. Arithmetic that mixes the two raises, and a naive
    value serialised to the frontend is parsed by the browser as local time.
    Normalising on read makes both backends behave identically.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class RunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def terminal(cls) -> frozenset[RunStatus]:
        return frozenset({cls.SUCCESS, cls.FAILED, cls.CANCELLED})


class LogType(str, enum.Enum):
    THOUGHT = "thought"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATUS = "status"
    ERROR = "error"


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        # The dashboard's hot query is "newest first, optionally filtered by
        # status". Without these it is a full scan plus sort on every poll.
        Index("ix_runs_created_at_desc", "created_at"),
        Index("ix_runs_status_created_at", "status", "created_at"),
        Index("ix_runs_repo", "repo_owner", "repo_name"),
        CheckConstraint("iteration_count >= 0", name="ck_runs_iteration_count_non_negative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)

    repo_owner: Mapped[str] = mapped_column(String(100), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(100), nullable=False)
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_title: Mapped[str | None] = mapped_column(String(500))
    installation_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), default=RunStatus.QUEUED.value, nullable=False, index=True
    )
    # Which agent is currently executing — drives the dashboard pipeline view.
    phase: Mapped[str | None] = mapped_column(String(20))

    pr_url: Mapped[str | None] = mapped_column(String(500))
    branch_name: Mapped[str | None] = mapped_column(String(255))
    iteration_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tests_passed: Mapped[bool | None] = mapped_column()
    review_verdict: Mapped[str | None] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    logs: Mapped[list[AgentLog]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def repo_full_name(self) -> str:
        return f"{self.repo_owner}/{self.repo_name}"

    @property
    def is_terminal(self) -> bool:
        return self.status in {s.value for s in RunStatus.terminal()}

    @property
    def duration_seconds(self) -> float | None:
        start = ensure_utc(self.created_at)
        if start is None:
            return None
        end = ensure_utc(self.completed_at) or utcnow()
        return (end - start).total_seconds()


class AgentLog(Base):
    __tablename__ = "agent_logs"
    __table_args__ = (
        # Log replay is always "everything for this run, in order".
        Index("ix_agent_logs_run_id_seq", "run_id", "seq"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Monotonic per run. `timestamp` alone is not a stable sort key: several
    # events can land inside the same clock tick and then replay out of order.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    agent: Mapped[str] = mapped_column(String(30), nullable=False)
    log_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extra: Mapped[str | None] = mapped_column(Text)

    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="logs")
