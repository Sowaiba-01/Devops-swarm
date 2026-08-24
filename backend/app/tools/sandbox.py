"""
E2B sandbox lifecycle.

Sandboxes are billed per running minute and are created lazily, one per run.
The previous implementation kept them in a bare dict with no eviction: any run
that died outside the happy path left a sandbox running until E2B's own timeout,
and a process restart orphaned every one of them.

This module owns creation, last-touch tracking, explicit release, and a
background reaper for anything that outlives its run.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from dataclasses import dataclass

from app.config import settings
from app.core.logging import get_logger
from app.core.metrics import sandboxes_active, sandboxes_reaped_total

logger = get_logger(__name__)


@dataclass
class SandboxHandle:
    sandbox: object  # e2b_code_interpreter.Sandbox
    run_id: str
    created_at: float
    last_used_at: float
    base_commit: str | None = None


class SandboxRegistry:
    """Thread-safe because tools run in a worker thread via `asyncio.to_thread`."""

    def __init__(self) -> None:
        self._handles: dict[str, SandboxHandle] = {}
        self._lock = threading.RLock()

    def get_or_create(self, run_id: str) -> SandboxHandle:
        with self._lock:
            handle = self._handles.get(run_id)
            if handle is not None:
                handle.last_used_at = time.monotonic()
                return handle

        # Construct outside the lock: sandbox boot takes seconds and must not
        # block every other run's tool calls.
        from e2b_code_interpreter import Sandbox

        logger.info("Creating E2B sandbox", extra={"run_id": run_id})
        sandbox = Sandbox(timeout=settings.SANDBOX_TIMEOUT_SECONDS)
        now = time.monotonic()

        with self._lock:
            existing = self._handles.get(run_id)
            if existing is not None:
                # Lost a race; discard the duplicate rather than leak it.
                with contextlib.suppress(Exception):
                    sandbox.kill()
                existing.last_used_at = now
                return existing
            handle = SandboxHandle(sandbox=sandbox, run_id=run_id, created_at=now, last_used_at=now)
            self._handles[run_id] = handle
            sandboxes_active.set(len(self._handles))
        return handle

    def peek(self, run_id: str) -> SandboxHandle | None:
        with self._lock:
            return self._handles.get(run_id)

    def release(self, run_id: str) -> None:
        with self._lock:
            handle = self._handles.pop(run_id, None)
            sandboxes_active.set(len(self._handles))
        if handle is None:
            return
        try:
            handle.sandbox.kill()  # type: ignore[attr-defined]
            logger.info("Sandbox released", extra={"run_id": run_id})
        except Exception:
            logger.warning("Sandbox kill failed for run_id=%s", run_id, exc_info=True)

    def reap_idle(self, max_idle_seconds: float) -> int:
        now = time.monotonic()
        with self._lock:
            stale = [
                rid for rid, h in self._handles.items() if now - h.last_used_at > max_idle_seconds
            ]
        for run_id in stale:
            logger.warning("Reaping idle sandbox", extra={"run_id": run_id})
            self.release(run_id)
            sandboxes_reaped_total.inc()
        return len(stale)

    def release_all(self) -> None:
        with self._lock:
            run_ids = list(self._handles)
        for run_id in run_ids:
            self.release(run_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._handles)


registry = SandboxRegistry()


async def reaper_loop(interval_seconds: float = 300.0) -> None:
    """Background task started at application startup."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            reaped = await asyncio.to_thread(
                registry.reap_idle, float(settings.SANDBOX_MAX_IDLE_SECONDS)
            )
            if reaped:
                logger.info("Sandbox reaper closed %d idle sandbox(es)", reaped)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Sandbox reaper iteration failed")


def close_sandbox(run_id: str) -> None:
    registry.release(run_id)
