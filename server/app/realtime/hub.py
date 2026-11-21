"""WebSocket connection hub (one per server process).

Each connection gets a bounded send queue and its own sender task, so a slow client can
never block event delivery to the others. If a queue overflows the connection is closed
with code 4008 and the client re-synchronises via REST after reconnecting.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from starlette.websockets import WebSocket, WebSocketState

from app.realtime.bus import BusMessage

logger = logging.getLogger(__name__)

# Application-specific close codes (4000–4999).
CLOSE_AUTH_FAILED = 4001
CLOSE_PERMISSIONS_CHANGED = 4002
CLOSE_SESSION_ENDED = 4003
CLOSE_OVERLOADED = 4008

QUEUE_SIZE = 500


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    user_id: uuid.UUID
    session_id: uuid.UUID
    permissions: frozenset[str]
    channels: set[str]
    all_control_centers: bool
    token_expires_at: datetime
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    queue: asyncio.Queue[str | None] = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    sender: asyncio.Task[None] | None = None

    def accepts(self, msg: BusMessage) -> bool:
        if msg.required_permission and msg.required_permission not in self.permissions:
            return False
        for ch in msg.channels:
            if ch == "broadcast" or ch in self.channels:
                return True
            if self.all_control_centers and ch.startswith("cc:"):
                return True
        return False


class ConnectionHub:
    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}

    @property
    def count(self) -> int:
        return len(self._connections)

    async def register(self, conn: Connection) -> None:
        self._connections[conn.id] = conn
        conn.sender = asyncio.create_task(self._sender(conn), name=f"ws-sender-{conn.id}")

    async def unregister(self, conn: Connection) -> None:
        self._connections.pop(conn.id, None)
        if conn.sender:
            with contextlib.suppress(asyncio.QueueFull):
                conn.queue.put_nowait(None)
            conn.sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await conn.sender

    async def _sender(self, conn: Connection) -> None:
        while True:
            item = await conn.queue.get()
            if item is None:
                return
            try:
                await conn.websocket.send_text(item)
            except Exception:
                return

    def send(self, conn: Connection, payload: dict[str, object]) -> None:
        try:
            conn.queue.put_nowait(json.dumps(payload, default=str))
        except asyncio.QueueFull:
            logger.warning("WebSocket-Queue voll, Verbindung wird getrennt", extra={"ctx": {"conn": conn.id}})
            asyncio.get_running_loop().create_task(self._close(conn, CLOSE_OVERLOADED, "overloaded"))

    async def _close(self, conn: Connection, code: int, reason: str) -> None:
        if conn.websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await conn.websocket.close(code=code, reason=reason)
        await self.unregister(conn)

    async def handle(self, msg: BusMessage) -> None:
        """Entry point for every message coming from the event bus."""
        if msg.kind == "control":
            await self._handle_control(msg)
            return
        payload = {"type": "event", "id": msg.id, "topic": msg.topic, "ts": msg.ts, "data": msg.data}
        for conn in list(self._connections.values()):
            if conn.accepts(msg):
                self.send(conn, payload)

    async def _handle_control(self, msg: BusMessage) -> None:
        if msg.topic == "disconnect_user":
            user_id = uuid.UUID(str(msg.data["user_id"]))
            code = int(msg.data.get("code", CLOSE_PERMISSIONS_CHANGED))
            for conn in [c for c in self._connections.values() if c.user_id == user_id]:
                await self._close(conn, code, str(msg.data.get("reason", "")))
        elif msg.topic == "disconnect_session":
            session_id = uuid.UUID(str(msg.data["session_id"]))
            for conn in [c for c in self._connections.values() if c.session_id == session_id]:
                await self._close(conn, CLOSE_SESSION_ENDED, "session ended")

    async def close_all(self) -> None:
        for conn in list(self._connections.values()):
            await self._close(conn, 1001, "server shutdown")
