"""
LangGraph shared state for the DevOps Swarm.

`phase` controls which agent node the supervisor routes to next.
Each agent node is responsible for setting the correct next phase
before returning.
"""

from typing import TypedDict, Optional


class SwarmState(TypedDict):
    # ── Run identity ──────────────────────────────────────────────────
    run_id: str
    installation_id: int

    # ── GitHub issue ──────────────────────────────────────────────────
    repo_owner: str
    repo_name: str
    issue_number: int
    issue_title: str
    issue_body: str

    # ── GitHub credentials (fetched once per run) ─────────────────────
    github_token: str

    # ── Routing ───────────────────────────────────────────────────────
    # architect | coder | reviewer | pr | done
    phase: str

    # ── Agent outputs ─────────────────────────────────────────────────
    plan: Optional[str]
    branch_name: Optional[str]
    test_output: Optional[str]
    test_passed: Optional[bool]
    review_notes: Optional[str]
    pr_url: Optional[str]

    # ── Self-correction loop ──────────────────────────────────────────
    iteration: int          # how many coder passes have occurred
    max_iterations: int     # = settings.MAX_CORRECTION_ITERATIONS

    # ── Final status ──────────────────────────────────────────────────
    status: str             # running | success | failed
    error_message: Optional[str]
