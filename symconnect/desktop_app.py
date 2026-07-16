from __future__ import annotations

import asyncio
import os
import platform
import shutil
import sys
import threading
import time
import tempfile
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


def _configure_windows_runtime() -> None:
    original_machine = platform.machine

    def patched_machine() -> str:
        machine = original_machine()
        if machine.lower() in {"arm64", "aarch64"}:
            return "AMD64"
        return machine

    platform.machine = patched_machine

    if getattr(sys, "frozen", False):
        python_dll = Path(sys._MEIPASS) / (
            f"python{sys.version_info.major}{sys.version_info.minor}.dll"
        )
        if python_dll.is_file():
            os.environ.setdefault("PYTHONNET_PYDLL", str(python_dll))
    os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")


_configure_windows_runtime()

import webview

from symconnect.agent import (
    HostAgent,
    default_pairing_code,
    default_session_id,
    read_server_url_config,
)
from symconnect.updater import UpdateInfo, check_for_updates, trigger_update
from symconnect.version import VERSION


class Api:
    def __init__(self, session_id: str, pairing_code: str, base_url: str) -> None:
        self._session_id = session_id
        self._pairing_code = pairing_code
        self._base_url = base_url
        self._window: Any = None
        self._host_status = {
            "state": "connecting" if base_url else "error",
            "detail": (
                "Connecting to secure server..."
                if base_url
                else "Server configuration is missing. Reinstall SYMconnect or contact support."
            ),
        }
        self._status_lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._events_lock = threading.Lock()
        self._update_lock = threading.Lock()
        self._pending_update: UpdateInfo | None = None
        self._update_started = False

    def _attach_window(self, window: Any) -> None:
        # This must remain private. pywebview recursively exposes public attributes.
        self._window = window

    def get_events(self) -> list[dict[str, Any]]:
        with self._events_lock:
            events = list(self._events)
            self._events.clear()
            return events

    def _emit_event(self, name: str, payload: dict[str, Any]) -> None:
        with self._events_lock:
            self._events.append({"name": name, "payload": payload})

    def _publish_bootstrap(self) -> None:
        self._emit_event(
            "symconnectBootstrap",
            {
                "credentials": self.get_credentials(),
                "server_url": self._base_url,
                "status": self.get_host_status(),
            },
        )

    def get_credentials(self) -> dict[str, str]:
        return {"id": self._session_id, "pass": self._pairing_code}

    def get_server_url(self) -> str:
        return self._base_url

    def get_host_status(self) -> dict[str, str]:
        with self._status_lock:
            return dict(self._host_status)

    def _set_host_status(self, state: str, detail: str) -> None:
        with self._status_lock:
            self._host_status = {"state": state, "detail": detail}
        self._emit_event("symconnectApplyHostStatus", self.get_host_status())

    def _confirm_control_request(self) -> bool:
        if self._window is None:
            return False
        return bool(
            self._window.create_confirmation_dialog(
                "Remote control request",
                "A supporter is requesting control of your mouse and keyboard.\n\n"
                "Select OK to allow or Cancel to deny.",
            )
        )

    def _show_notification(self, title: str, message: str) -> None:
        self._emit_event(
            "symconnectHostNotification",
            {"title": title, "message": message}
        )

    def _offer_update(self, update: UpdateInfo) -> None:
        with self._update_lock:
            self._pending_update = update
            self._update_started = False
        self._emit_event(
            "symconnectShowUpdate",
            {"version": update.version},
        )

    def _handle_update_status(self, status: dict[str, Any]) -> None:
        if status.get("state") == "error":
            with self._update_lock:
                self._update_started = False
        self._emit_event("symconnectUpdateStatus", status)

    def trigger_app_update(self) -> dict[str, Any]:
        with self._update_lock:
            if self._pending_update is None:
                return {"ok": False, "error": "No verified update is available."}
            if self._update_started:
                return {"ok": False, "error": "The update is already running."}
            self._update_started = True
            update = self._pending_update

        trigger_update(update, self._handle_update_status)
        return {"ok": True, "version": update.version}
        
    def open_downloads_folder(self) -> None:
        import os
        from pathlib import Path
        import platform
        
        downloads_dir = Path.home() / "Downloads" / "SYMconnectTransfers"
        if downloads_dir.exists():
            if platform.system() == "Windows":
                os.startfile(str(downloads_dir))
            elif platform.system() == "Darwin":
                import subprocess
                subprocess.Popen(["open", str(downloads_dir)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(downloads_dir)])


