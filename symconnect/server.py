from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .protocol import (
    CHAT_MESSAGE,
    CLIPBOARD_TEXT,
    CONTROL_DECISION,
    CONTROL_REQUEST,
    CONTROL_REVOKE,
    CONTROL_STATE,
    FILE_SEND,
    FILE_STATUS,
    HOST_FRAME,
    HOST_HELLO,
    HOST_REGISTERED,
    HOST_STATUS,
    INPUT_KEY,
    INPUT_MOUSE,
    SERVER_ERROR,
    SESSION_STATE,
    SETTINGS_UPDATE,
    VIEWER_CONNECTED,
    VIEWER_DISCONNECTED,
    VIEWER_HELLO,
    VIEWER_REGISTERED,
    message,
)

logger = logging.getLogger("symconnect.server")
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="SYMconnect", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MAX_TEXT_LENGTH = 20_000
MAX_FILE_BYTES = 8 * 1024 * 1024
AUTH_ATTEMPT_LIMIT = 12
AUTH_ATTEMPT_WINDOW_SECONDS = 60.0


class AuthAttemptLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def record(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - AUTH_ATTEMPT_WINDOW_SECONDS
        async with self._lock:
            attempts = self._attempts.setdefault(key, deque())
            while attempts and attempts[0] < cutoff:
                attempts.popleft()
            if len(attempts) >= AUTH_ATTEMPT_LIMIT:
                return False
            attempts.append(now)
            return True

    async def clear(self, key: str) -> None:
        async with self._lock:
            self._attempts.pop(key, None)


@dataclass
class Session:
    session_id: str
    pairing_hash: str
    host_name: str
    host: WebSocket
    viewer: WebSocket | None = None
    control_allowed: bool = False
    control_pending: bool = False
    created_at: float = field(default_factory=time.time)
    frame_count: int = 0


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: Session) -> tuple[bool, str | None]:
        async with self._lock:
            existing = self._sessions.get(session.session_id)
            if existing is not None:
                return False, "Session ID is already in use."
            self._sessions[session.session_id] = session
            return True, None

    async def get(self, session_id: str) -> Session | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def remove_host(self, session_id: str, host: WebSocket) -> Session | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.host is not host:
                return None
            return self._sessions.pop(session_id)

    async def attach_viewer(self, session_id: str, viewer: WebSocket) -> tuple[Session | None, str | None, WebSocket | None]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None, "Session not found.", None
            previous_viewer = session.viewer
            session.viewer = viewer
            session.control_allowed = False
            session.control_pending = False
            return session, None, previous_viewer

    async def detach_viewer(self, session_id: str, viewer: WebSocket) -> Session | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.viewer is not viewer:
                return None
            session.viewer = None
            session.control_allowed = False
            session.control_pending = False
            return session

    async def set_control(self, session_id: str, allowed: bool) -> Session | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.control_allowed = allowed
            session.control_pending = False
            return session

    async def request_control(self, session_id: str) -> tuple[Session | None, str]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None, "missing"
            if session.control_allowed:
                return session, "approved"
            if session.control_pending:
                return session, "pending"
            session.control_pending = True
            return session, "requested"

    async def revoke_control(self, session_id: str) -> Session | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.control_allowed = False
            session.control_pending = False
            return session


sessions = SessionStore()
auth_attempts = AuthAttemptLimiter()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "symconnect"})


