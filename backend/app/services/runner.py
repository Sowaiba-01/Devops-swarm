"""
Run execution.

Replaces FastAPI's `BackgroundTasks` for swarm execution. `BackgroundTasks` is
fine for a quick side effect after a response, but a swarm run lasts minutes and
needs things that mechanism does not offer:

* a concurrency ceiling — each run holds a paid sandbox and burns LLM quota, and
  nothing previously stopped N simultaneous webhooks from starting N sandboxes;
* a handle on in-flight work, so shutdown can drain instead of severing runs
  mid-write and leaving rows stuck at `running`;
* a guaranteed terminal transition, so a run always ends in `success` or
  `failed` even if the graph raises, is cancelled, or times out.

Scope note: this is an in-process executor. Runs do not survive a restart — the
startup reconciler marks orphans as failed. Durable execution would mean a real
queue (Celery, Temporal, SQS); the seam for that is `submit()`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from app.config import settings
from app.core.logging import get_logger, run_id_var
from app.core.metrics import run_duration, runs_completed_total, runs_in_flight, runs_started_total
from app.core.redaction import forget_secret, register_secret
from app.db import repository
from app.tools.sandbox import close_sandbox

logger = get_logger(__name__)

# A run that has not finished in this long is wedged: E2B sandboxes expire after
# SANDBOX_TIMEOUT_SECONDS, so anything past that cannot make progress.
RUN_TIMEOUT_SECONDS = settings.SANDBOX_TIMEOUT_SECONDS + 600


class RunExecutor:
    def __init__(self, max_concurrent: int) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: set[asyncio.Task] = set()
        self._waiting = 0
        self._shutting_down = False

    @property
    def in_flight(self) -> int:
        return len(self._tasks)

    @property
    def queue_depth(self) -> int:
        """Runs accepted but still waiting on the concurrency semaphore."""
        return self._waiting

    def submit(self, run_id: str, state: dict, *, source: str = "api") -> None:
        """Accept a run for execution. Returns as soon as it is scheduled."""
        if self._shutting_down:
            raise RuntimeError("Service is shutting down and is not accepting new runs")

        runs_started_total.labels(source=source).inc()
        task = asyncio.create_task(self._execute(run_id, state), name=f"swarm-run-{run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute(self, run_id: str, state: dict) -> None:
        run_id_var.set(run_id)
        token = state.get("github_token")
        register_secret(token)

        started = time.perf_counter()
        outcome = "failed"

        try:
            self._waiting += 1
            try:
                await self._semaphore.acquire()
            finally:
                # Decrement whether the wait succeeded or was cancelled, so a
                # cancelled queue does not report phantom depth forever.
                self._waiting -= 1

            runs_in_flight.inc()
            try:
                await repository.mark_running(run_id)
                # Imported here so no module-level cycle can form between the
                # executor and the agent nodes.
                from app.agents.graph import get_compiled_graph

                await asyncio.wait_for(
                    get_compiled_graph().ainvoke(
                        state, config={"recursion_limit": settings.GRAPH_RECURSION_LIMIT}
                    ),
                    timeout=RUN_TIMEOUT_SECONDS,
                )
                outcome = await self._finalise(run_id)
            finally:
                runs_in_flight.dec()
                self._semaphore.release()

        except TimeoutError:
            outcome = "failed"
            await self._fail(
                run_id,
                f"Run exceeded the {RUN_TIMEOUT_SECONDS}s limit and was terminated.",
            )
        except asyncio.CancelledError:
            outcome = "cancelled"
            await self._fail(run_id, "Run cancelled: the service is shutting down.")
            raise
        except Exception as exc:
            outcome = "failed"
            from app.agents.nodes import handle_error

            await handle_error(run_id, exc)
        finally:
            forget_secret(token)
            with contextlib.suppress(Exception):
                close_sandbox(run_id)
            runs_completed_total.labels(status=outcome).inc()
            run_duration.labels(status=outcome).observe(time.perf_counter() - started)
            logger.info("Run finished with outcome=%s", outcome, extra={"run_id": run_id})

    @staticmethod
    async def _finalise(run_id: str) -> str:
        """
        Guarantee a terminal status.

        `pr_node` marks the run itself on the happy path. This catches the case
        where the graph completed without reaching it — for example the
        supervisor gave up after repeated empty agent output.
        """
        from app.db.database import session_scope

        async with session_scope() as session:
            run = await repository.get_run(session, run_id)
            if run is not None and run.is_terminal:
                return run.status

        await repository.mark_failed(
            run_id, "Run ended without opening a pull request. See the agent log for details."
        )
        return "failed"

    @staticmethod
    async def _fail(run_id: str, message: str) -> None:
        try:
            from app.agents.nodes import emit

            await emit(run_id, "system", "error", message)
        except Exception:
            logger.exception("Could not record the failure event", extra={"run_id": run_id})
        with contextlib.suppress(Exception):
            await repository.mark_failed(run_id, message)

    async def drain(self, timeout: float = 30.0) -> None:  # noqa: ASYNC109
        """Stop accepting work, give in-flight runs a grace period, then cancel."""
        self._shutting_down = True
        if not self._tasks:
            return

        logger.info("Draining %d in-flight run(s)", len(self._tasks))
        done, pending = await asyncio.wait(set(self._tasks), timeout=timeout)
        for task in pending:
            logger.warning("Cancelling run task %s after the drain timeout", task.get_name())
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


executor = RunExecutor(max_concurrent=settings.MAX_CONCURRENT_RUNS)