def normalize_server_base(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if base_url.startswith("https://"):
        base_url = "wss://" + base_url.removeprefix("https://")
    elif base_url.startswith("http://"):
        base_url = "ws://" + base_url.removeprefix("http://")
    for suffix in ("/ws/host", "/ws/viewer"):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)]
    return base_url.rstrip("/")


def build_ui_url(
    html_path: Path,
    session_id: str,
    pairing_code: str,
    server_url: str,
    status: dict[str, str],
) -> str:
    query = urlencode(
        {
            "session_id": session_id,
            "pairing_code": pairing_code,
            "server_url": server_url,
            "host_state": status.get("state", "connecting"),
            "host_detail": status.get("detail", "Connecting to secure server..."),
            "app_version": VERSION,
        }
    )
    return f"{html_path.as_uri()}#{query}"


def prepare_desktop_html(html_path: Path) -> Path:
    target_dir = Path(tempfile.gettempdir()) / "symconnect-ui" / VERSION
    shutil.copytree(html_path.parent, target_dir, dirs_exist_ok=True)

    html = html_path.read_text(encoding="utf-8")
    html = html.replace('href="/static/', 'href="')
    html = html.replace('src="/static/', 'src="')

    target_html = target_dir / "desktop_index.html"
    target_html.write_text(html, encoding="utf-8")
    return target_html


def start_agent(session_id: str, pairing_code: str, server_url: str, api: Api) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        agent = HostAgent(
            server=server_url,
            session_id=session_id,
            pairing_code=pairing_code,
            fps=15,
            monitor=1,
            max_width=1600,
            quality=68,
            control_approval=api._confirm_control_request,
            on_registered=lambda: api._set_host_status(
                "ready",
                "Live session ready - share your ID and password.",
            ),
            on_notification=api._show_notification,
        )
        retry_delay = 2
        while True:
            try:
                loop.run_until_complete(agent.run())
                api._set_host_status("error", "Secure server connection closed. Retrying...")
            except Exception as exc:
                detail = str(exc).strip() or type(exc).__name__
                api._set_host_status(
                    "error",
                    f"Connection failed: {detail}. Retrying in {retry_delay}s...",
                )
            
            # Simple backoff up to 10 seconds
            time.sleep(retry_delay)
            retry_delay = min(10, retry_delay * 2)
    finally:
        loop.close()


def main() -> None:
    session_id = default_session_id()
    pairing_code = default_pairing_code()
    configured_url = (
        os.getenv("SYMCONNECT_SERVER_URL", "").strip()
        or os.getenv("CONTROLVIEWER_SERVER", "").strip()
        or read_server_url_config()
    )
    if not configured_url and not getattr(sys, "frozen", False):
        configured_url = "wss://symconnect.onrender.com"
    server_url = normalize_server_base(configured_url)
    api = Api(session_id, pairing_code, server_url)

    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent
    html_path = base_path / "symconnect" / "static" / "index.html"
    if not html_path.is_file():
        html_path = base_path / "static" / "index.html"
    html_path = prepare_desktop_html(html_path)

    window = webview.create_window(
        f"SYMconnect v{VERSION}",
        build_ui_url(
            html_path,
            session_id,
            pairing_code,
            server_url,
            api.get_host_status(),
        ),
        js_api=api,
        width=1180,
        height=700,
        min_size=(900, 600),
        background_color="#0a0a0a",
    )
    api._attach_window(window)
    api._publish_bootstrap()

    if server_url:
        threading.Thread(
            target=start_agent,
            args=(session_id, pairing_code, server_url, api),
            daemon=True,
        ).start()

    check_for_updates(api._offer_update)

    webview.start()


if __name__ == "__main__":
    main()
