"""
WebSocket connection manager.

Maintains a registry of active connections keyed by run_id.
Broadcast messages are fire-and-forget; dead sockets are pruned silently.
"""

import json
import logging
from collections import defaultdict
from typing import Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # run_id -> list of open WebSocket connections
        self._connections: Dict[str, List[WebSocket]] = defaultdict(list)

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[run_id].append(websocket)
        logger.info("WS connected: run_id=%s  total=%d", run_id, len(self._connections[run_id]))

    def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        try:
            self._connections[run_id].remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, run_id: str, message: dict) -> None:
        """Send message to every client watching this run."""
        dead: List[WebSocket] = []
        for ws in list(self._connections.get(run_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(run_id, ws)

    async def broadcast_text(self, run_id: str, text: str) -> None:
        await self.broadcast(run_id, {"type": "raw", "content": text})


# Singleton used throughout the application
manager = ConnectionManager()
