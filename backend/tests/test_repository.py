"""Persistence behaviour: sequencing, terminal transitions, orphan reconciliation."""

from __future__ import annotations

import asyncio

from app.db import repository
from app.db.database import AsyncSessionLocal
from app.db.models import RunStatus


class TestLogSequencing:
    async def test_sequence_numbers_are_monotonic(self, make_run):
        run = await make_run()
        seqs = [
            (
                await repository.append_log(
                    run_id=run.id, agent="coder", log_type="thought", content=str(i)
                )
            )["seq"]
            for i in range(10)
        ]
        assert seqs == list(range(1, 11))

    async def test_concurrent_writes_do_not_collide(self, make_run):
        # Timestamps alone are not a stable sort key: several events land inside
        # the same clock tick and then replay out of order.
        run = await make_run()
        results = await asyncio.gather(
            *(
                repository.append_log(
                    run_id=run.id, agent="coder", log_type="thought", content=str(i)
                )
                for i in range(25)
            )
        )
        seqs = sorted(r["seq"] for r in results)
        assert seqs == list(range(1, 26))

    async def test_sequences_are_independent_per_run(self, make_run):
        a = await make_run(id="aaaaaaaa-0000-0000-0000-000000000000")
        b = await make_run(id="bbbbbbbb-0000-0000-0000-000000000000")
        first = await repository.append_log(run_id=a.id, agent="x", log_type="status", content="1")
        second = await repository.append_log(run_id=b.id, agent="x", log_type="status", content="1")
        assert first["seq"] == second["seq"] == 1

    async def test_oversized_content_is_capped(self, make_run):
        run = await make_run()
        entry = await repository.append_log(
            run_id=run.id, agent="coder", log_type="tool_result", content="x" * 100_000
        )
        assert len(entry["content"]) <= repository.MAX_LOG_CONTENT_CHARS


class TestTerminalTransitions:
    async def test_success_records_the_outcome_fields(self, make_run):
        run = await make_run()
        await repository.mark_succeeded(
            run.id,
            pr_url="https://github.com/o/r/pull/7",
            branch_name="swarm/issue-1",
            iteration_count=2,
            tests_passed=True,
            review_verdict="APPROVED",
        )
        async with AsyncSessionLocal() as session:
            stored = await repository.get_run(session, run.id)
        assert stored.status == RunStatus.SUCCESS.value
        assert stored.tests_passed is True
        assert stored.completed_at is not None

    async def test_a_completed_run_can_record_failing_tests(self, make_run):
        # The pipeline finishing and the tests passing are separate facts; the
        # old code wrote "success" regardless of the test outcome.
        run = await make_run()
        await repository.mark_succeeded(
            run.id,
            pr_url="https://github.com/o/r/pull/7",
            branch_name="b",
            iteration_count=3,
            tests_passed=False,
            review_verdict="NEEDS_REVISION",
        )
        async with AsyncSessionLocal() as session:
            stored = await repository.get_run(session, run.id)
        assert stored.status == RunStatus.SUCCESS.value
        assert stored.tests_passed is False
        assert stored.review_verdict == "NEEDS_REVISION"

    async def test_failure_messages_are_redacted(self, make_run):
        from app.core.redaction import register_secret

        run = await make_run()
        register_secret("ghs_supersecrettokenvalue123456")
        await repository.mark_failed(run.id, "push failed for ghs_supersecrettokenvalue123456")
        async with AsyncSessionLocal() as session:
            stored = await repository.get_run(session, run.id)
        assert "ghs_supersecrettokenvalue123456" not in stored.error_message

    async def test_cancel_is_distinct_from_failure(self, make_run):
        run = await make_run()
        await repository.mark_cancelled(run.id)
        async with AsyncSessionLocal() as session:
            stored = await repository.get_run(session, run.id)
        assert stored.status == RunStatus.CANCELLED.value
        assert stored.is_terminal


class TestOrphanReconciliation:
    async def test_runs_left_executing_by_a_restart_are_failed(self, make_run):
        await make_run(id="aaaaaaaa-0000-0000-0000-000000000000", status="running")
        await make_run(id="bbbbbbbb-0000-0000-0000-000000000000", status="queued")
        await make_run(id="cccccccc-0000-0000-0000-000000000000", status="success")

        reconciled = await repository.reconcile_orphaned_runs()
        assert reconciled == 2

        async with AsyncSessionLocal() as session:
            still_running = await repository.get_run(
                session, "aaaaaaaa-0000-0000-0000-000000000000"
            )
            untouched = await repository.get_run(session, "cccccccc-0000-0000-0000-000000000000")
        assert still_running.status == RunStatus.FAILED.value
        assert "restarted" in still_running.error_message
        assert untouched.status == RunStatus.SUCCESS.value

    async def test_reconciliation_is_idempotent(self, make_run):
        await make_run(status="running")
        assert await repository.reconcile_orphaned_runs() == 1
        assert await repository.reconcile_orphaned_runs() == 0


class TestPagination:
    async def test_offset_walks_the_full_set_without_gaps(self, make_run):
        for i in range(30):
            await make_run(id=f"{i:08d}-0000-0000-0000-000000000000", issue_number=i)

        seen: list[str] = []
        async with AsyncSessionLocal() as session:
            for offset in range(0, 30, 7):
                rows, total = await repository.list_runs(session, limit=7, offset=offset)
                assert total == 30
                seen.extend(r.id for r in rows)
        assert len(set(seen)) == 30
