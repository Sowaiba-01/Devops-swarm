"""
Supervisor routing against real state.

The headline case is the loop: when an agent returned an empty string the
supervisor routed straight back to it, forever, until LangGraph aborted with a
`GraphRecursionError` and the run died with an unreadable message.
"""

from __future__ import annotations

import pytest

from app.agents.nodes import supervisor_node
from app.agents.state import MAX_AGENT_ATTEMPTS, initial_state


@pytest.fixture
def state(make_run):
    async def _build(**overrides):
        await make_run(id="22222222-2222-2222-2222-222222222222")
        base = initial_state(
            run_id="22222222-2222-2222-2222-222222222222",
            installation_id=0,
            repo_owner="octocat",
            repo_name="hello-world",
            issue_number=1,
            issue_title="Fix it",
            issue_body="body",
            github_token="ghp_test",
            max_iterations=3,
        )
        base.update(overrides)
        return base

    return _build


class TestHappyPath:
    async def test_no_plan_routes_to_the_architect(self, state):
        assert (await supervisor_node(await state()))["phase"] == "architect"

    async def test_a_plan_with_no_test_result_routes_to_the_coder(self, state):
        result = await supervisor_node(await state(plan="do the thing"))
        assert result["phase"] == "coder"

    async def test_passing_tests_route_to_the_reviewer(self, state):
        result = await supervisor_node(await state(plan="p", test_passed=True, iteration=1))
        assert result["phase"] == "reviewer"

    async def test_a_completed_review_routes_to_the_pull_request(self, state):
        result = await supervisor_node(
            await state(plan="p", test_passed=True, iteration=1, review_notes="looks fine")
        )
        assert result["phase"] == "pr"

    async def test_an_existing_pull_request_ends_the_run(self, state):
        result = await supervisor_node(
            await state(pr_url="https://github.com/o/r/pull/1", plan="p")
        )
        assert result["phase"] == "done"


class TestCorrectionLoop:
    async def test_a_failure_below_the_limit_returns_to_the_coder(self, state):
        result = await supervisor_node(
            await state(plan="p", test_passed=False, iteration=1, max_iterations=3)
        )
        assert result["phase"] == "coder"

    async def test_exhausting_the_limit_moves_on_instead_of_retrying(self, state):
        result = await supervisor_node(
            await state(plan="p", test_passed=False, iteration=3, max_iterations=3)
        )
        assert result["phase"] == "reviewer"


class TestEmptyOutputTermination:
    async def test_an_empty_plan_retries_the_architect_while_budget_remains(self, state):
        result = await supervisor_node(await state(plan="", architect_attempts=1))
        assert result["phase"] == "architect"

    async def test_an_empty_plan_fails_the_run_once_the_budget_is_spent(self, state):
        # Previously this bounced between supervisor and architect until the
        # graph's recursion limit killed the run.
        result = await supervisor_node(await state(plan="", architect_attempts=MAX_AGENT_ATTEMPTS))
        assert result["phase"] == "done"
        assert result["status"] == "failed"
        assert "no plan" in result["error_message"].lower()

    async def test_whitespace_is_not_a_plan(self, state):
        result = await supervisor_node(
            await state(plan="   \n\t ", architect_attempts=MAX_AGENT_ATTEMPTS)
        )
        assert result["status"] == "failed"

    async def test_an_exhausted_reviewer_proceeds_to_the_pull_request(self, state):
        result = await supervisor_node(
            await state(
                plan="p",
                test_passed=True,
                iteration=1,
                review_notes="",
                reviewer_attempts=MAX_AGENT_ATTEMPTS,
            )
        )
        assert result["phase"] == "pr"
        assert result["review_verdict"] == "UNKNOWN"


class TestTerminalStates:
    async def test_a_failed_run_stops_immediately(self, state):
        result = await supervisor_node(await state(status="failed", plan="p"))
        assert result["phase"] == "done"
