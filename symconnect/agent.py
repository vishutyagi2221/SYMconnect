from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import websockets
from rich.console import Console

from .input_control import InputController
from .protocol import (
    CHAT_MESSAGE,
    CLIPBOARD_TEXT,
    CONTROL_DECISION,
    CONTROL_REQUEST,
    CONTROL_REVOKE,
    FILE_SEND,
    FILE_STATUS,
    HOST_FRAME,
    HOST_HELLO,
    HOST_REGISTERED,
    HOST_STATUS,
    INPUT_KEY,
    INPUT_MOUSE,
    SETTINGS_UPDATE,
    VIEWER_CONNECTED,
    VIEWER_DISCONNECTED,
    message,
)
from .screen_capture import ScreenCapture

console = Console()
MAX_FILE_BYTES = 50 * 1024 * 1024
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class HostAgent:
    def __init__(
        self,
        server: str,
        session_id: str,
        pairing_code: str,
        fps: int,
        monitor: int,
        max_width: int,
        quality: int,
        control_approval: Callable[[], bool] | None = None,
        on_registered: Callable[[], None] | None = None,
        on_notification: Callable[[str, str], None] | None = None,
    ) -> None:
        self.server = server
        self.session_id = session_id
        self.pairing_code = pairing_code
        self.fps = max(1, min(fps, 30))
        self.capture = ScreenCapture(monitor_index=monitor, max_width=max_width, jpeg_quality=quality)
        self.input_controller = InputController(self.capture.bounds)
        self.control_enabled = False
        self.control_request_pending = False
        self.viewer_connected = asyncio.Event()
        self.control_approval = control_approval
        self.on_registered = on_registered
        self.on_notification = on_notification
        self.ws: Any = None

    async def run(self) -> None:
        console.print("[bold]SYMconnect host agent[/bold]")
        console.print(f"Session ID: [bold cyan]{self.session_id}[/bold cyan]")
        console.print(f"Pairing code: [bold cyan]{self.pairing_code}[/bold cyan]")
        console.print("Keep this terminal visible. Press Ctrl+C to stop sharing.")

        ws_url = self.server
        if not ws_url.endswith("/ws/host"):
            ws_url = ws_url.rstrip("/") + "/ws/host"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with websockets.connect(ws_url, max_size=None, ping_interval=20, additional_headers=headers) as websocket:
            self.ws = websocket
            await self.send(
                message(
                    HOST_HELLO,
                    session_id=self.session_id,
                    pairing_code=self.pairing_code,
                    host_name=socket.gethostname(),
                )
            )

            registered = await self.receive()
            if registered.get("type") != HOST_REGISTERED:
                detail = registered.get("detail", "Server rejected host registration.")
                raise RuntimeError(str(detail))

            if self.on_registered is not None:
                try:
                    self.on_registered()
                except Exception as exc:
                    console.print(f"[yellow]Host status callback failed:[/yellow] {exc}")

            console.print(f"Connected to server: [green]{self.server}[/green]")
            stream_task = asyncio.create_task(self.stream_loop(), name="screen-stream")
            receive_task = asyncio.create_task(self.receive_loop(), name="agent-receiver")
            done, pending = await asyncio.wait(
                {stream_task, receive_task},
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()

    async def stream_loop(self) -> None:
        sequence = 0
        while True:
            await self.viewer_connected.wait()
            while self.viewer_connected.is_set():
                started = time.perf_counter()
                frame = self.capture.grab()
                sequence += 1
                await self.send(
                    message(
                        HOST_FRAME,
                        image=frame.image,
                        screen_width=frame.screen_width,
                        screen_height=frame.screen_height,
                        image_width=frame.image_width,
                        image_height=frame.image_height,
                        timestamp=frame.timestamp,
                        sequence=sequence,
                    )
                )
                elapsed = time.perf_counter() - started
                await asyncio.sleep(max(0.0, (1 / self.fps) - elapsed))

    async def receive_loop(self) -> None:
        async for raw in self.ws:
            event = parse_json(raw)
            event_type = event.get("type")

            if event_type == VIEWER_CONNECTED:
                self.viewer_connected.set()
                self.control_enabled = False
                self.control_request_pending = False
                console.print("[green]Viewer connected.[/green]")
            elif event_type == VIEWER_DISCONNECTED:
                self.viewer_connected.clear()
                self.control_enabled = False
                self.control_request_pending = False
                console.print("[yellow]Viewer disconnected. Control disabled.[/yellow]")
                self.control_request_pending = False
                console.print("[yellow]Viewer disconnected. Control disabled.[/yellow]")
            elif event_type == CONTROL_REQUEST:
                await self.handle_control_request()
            elif event_type == CONTROL_REVOKE:
                self.control_enabled = False
                self.control_request_pending = False
                console.print("[yellow]Viewer released control.[/yellow]")
            elif event_type == CHAT_MESSAGE:
                text = str(event.get("text") or "").strip()
                if text:
                    console.print(f"[cyan]Viewer chat:[/cyan] {text}")
                    if self.on_notification:
                        self.on_notification("Chat Message", text)
            elif event_type == SETTINGS_UPDATE:
                self.apply_settings(event)
            elif event_type == CLIPBOARD_TEXT:
                await self.handle_clipboard_text(event)
            elif event_type == FILE_SEND:
                await self.handle_file_send(event)
            elif event_type == INPUT_MOUSE and self.control_enabled:
                self.input_controller.handle_mouse(event)
            elif event_type == INPUT_KEY and self.control_enabled:
                self.input_controller.handle_key(event)

    async def handle_control_request(self) -> None:
        if self.control_enabled:
            await self.send(message(CONTROL_DECISION, approved=True, reason="Already approved by host."))
            return
        if self.control_request_pending:
            console.print("[yellow]Duplicate control request ignored; approval is already pending.[/yellow]")
            return

        self.control_request_pending = True
        console.print("[yellow]Viewer requested mouse and keyboard control.[/yellow]")
        try:
            if self.control_approval is not None:
                try:
                    approved = bool(await asyncio.to_thread(self.control_approval))
                except Exception as exc:
                    console.print(f"[yellow]Control approval dialog failed:[/yellow] {exc}")
                    approved = False
            else:
                console.print("[yellow]No approval GUI attached; auto-denying control request.[/yellow]")
                approved = False

            self.control_enabled = approved
            reason = "Approved by host." if approved else "Denied by host."
            await self.send(message(CONTROL_DECISION, approved=approved, reason=reason))
        finally:
            self.control_request_pending = False


def parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def default_session_id() -> str:
    return f"CV-{secrets.token_hex(4).upper()}"


def default_pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))


