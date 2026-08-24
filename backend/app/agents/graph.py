"""
LangGraph topology.

    START -> supervisor -> architect -> supervisor
                        -> coder     -> supervisor
                        -> reviewer  -> supervisor
                        -> pr        -> END
                        -> done      -> END

The supervisor is the only node that writes `phase`; workers return their own
fields and hand control back. The recursion limit is raised above LangGraph's
default of 25 because a legitimate run with three correction rounds costs
roughly 14 steps and the default left almost no headroom before an opaque
`GraphRecursionError`.
"""

from __future__ import annotations

from collections.abc import Hashable
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.core.logging import get_logger

from .nodes import architect_node, coder_node, pr_node, reviewer_node, supervisor_node
from .state import SwarmState

logger = get_logger(__name__)

ROUTES: dict[Hashable, str] = {
    "architect": "architect",
    "coder": "coder",
    "reviewer": "reviewer",
    "pr": "pr",
    "done": END,
}


def route_from_supervisor(state: SwarmState) -> str:
    phase = state.get("phase", "architect")
    if phase not in ROUTES:
        logger.error("Supervisor produced an unknown phase %r — ending the run.", phase)
        return "done"
    return phase


def build_graph() -> StateGraph:
    graph = StateGraph(SwarmState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("architect", architect_node)
    graph.add_node("coder", coder_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("pr", pr_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_from_supervisor, ROUTES)

    graph.add_edge("architect", "supervisor")
    graph.add_edge("coder", "supervisor")
    graph.add_edge("reviewer", "supervisor")
    graph.add_edge("pr", END)

    return graph


@lru_cache(maxsize=1)
def get_compiled_graph():
    """Compiled once per process; compilation is not free and the graph is static."""
    return build_graph().compile()


# Backwards-compatible module-level handle.
swarm_graph = get_compiled_graph()
