"""
Prometheus metrics.

Kept deliberately small: the four RED signals for HTTP, plus the swarm-specific
counters an on-call engineer would actually page on (runs failing, LLM errors,
sandboxes leaking, tool latency).

prometheus_client is an optional import so the service still starts if it is not
installed; in that case every helper becomes a no-op.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

try:  # pragma: no cover - exercised implicitly by import
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    METRICS_AVAILABLE = True
except ImportError:  # pragma: no cover
    METRICS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"

    class _Noop:
        def __init__(self, *_: Any, **__: Any) -> None: ...
        def labels(self, *_: Any, **__: Any) -> _Noop:
            return self

        def inc(self, *_: Any, **__: Any) -> None: ...
        def dec(self, *_: Any, **__: Any) -> None: ...
        def set(self, *_: Any, **__: Any) -> None: ...
        def observe(self, *_: Any, **__: Any) -> None: ...

    Counter = Gauge = Histogram = _Noop  # type: ignore[assignment,misc]
    CollectorRegistry = object  # type: ignore[assignment,misc]

    def generate_latest(*_: Any, **__: Any) -> bytes:  # type: ignore[misc]
        return b"# prometheus_client not installed\n"


REGISTRY = CollectorRegistry() if METRICS_AVAILABLE else None
_kw: dict[str, Any] = {"registry": REGISTRY} if METRICS_AVAILABLE else {}

# ── HTTP ───────────────────────────────────────────────────────────────
http_requests_total = Counter(
    "swarm_http_requests_total",
    "HTTP requests by method, route template and status class.",
    ["method", "route", "status"],
    **_kw,
)
http_request_duration = Histogram(
    "swarm_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "route"],
    buckets=(0.005, 0.025, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    **_kw,
)

# ── Swarm ──────────────────────────────────────────────────────────────
runs_started_total = Counter(
    "swarm_runs_started_total", "Swarm runs started, by trigger source.", ["source"], **_kw
)
runs_completed_total = Counter(
    "swarm_runs_completed_total", "Swarm runs finished, by terminal status.", ["status"], **_kw
)
run_duration = Histogram(
    "swarm_run_duration_seconds",
    "Wall-clock duration of a full swarm run.",
    ["status"],
    buckets=(30, 60, 120, 300, 600, 900, 1800, 3600),
    **_kw,
)
runs_in_flight = Gauge("swarm_runs_in_flight", "Swarm runs currently executing.", **_kw)

agent_node_duration = Histogram(
    "swarm_agent_node_duration_seconds",
    "Time spent inside a single agent node.",
    ["agent"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600),
    **_kw,
)
llm_calls_total = Counter(
    "swarm_llm_calls_total", "LLM invocations by agent and outcome.", ["agent", "outcome"], **_kw
)
tool_calls_total = Counter(
    "swarm_tool_calls_total",
    "Agent tool invocations by name and outcome.",
    ["tool", "outcome"],
    **_kw,
)
tool_duration = Histogram(
    "swarm_tool_duration_seconds",
    "Agent tool latency.",
    ["tool"],
    buckets=(0.1, 0.5, 1, 5, 15, 60, 180),
    **_kw,
)

sandboxes_active = Gauge("swarm_sandboxes_active", "E2B sandboxes currently held open.", **_kw)
sandboxes_reaped_total = Counter(
    "swarm_sandboxes_reaped_total", "Sandboxes closed by the idle reaper.", **_kw
)
websocket_connections = Gauge(
    "swarm_websocket_connections", "Open dashboard WebSocket connections.", **_kw
)


@contextmanager
def observe(histogram: Any, **labels: str) -> Iterator[None]:
    """Time a block and record it, whether or not it raises."""
    import time

    start = time.perf_counter()
    try:
        yield
    finally:
        target = histogram.labels(**labels) if labels else histogram
        target.observe(time.perf_counter() - start)


def render() -> bytes:
    if METRICS_AVAILABLE and REGISTRY is not None:
        return generate_latest(REGISTRY)
    return generate_latest()
