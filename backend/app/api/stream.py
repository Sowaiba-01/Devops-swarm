"""
Live run stream.

Two behaviours the previous endpoint lacked:

* **History replay on connect.** It only forwarded events produced *after* the
  socket opened, so opening a run that was already three minutes in showed a
  blank console until the next event arrived. The client sends the highest
  sequence number it holds and receives the gap before the live feed starts.
* **Liveness.** The handler blocked forever on `receive_text()` with no
  heartbeat, so an idle proxy silently dropped the connection and the dashboard
  sat there looking connected. The server now pings, and a socket that stops
  answering is closed.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.core.security import require_api_key_ws
from app.db import repository
from app.db.database import session_scope
from app.db.models import ensure_utc
from app.ws_manager import manager

logger = get_logger(__name__)
router = APIRouter(tags=["stream"])

HEARTBEAT_SECONDS = 20.0
CLIENT_IDLE_TIMEOUT_SECONDS = 120.0


@router.websocket("/ws/{run_id}")
async def stream_run(
    websocket: WebSocket,
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    _: str = Depends(require_api_key_ws),
) -> None:
    if not await manager.connect(run_id, websocket):
        return

    try:
        async with session_scope() as session:
            run = await repository.get_run(session, run_id)
            if run is None:
                await websocket.send_json({"type": "error", "content": "Run not found"})
                await websocket.close(code=1008, reason="Unknown run")
                return

            backlog = await repository.list_logs(session, run_id, limit=2000, after_seq=after_seq)

        # Replay first so the client's console is complete before live events.
        for entry in backlog:
            await websocket.send_json(
                {
                    "seq": entry.seq,
                    "run_id": run_id,
                    "agent": entry.agent,
                    "type": entry.log_type,
                    "content": entry.content,
                    "timestamp": (ts.isoformat() if (ts := ensure_utc(entry.timestamp)) else None),
                    "replay": True,
                }
            )

        await websocket.send_json(
            {
                "type": "ready",
                "run_id": run_id,
                "status": run.status,
                "phase": run.phase,
                "last_seq": backlog[-1].seq if backlog else after_seq,
            }
        )

        await _pump(websocket)

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket stream failed", extra={"run_id": run_id})
    finally:
        await manager.disconnect(run_id, websocket)
        with contextlib.suppress(Exception):
            await websocket.close()


async def _pump(websocket: WebSocket) -> None:
    """
    Hold the socket open.

    Outbound events are pushed by `ConnectionManager.broadcast`; this loop only
    watches for client traffic and sends heartbeats. A client that sends nothing
    for CLIENT_IDLE_TIMEOUT_SECONDS despite the pings is treated as gone.
    """
    silent_for = 0.0
    while True:
        try:
            await asyncio.wait_for(websocket.receive_text(), timeout=HEARTBEAT_SECONDS)
            silent_for = 0.0
        except TimeoutError:
            silent_for += HEARTBEAT_SECONDS
            if silent_for >= CLIENT_IDLE_TIMEOUT_SECONDS:
                await websocket.close(code=1000, reason="Idle")
                return
            await websocket.send_json({"type": "ping"})
