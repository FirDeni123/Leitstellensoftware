"""Realtime WebSocket endpoint.

Protocol (JSON text frames)::

    client -> {"type": "auth", "token": "<access token>"}       (first frame, within 5 s;
                                                                  repeat before token expiry)
    server -> {"type": "welcome", "connection_id", "user_id", "server_time", "channels"}
    server -> {"type": "event", "id", "topic", "ts", "data"}
    client -> {"type": "ping", "ts": ...}  server -> {"type": "pong", "ts": ..., "server_time": ...}
    server -> {"type": "error", "code", "message"}

The token is sent as first message instead of in the URL so it never shows up in proxy
or access logs. After a reconnect the client must re-sync its data via REST, because
events emitted while it was offline are not replayed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import AuthContext, authenticate_token
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.realtime.hub import CLOSE_AUTH_FAILED, Connection, ConnectionHub

router = APIRouter()
logger = logging.getLogger(__name__)


def _channels(auth: AuthContext) -> set[str]:
    return {f"user:{auth.user.id}", *(f"cc:{cc}" for cc in auth.control_center_ids())}


async def _authenticate(websocket: WebSocket, token: str) -> tuple[AuthContext, datetime]:
    app = websocket.app
    async with app.state.db.sessionmaker() as session:
        auth = await authenticate_token(session, app.state.settings, token)
        if auth.user.must_change_password:
            raise AppError("Passwortänderung erforderlich")
        # Touch lazy relationships while the session is open.
        _ = auth.control_center_ids()
    return auth, decode_access_token(app.state.settings, token).expires_at


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    app = websocket.app
    settings = app.state.settings
    hub: ConnectionHub = app.state.hub
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=settings.ws_auth_timeout_seconds)
        msg = json.loads(raw)
        if msg.get("type") != "auth" or not isinstance(msg.get("token"), str):
            raise AppError("Erste Nachricht muss 'auth' sein")
        auth, expires_at = await _authenticate(websocket, msg["token"])
    except (TimeoutError, json.JSONDecodeError, AppError, WebSocketDisconnect) as exc:
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "error", "code": "auth_failed", "message": str(exc) or "Timeout"}
            )
            await websocket.close(code=CLOSE_AUTH_FAILED)
        return

    conn = Connection(
        websocket=websocket,
        user_id=auth.user.id,
        session_id=auth.session_id,
        permissions=auth.permissions,
        channels=_channels(auth),
        all_control_centers=auth.is_admin,
        token_expires_at=expires_at,
    )
    await hub.register(conn)
    hub.send(
        conn,
        {
            "type": "welcome",
            "connection_id": conn.id,
            "user_id": str(auth.user.id),
            "server_time": datetime.now(UTC).isoformat(),
            "channels": sorted(conn.channels),
        },
    )
    logger.info("WebSocket verbunden", extra={"ctx": {"user": auth.user.username, "conn": conn.id}})

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=settings.ws_heartbeat_seconds)
            except TimeoutError:
                raw = None
            if conn.token_expires_at <= datetime.now(UTC):
                await websocket.close(code=CLOSE_AUTH_FAILED, reason="token expired")
                break
            if raw is None:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                hub.send(conn, {"type": "error", "code": "bad_message", "message": "Ungültiges JSON"})
                continue
            kind = msg.get("type")
            if kind == "ping":
                hub.send(
                    conn, {"type": "pong", "ts": msg.get("ts"), "server_time": datetime.now(UTC).isoformat()}
                )
            elif kind == "auth" and isinstance(msg.get("token"), str):
                try:
                    new_auth, conn.token_expires_at = await _authenticate(websocket, msg["token"])
                except AppError:
                    await websocket.close(code=CLOSE_AUTH_FAILED, reason="re-auth failed")
                    break
                if new_auth.user.id != conn.user_id:
                    await websocket.close(code=CLOSE_AUTH_FAILED, reason="user mismatch")
                    break
                hub.send(conn, {"type": "reauth_ok", "expires_at": conn.token_expires_at.isoformat()})
            else:
                hub.send(
                    conn, {"type": "error", "code": "unknown_type", "message": f"Unbekannter Typ: {kind}"}
                )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(conn)
        logger.info("WebSocket getrennt", extra={"ctx": {"conn": conn.id}})
