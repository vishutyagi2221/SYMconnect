"""Shared protocol constants for SYMconnect WebSocket messages."""

from __future__ import annotations

from typing import Any


HOST_HELLO = "host:hello"
HOST_REGISTERED = "host:registered"
HOST_FRAME = "host:frame"
HOST_STATUS = "host:status"

VIEWER_HELLO = "viewer:hello"
VIEWER_REGISTERED = "viewer:registered"
VIEWER_CONNECTED = "viewer:connected"
VIEWER_DISCONNECTED = "viewer:disconnected"

CONTROL_REQUEST = "control:request"
CONTROL_DECISION = "control:decision"
CONTROL_STATE = "control:state"
CONTROL_REVOKE = "control:revoke"

INPUT_MOUSE = "input:mouse"
INPUT_KEY = "input:key"

CHAT_MESSAGE = "chat:message"
FILE_SEND = "file:send"
FILE_STATUS = "file:status"
CLIPBOARD_TEXT = "clipboard:text"
SETTINGS_UPDATE = "settings:update"

SERVER_ERROR = "server:error"
SESSION_STATE = "session:state"


def message(message_type: str, **payload: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"type": message_type}
    data.update(payload)
    return data