@app.websocket("/ws/host")
async def host_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id: str | None = None

    try:
        hello = await receive_json(websocket)
        if hello.get("type") != HOST_HELLO:
            await close_with_error(websocket, "Expected host hello.")
            return

        session_id = clean_text(hello.get("session_id"))
        pairing_code = clean_text(hello.get("pairing_code"))
        host_name = clean_text(hello.get("host_name")) or "Host"
        if not session_id or not pairing_code:
            await close_with_error(websocket, "Missing session ID or pairing code.")
            return

        session = Session(
            session_id=session_id,
            pairing_hash=hash_pairing_code(pairing_code),
            host_name=host_name,
            host=websocket,
        )
        created, error = await sessions.create(session)
        if not created:
            await close_with_error(websocket, error or "Could not create session.")
            return

        await send_json(websocket, message(HOST_REGISTERED, session_id=session_id))
        logger.info("Host registered session %s from %s", session_id, host_name)

        async for raw in websocket.iter_text():
            event = parse_json(raw)
            event_type = event.get("type")
            session = await sessions.get(session_id)
            if session is None:
                break

            if event_type == HOST_FRAME:
                session.frame_count += 1
                if session.viewer is not None:
                    await send_json(session.viewer, event)
            elif event_type == HOST_STATUS:
                if session.viewer is not None:
                    await send_json(session.viewer, event)
            elif event_type == CONTROL_DECISION:
                approved = bool(event.get("approved"))
                await sessions.set_control(session_id, approved)
                if session.viewer is not None:
                    await send_json(
                        session.viewer,
                        message(
                            CONTROL_STATE,
                            allowed=approved,
                            pending=False,
                            reason=clean_text(event.get("reason")),
                        ),
                    )
            elif event_type in {CHAT_MESSAGE, FILE_STATUS}:
                if session.viewer is not None:
                    await send_json(session.viewer, event)
            elif event_type == CLIPBOARD_TEXT:
                if session.viewer is not None:
                    safe_text = clean_long_text(event.get("text"))
                    await send_json(
                        session.viewer,
                        message(CLIPBOARD_TEXT, text=safe_text, direction="from-host"),
                    )
            else:
                logger.debug("Ignoring host event %s", event_type)
    except WebSocketDisconnect:
        pass
    finally:
        if session_id is not None:
            session = await sessions.remove_host(session_id, websocket)
            if session is not None and session.viewer is not None:
                await send_json(session.viewer, message(SERVER_ERROR, detail="Host disconnected."))
                await session.viewer.close(code=1012)
            logger.info("Host session %s closed", session_id)


@app.websocket("/ws/viewer")
async def viewer_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id: str | None = None

    try:
        hello = await receive_json(websocket)
        if hello.get("type") != VIEWER_HELLO:
            await close_with_error(websocket, "Expected viewer hello.")
            return

        session_id = clean_text(hello.get("session_id"))
        pairing_code = clean_text(hello.get("pairing_code"))
        if not session_id or not pairing_code:
            await close_with_error(websocket, "Missing session ID or pairing code.")
            return

        client_key = client_identity(websocket)
        if not await auth_attempts.record(client_key):
            await close_with_error(websocket, "Too many pairing attempts. Try again later.")
            return

        session = await sessions.get(session_id)
        pairing_hash = hash_pairing_code(pairing_code)
        if session is None or not secrets.compare_digest(session.pairing_hash, pairing_hash):
            await close_with_error(websocket, "Session ID or password rejected.")
            return
        await auth_attempts.clear(client_key)

        session, error, previous_viewer = await sessions.attach_viewer(session_id, websocket)
        if session is None:
            await close_with_error(websocket, error or "Could not attach viewer.")
            return
        if previous_viewer is not None:
            await send_json(previous_viewer, message(SERVER_ERROR, detail="Viewer reconnected. Closing old tab."))
            await previous_viewer.close(code=1012)

        await send_json(
            websocket,
            message(
                VIEWER_REGISTERED,
                session_id=session_id,
                host_name=session.host_name,
                control_allowed=session.control_allowed,
                pending=session.control_pending,
            ),
        )
        await send_json(
            websocket,
            message(
                SESSION_STATE,
                session_id=session_id,
                host_name=session.host_name,
                connected=True,
                control_allowed=False,
                pending=False,
            ),
        )
        await send_json(session.host, message(VIEWER_CONNECTED))
        logger.info("Viewer attached to session %s", session_id)

        async for raw in websocket.iter_text():
            event = parse_json(raw)
            event_type = event.get("type")
            session = await sessions.get(session_id)
            if session is None:
                await close_with_error(websocket, "Session ended.")
                return

            if event_type == CONTROL_REQUEST:
                session, request_status = await sessions.request_control(session_id)
                if session is None:
                    await close_with_error(websocket, "Session ended.")
                    return
                if request_status == "requested":
                    await send_json(session.host, message(CONTROL_REQUEST))
                    await send_json(
                        websocket,
                        message(
                            CONTROL_STATE,
                            allowed=False,
                            pending=True,
                            reason="Control request sent. Waiting for host approval.",
                        ),
                    )
                elif request_status == "pending":
                    await send_json(
                        websocket,
                        message(
                            CONTROL_STATE,
                            allowed=False,
                            pending=True,
                            reason="Control request already pending on host.",
                        ),
                    )
                elif request_status == "approved":
                    await send_json(
                        websocket,
                        message(CONTROL_STATE, allowed=True, pending=False, reason="Control already approved."),
                    )
            elif event_type == CONTROL_REVOKE:
                await sessions.revoke_control(session_id)
                await send_json(session.host, message(CONTROL_REVOKE))
                await send_json(websocket, message(CONTROL_STATE, allowed=False, pending=False, reason="Control released."))
            elif event_type == CHAT_MESSAGE:
                await send_json(
                    session.host,
                    message(
                        CHAT_MESSAGE,
                        sender="viewer",
                        text=clean_long_text(event.get("text")),
                        timestamp=time.time(),
                    ),
                )
            elif event_type == SETTINGS_UPDATE:
                await send_json(
                    session.host,
                    message(
                        SETTINGS_UPDATE,
                        fps=clamp_int(event.get("fps"), 1, 30),
                        quality=clamp_int(event.get("quality"), 20, 95),
                        max_width=clamp_int(event.get("max_width"), 640, 3840),
                    ),
                )
                await send_json(websocket, message(HOST_STATUS, detail="Quality settings sent to host."))
            elif event_type == CLIPBOARD_TEXT:
                if session.control_allowed:
                    await send_json(
                        session.host,
                        message(
                            CLIPBOARD_TEXT,
                            text=clean_long_text(event.get("text")),
                            direction="to-host",
                        ),
                    )
                else:
                    await send_json(websocket, message(CONTROL_STATE, allowed=False, pending=session.control_pending, reason="Clipboard requires approved control."))
            elif event_type == FILE_SEND:
                file_size = clamp_int(event.get("size"), 0, MAX_FILE_BYTES + 1)
                if not session.control_allowed:
                    await send_json(websocket, message(FILE_STATUS, ok=False, detail="File transfer requires approved control."))
                elif file_size > MAX_FILE_BYTES:
                    await send_json(websocket, message(FILE_STATUS, ok=False, detail="File is too large. Max size is 8 MB."))
                else:
                    await send_json(
                        session.host,
                        message(
                            FILE_SEND,
                            name=clean_filename(event.get("name")),
                            size=file_size,
                            mime=clean_text(event.get("mime")),
                            data=clean_base64(event.get("data")),
                        ),
                    )
            elif event_type in {INPUT_MOUSE, INPUT_KEY}:
                if session.control_allowed:
                    await send_json(session.host, event)
                else:
                    await send_json(
                        websocket,
                        message(
                            CONTROL_STATE,
                            allowed=False,
                            pending=session.control_pending,
                            reason="Control is not approved yet.",
                        ),
                    )
            else:
                logger.debug("Ignoring viewer event %s", event_type)
    except WebSocketDisconnect:
        pass
    finally:
        if session_id is not None:
            session = await sessions.detach_viewer(session_id, websocket)
            if session is not None:
                await send_json(session.host, message(VIEWER_DISCONNECTED))
                logger.info("Viewer detached from session %s", session_id)


