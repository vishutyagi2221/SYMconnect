from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
import threading
from pathlib import Path
from typing import Any


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
from symconnect.updater import check_for_updates, trigger_update
from symconnect.version import VERSION


class Api:
    def __init__(self, session_id: str, pairing_code: str, base_url: str) -> None:
        self.session_id = session_id
        self.pairing_code = pairing_code
        self.base_url = base_url
        self.window: Any = None
        self._status_lock = threading.Lock()
        self._host_status = {
            "state": "connecting" if base_url else "error",
            "detail": (
                "Connecting to secure server..."
                if base_url
                else "Server configuration is missing. Reinstall SYMconnect or contact support."
            ),
        }

    def attach_window(self, window: Any) -> None:
        self.window = window

    def _run_js(self, function_name: str, payload: dict[str, Any]) -> None:
        if self.window is None:
            return
        script = (
            f"if (window.{function_name}) {{ "
            f"window.{function_name}({json.dumps(payload)}); "
            "}"
        )
        try:
            self.window.run_js(script)
        except Exception:
            return

    def publish_bootstrap(self) -> None:
        self._run_js(
            "symconnectBootstrap",
            {
                "credentials": self.get_credentials(),
                "server_url": self.base_url,
                "status": self.get_host_status(),
            },
        )

    def get_credentials(self) -> dict[str, str]:
        return {"id": self.session_id, "pass": self.pairing_code}

    def get_server_url(self) -> str:
        return self.base_url

    def get_host_status(self) -> dict[str, str]:
        with self._status_lock:
            return dict(self._host_status)

    def set_host_status(self, state: str, detail: str) -> None:
        with self._status_lock:
            self._host_status = {"state": state, "detail": detail}
        self._run_js("symconnectApplyHostStatus", self.get_host_status())

    def confirm_control_request(self) -> bool:
        if self.window is None:
            return False
        return bool(
            self.window.create_confirmation_dialog(
                "Remote control request",
                "A supporter is requesting control of your mouse and keyboard.\n\n"
                "Select OK to allow or Cancel to deny.",
            )
        )

    def show_notification(self, title: str, message: str) -> None:
        self._run_js(
            "symconnectHostNotification",
            {"title": title, "message": message}
        )

    def trigger_app_update(self, download_url: str) -> None:
        trigger_update(download_url)


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


def start_agent(session_id: str, pairing_code: str, server_url: str, api: Api) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        agent = HostAgent(
            server=server_url,
            session_id=session_id,
            pairing_code=pairing_code,
            fps=12,
            monitor=1,
            max_width=1920,
            quality=75,
            control_approval=api.confirm_control_request,
            on_registered=lambda: api.set_host_status(
                "ready",
                "Live session ready - share your ID and password.",
            ),
            on_notification=api.show_notification,
        )
        loop.run_until_complete(agent.run())
        api.set_host_status("error", "Secure server connection closed.")
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        api.set_host_status("error", f"Connection failed: {detail}")
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

    window = webview.create_window(
        f"SYMconnect v{VERSION}",
        html_path.as_uri(),
        js_api=api,
        width=1180,
        height=700,
        min_size=(900, 600),
        background_color="#0a0a0a",
    )
    api.attach_window(window)
    window.events.loaded += api.publish_bootstrap

    if server_url:
        threading.Thread(
            target=start_agent,
            args=(session_id, pairing_code, server_url, api),
            daemon=True,
        ).start()

    def on_update_found(latest_tag: str, download_url: str) -> None:
        api._run_js(
            "symconnectShowUpdate",
            {"version": latest_tag, "url": download_url}
        )

    check_for_updates(on_update_found)

    webview.start()


if __name__ == "__main__":
    main()