async def async_main(args: argparse.Namespace) -> None:
    server = resolve_server_url(args.server)
    agent = HostAgent(
        server=server,
        session_id=args.session_id or default_session_id(),
        pairing_code=args.pairing_code or default_pairing_code(),
        fps=args.fps,
        monitor=args.monitor,
        max_width=args.max_width,
        quality=args.quality,
    )
    await agent.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SYMconnect host agent.")
    parser.add_argument("--server", default="", help="Host WebSocket URL.")
    parser.add_argument("--session-id", default="", help="Optional fixed session ID.")
    parser.add_argument("--pairing-code", default="", help="Optional fixed pairing code.")
    parser.add_argument("--fps", default=8, type=int, help="Capture frames per second.")
    parser.add_argument("--monitor", default=1, type=int, help="Monitor index from mss. Usually 1.")
    parser.add_argument("--max-width", default=1366, type=int, help="Max encoded frame width. Use 0 for native size.")
    parser.add_argument("--quality", default=62, type=int, help="JPEG quality from 1 to 95.")
    args = parser.parse_args()

    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Host stopped.[/yellow]")


def resolve_server_url(cli_value: str) -> str:
    if cli_value.strip():
        return cli_value.strip()

    env_value = (
        os.getenv("SYMCONNECT_SERVER_URL", "").strip()
        or os.getenv("CONTROLVIEWER_SERVER", "").strip()
    )
    if env_value:
        return env_value
    if env_value:
        return env_value

    config_value = read_server_url_config()
    if config_value:
        return config_value

    default = "wss://symconnect.onrender.com/ws/host"
    console.print("[yellow]Server URL is required for public testing.[/yellow]")
    console.print("Example: wss://relay.your-domain.example")
    answer = console.input(f"Server WebSocket URL [{default}]: ").strip()
    return answer or default


def read_server_url_config() -> str:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "server_url.txt")
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            candidates.append(Path(bundle_root) / "server_url.txt")
    candidates.append(Path.cwd() / "server_url.txt")

    for path in candidates:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def safe_filename(value: str) -> str:
    safe = "".join(ch for ch in value if ch.isalnum() or ch in " ._-").strip()
    return (safe or "symconnect-file")[:160]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{secrets.token_hex(4)}{suffix}")


def set_clipboard_text(text: str) -> None:
    if os.name == "nt":
        set_windows_clipboard_text(text)
        return

    import tkinter

    root = tkinter.Tk()
    try:
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
    finally:
        root.destroy()


def set_windows_clipboard_text(text: str) -> None:
    import ctypes

    cf_unicode_text = 13
    gmem_moveable = 0x0002
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if not user32.OpenClipboard(None):
        raise OSError("Could not open clipboard")
    try:
        if not user32.EmptyClipboard():
            raise OSError("Could not empty clipboard")

        buffer = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buffer)
        handle = kernel32.GlobalAlloc(gmem_moveable, size)
        if not handle:
            raise OSError("Could not allocate clipboard memory")

        locked = kernel32.GlobalLock(handle)
        if not locked:
            raise OSError("Could not lock clipboard memory")
        ctypes.memmove(locked, buffer, size)
        kernel32.GlobalUnlock(handle)

        if not user32.SetClipboardData(cf_unicode_text, handle):
            raise OSError("Could not set clipboard data")
    finally:
        user32.CloseClipboard()


if __name__ == "__main__":
    main()