async def receive_json(websocket: WebSocket) -> dict[str, Any]:
    raw = await websocket.receive_text()
    return parse_json(raw)


def parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_text(json.dumps(payload, separators=(",", ":")))
    except RuntimeError:
        logger.debug("WebSocket send failed because the connection is closed.")


async def close_with_error(websocket: WebSocket, detail: str) -> None:
    await send_json(websocket, message(SERVER_ERROR, detail=detail))
    await websocket.close(code=1008)


def hash_pairing_code(pairing_code: str) -> str:
    return hashlib.sha256(pairing_code.encode("utf-8")).hexdigest()


def client_identity(websocket: WebSocket) -> str:
    forwarded = websocket.headers.get("cf-connecting-ip") or websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if websocket.client is not None:
        return websocket.client.host
    return "unknown"


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:128]


def clean_long_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_TEXT_LENGTH]


def clean_filename(value: Any) -> str:
    if not isinstance(value, str):
        return "symconnect-file"
    safe = "".join(ch for ch in value if ch.isalnum() or ch in " ._-").strip()
    return (safe or "symconnect-file")[:160]


def clean_base64(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def clamp_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SYMconnect signaling server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:128]


def clean_long_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_TEXT_LENGTH]


def clean_filename(value: Any) -> str:
    if not isinstance(value, str):
        return "symconnect-file"
    safe = "".join(ch for ch in value if ch.isalnum() or ch in " ._-").strip()
    return (safe or "symconnect-file")[:160]


def clean_base64(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def clamp_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SYMconnect signaling server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", default=8765, type=int, help="Bind port.")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload.")
    parser.add_argument("--log-level", default="info", help="uvicorn log level.")
    args = parser.parse_args()

    uvicorn.run(
        "symconnect.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
        ws_max_size=104857600,
    )


if __name__ == "__main__":
    main()
