"""
Agent-layer pure logic: verdict parsing, truncation, branch naming, routing.

Every case here corresponds to a defect in the previous implementation.
"""

from __future__ import annotations

import pytest

from app.agents.graph import ROUTES, route_from_supervisor
from app.agents.nodes import _branch_name, _failure_reason, _truncate, parse_verdict
from app.agents.state import MAX_AGENT_ATTEMPTS, initial_state


class TestParseVerdict:
    def test_structured_approval(self):
        assert parse_verdict("Looks good.\n\n### Verdict: APPROVED") == "APPROVED"

    def test_structured_rejection(self):
        assert (
            parse_verdict("### Verdict: NEEDS_REVISION\nReason: SQL injection in db.py:42")
            == "NEEDS_REVISION"
        )

    def test_negated_approval_is_not_an_approval(self):
        # `"APPROVED" in text` matched this and shipped rejected code.
        text = "This change cannot be APPROVED as written.\n### Verdict: NEEDS_REVISION"
        assert parse_verdict(text) == "NEEDS_REVISION"

    def test_prose_saying_not_approved_is_not_an_approval(self):
        assert parse_verdict("The change is NOT APPROVED.") != "APPROVED"

    def test_the_last_verdict_wins_when_restated(self):
        text = "### Verdict: APPROVED\n\nOn reflection:\n### Verdict: NEEDS_REVISION"
        assert parse_verdict(text) == "NEEDS_REVISION"

    def test_unparseable_review_is_unknown_rather_than_approved(self):
        assert parse_verdict("I looked at the diff and have thoughts.") == "UNKNOWN"

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_review_is_unknown(self, value):
        assert parse_verdict(value) == "UNKNOWN"


class TestTruncate:
    def test_short_text_is_untouched(self):
        assert _truncate("hello", 100) == "hello"

    def test_the_tail_is_preserved(self):
        # A pytest run states its verdict at the end; head-only truncation
        # discarded exactly the part the model needed.
        text = "noise " * 2000 + "FAILED tests/test_auth.py::test_login"
        out = _truncate(text, 500)
        assert "FAILED tests/test_auth.py::test_login" in out
        assert len(out) < len(text)

    def test_the_head_is_preserved(self):
        text = "=== FIRST LINE ===\n" + "x" * 5000
        assert "=== FIRST LINE ===" in _truncate(text, 400)

    def test_elision_is_marked(self):
        assert "elided" in _truncate("y" * 5000, 500)


class TestBranchName:
    def test_title_is_slugified(self):
        assert _branch_name(42, "Add Rate Limiting!") == "swarm/issue-42-add-rate-limiting"

    def test_a_title_of_only_punctuation_still_yields_a_valid_branch(self):
        assert _branch_name(7, "!!!???") == "swarm/issue-7"

    def test_long_titles_are_bounded(self):
        name = _branch_name(1, "word " * 100)
        assert len(name) <= 60
        assert not name.endswith("-")

    def test_unicode_does_not_leak_into_the_ref(self):
        name = _branch_name(3, "Fix ünïcödé 🎉 handling")
        assert all(c.isascii() for c in name)


class TestFailureReason:
    def test_the_stated_reason_is_extracted(self):
        assert "assertion failed" in _failure_reason("TESTS_FAILED: assertion failed in auth")

    def test_falls_back_to_the_tail_when_unstated(self):
        assert _failure_reason("something broke") == "something broke"


class TestSupervisorRouting:
    @pytest.mark.parametrize("phase", ["architect", "coder", "reviewer", "pr", "done"])
    def test_known_phases_route(self, phase):
        assert route_from_supervisor({"phase": phase}) in ROUTES

    def test_an_unknown_phase_ends_the_run_rather_than_crashing(self):
        assert route_from_supervisor({"phase": "nonsense"}) == "done"

    def test_a_missing_phase_defaults_to_the_architect(self):
        assert route_from_supervisor({}) == "architect"


class TestInitialState:
    def test_every_key_the_nodes_read_is_present(self):
        state = initial_state(
            run_id="r1",
            installation_id=0,
            repo_owner="octocat",
            repo_name="hello-world",
            issue_number=1,
            issue_title="Fix it",
            issue_body="",
            github_token="ghp_x",
            max_iterations=3,
        )
        for key in (
            "plan",
            "repo_context",
            "branch_name",
            "test_output",
            "test_passed",
            "review_notes",
            "review_verdict",
            "pr_url",
            "iteration",
            "architect_attempts",
            "reviewer_attempts",
        ):
            assert key in state

    def test_an_empty_issue_body_is_given_a_placeholder(self):
        state = initial_state(
            run_id="r1",
            installation_id=0,
            repo_owner="o",
            repo_name="r",
            issue_number=1,
            issue_title="t",
            issue_body="",
            github_token="x",
            max_iterations=3,
        )
        assert state["issue_body"].strip()

    def test_attempt_budget_is_small_enough_to_terminate(self):
        assert 1 <= MAX_AGENT_ATTEMPTS <= 5
