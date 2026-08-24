"""
WebSocket fan-out for live run streams.

Scope note: connections are held in process memory, so a client only receives
events produced by the replica it is attached to. That is correct for the
single-replica deployment this ships with. Horizontal scaling requires a shared
bus (Redis pub/sub) behind `broadcast()`; the rest of the codebase only touches
this class, so that change stays local.

Two properties the previous version lacked and that matter in practice:

* a slow or wedged client cannot stall the agent — sends are bounded by a
  timeout and the socket is dropped rather than awaited forever;
* every connection is registered against a limit, so a client that reconnects in
  a loop cannot exhaust the process's file descriptors.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.core.logging import get_logger
from app.core.metrics import websocket_connections

logger = get_logger(__name__)

SEND_TIMEOUT_SECONDS = 5.0
MAX_CONNECTIONS_PER_RUN = 20
MAX_TOTAL_CONNECTIONS = 500


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    @property
    def total_connections(self) -> int:
        return sum(len(v) for v in self._connections.values())

    async def connect(self, run_id: str, websocket: WebSocket) -> bool:
        """Accept and register a socket. Returns False if a limit was hit."""
        async with self._lock:
            if self.total_connections >= MAX_TOTAL_CONNECTIONS:
                logger.warning("Rejecting WebSocket: global connection limit reached")
                await websocket.close(code=1013, reason="Server at capacity")
                return False
            if len(self._connections[run_id]) >= MAX_CONNECTIONS_PER_RUN:
                logger.warning("Rejecting WebSocket for run_id=%s: per-run limit reached", run_id)
                await websocket.close(code=1013, reason="Too many watchers for this run")
                return False

        await websocket.accept()

        async with self._lock:
            self._connections[run_id].add(websocket)
            websocket_connections.set(self.total_connections)
        logger.info("WebSocket connected", extra={"run_id": run_id})
        return True

    async def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.get(run_id, set()).discard(websocket)
            if not self._connections.get(run_id):
                self._connections.pop(run_id, None)
            websocket_connections.set(self.total_connections)

    async def broadcast(self, run_id: str, message: dict) -> None:
        """
        Fan a message out to everyone watching `run_id`.

        Never raises: agent progress must not depend on the health of a browser
        tab. Sockets that time out or error are dropped.
        """
        async with self._lock:
            targets = list(self._connections.get(run_id, ()))
        if not targets:
            return

        results = await asyncio.gather(
            *(self._send(ws, message) for ws in targets), return_exceptions=True
        )
        dead = [ws for ws, ok in zip(targets, results, strict=False) if ok is not True]
        for ws in dead:
            await self.disconnect(run_id, ws)
            with contextlib.suppress(Exception):
                await ws.close()

    @staticmethod
    async def _send(websocket: WebSocket, message: dict) -> bool:
        if websocket.client_state is not WebSocketState.CONNECTED:
            return False
        try:
            await asyncio.wait_for(websocket.send_json(message), timeout=SEND_TIMEOUT_SECONDS)
            return True
        except (TimeoutError, Exception):
            return False

    async def close_all(self) -> None:
        """Shut every socket down cleanly during application shutdown."""
        async with self._lock:
            everything = [(rid, ws) for rid, wss in self._connections.items() for ws in wss]
            self._connections.clear()
            websocket_connections.set(0)
        for _, ws in everything:
            with contextlib.suppress(Exception):
                await ws.close(code=1001, reason="Server shutting down")


manager = ConnectionManager()
