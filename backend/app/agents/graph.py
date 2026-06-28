"""
LangGraph StateGraph definition for the DevOps Swarm.

Topology:
    START → supervisor → architect → supervisor
                       → coder     → supervisor
                       → reviewer  → supervisor
                       → pr        → END
                       → done      → END

The supervisor reads `state["phase"]` (set by each node) to decide routing.
"""

import logging
from langgraph.graph import END, START, StateGraph

from .nodes import architect_node, coder_node, pr_node, reviewer_node, supervisor_node
from .state import SwarmState

logger = logging.getLogger(__name__)


def _route_from_supervisor(state: SwarmState) -> str:
    """Conditional edge: read phase set by supervisor_node and route."""
    phase = state.get("phase", "architect")
    logger.debug("Router: phase=%s", phase)
    return phase


def build_graph() -> StateGraph:
    graph = StateGraph(SwarmState)

    # ── Nodes ──────────────────────────────────────────────────────────
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("architect", architect_node)
    graph.add_node("coder", coder_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("pr", pr_node)

    # ── Entry point ────────────────────────────────────────────────────
    graph.add_edge(START, "supervisor")

    # ── Supervisor routes conditionally ────────────────────────────────
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "architect": "architect",
            "coder": "coder",
            "reviewer": "reviewer",
            "pr": "pr",
            "done": END,
        },
    )

    # ── All worker nodes return to supervisor ──────────────────────────
    graph.add_edge("architect", "supervisor")
    graph.add_edge("coder", "supervisor")
    graph.add_edge("reviewer", "supervisor")
    graph.add_edge("pr", END)

    return graph


# Compiled graph — ready to invoke
swarm_graph = build_graph().compile()
