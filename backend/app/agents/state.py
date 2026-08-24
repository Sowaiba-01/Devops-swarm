"""
Shared graph state.

`architect_attempts` and `reviewer_attempts` exist to bound the loop. The
supervisor routes on "is `plan` empty?"; when an agent returned an empty string
— which happens whenever the model answers with a tool call and no prose, or the
provider truncates — the supervisor sent it straight back to the same node
forever, until LangGraph's recursion limit aborted the run with an opaque error.
Counting attempts turns that into a bounded retry with a clear failure message.
"""

from __future__ import annotations

from typing import Literal, TypedDict

Phase = Literal["architect", "coder", "reviewer", "pr", "done"]


class SwarmState(TypedDict, total=False):
    # ── Identity ──────────────────────────────────────────────────────
    run_id: str
    installation_id: int

    # ── Target ────────────────────────────────────────────────────────
    repo_owner: str
    repo_name: str
    issue_number: int
    issue_title: str
    issue_body: str

    # ── Credentials (never logged; redacted at every output boundary) ──
    github_token: str

    # ── Routing ───────────────────────────────────────────────────────
    phase: Phase

    # ── Agent outputs ─────────────────────────────────────────────────
    plan: str | None
    repo_context: str | None
    branch_name: str | None
    test_output: str | None
    test_passed: bool | None
    review_notes: str | None
    review_verdict: str | None  # APPROVED | NEEDS_REVISION | UNKNOWN
    pr_url: str | None

    # ── Loop control ──────────────────────────────────────────────────
    iteration: int
    max_iterations: int
    architect_attempts: int
    reviewer_attempts: int

    # ── Terminal ──────────────────────────────────────────────────────
    status: str
    error_message: str | None


MAX_AGENT_ATTEMPTS = 2


def initial_state(
    *,
    run_id: str,
    installation_id: int,
    repo_owner: str,
    repo_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    github_token: str,
    max_iterations: int,
) -> SwarmState:
    """Build a complete state so no node has to guess at a missing key."""
    return SwarmState(
        run_id=run_id,
        installation_id=installation_id,
        repo_owner=repo_owner,
        repo_name=repo_name,
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body or "(no description provided)",
        github_token=github_token,
        phase="architect",
        plan=None,
        repo_context=None,
        branch_name=None,
        test_output=None,
        test_passed=None,
        review_notes=None,
        review_verdict=None,
        pr_url=None,
        iteration=0,
        max_iterations=max_iterations,
        architect_attempts=0,
        reviewer_attempts=0,
        status="running",
        error_message=None,
    )
