from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from symconnect.version import VERSION

logger = logging.getLogger(__name__)

UPDATE_MANIFEST_URL = (
    "https://github.com/vishutyagi2221/SYMconnect/"
    "releases/latest/download/update.json"
)
_RELEASE_DOWNLOAD_PREFIX = "/vishutyagi2221/symconnect/releases/download/"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){2}$")

UpdateCallback = Callable[[dict[str, Any]], None]


class UpdateVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    size: int
    sha256: str


def _version_tuple(value: str) -> tuple[int, int, int]:
    normalized = value.strip().lstrip("v")
    if not _VERSION_PATTERN.fullmatch(normalized):
        raise ValueError(f"Unsupported version: {value}")
    return tuple(int(part) for part in normalized.split("."))  # type: ignore[return-value]


def _validate_release_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or not parsed.path.lower().startswith(_RELEASE_DOWNLOAD_PREFIX)
    ):
        raise UpdateVerificationError("GitHub release download URL is invalid.")
    return value


def parse_update_manifest(
    data: dict[str, Any],
    current_version: str = VERSION,
) -> UpdateInfo | None:
    latest_version = str(data.get("version", "")).strip().lstrip("v")
    if not latest_version or _version_tuple(latest_version) <= _version_tuple(current_version):
        return None

    expected_name = f"SYMconnect-Setup-{latest_version}.exe"
    download_url = _validate_release_url(str(data.get("download_url", "")))
    if not urlparse(download_url).path.endswith(f"/{expected_name}"):
        raise UpdateVerificationError("Update manifest installer name is invalid.")

    size = int(data.get("size") or 0)
    if size <= 0:
        raise UpdateVerificationError("Update manifest installer size is missing.")

    sha256 = str(data.get("sha256") or "").strip().lower()
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise UpdateVerificationError("Update manifest SHA256 is invalid.")

    return UpdateInfo(
        version=latest_version,
        download_url=download_url,
        size=size,
        sha256=sha256,
    )


def check_for_updates(on_update_available: Callable[[UpdateInfo], None]) -> None:
    """Check GitHub in the background and return only verified release metadata."""

    def _check() -> None:
        try:
            request = urllib.request.Request(
                UPDATE_MANIFEST_URL,
                headers={
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "User-Agent": f"SYMconnect/{VERSION}",
                },
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            update = parse_update_manifest(data)
            if update is not None:
                on_update_available(update)
        except Exception as exc:
            logger.warning("Failed to check for updates: %s", exc)

    threading.Thread(target=_check, name="symconnect-update-check", daemon=True).start()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_expected_sha256(update: UpdateInfo) -> str:
    if not _SHA256_PATTERN.fullmatch(update.sha256):
        raise UpdateVerificationError("Update SHA256 is invalid.")
    return update.sha256


def _emit_status(callback: UpdateCallback | None, state: str, message: str) -> None:
    if callback is not None:
        callback({"state": state, "message": message})


def download_update(
    update: UpdateInfo,
    destination_dir: Path | None = None,
    on_status: UpdateCallback | None = None,
) -> Path:
    _validate_release_url(update.download_url)
    expected_sha256 = _load_expected_sha256(update)
    destination_dir = destination_dir or (
        Path(tempfile.gettempdir()) / "SYMconnect" / "updates"
    )
    destination_dir.mkdir(parents=True, exist_ok=True)
    installer_path = destination_dir / f"SYMconnect-Setup-{update.version}.exe"
    partial_path = installer_path.with_suffix(".exe.part")

    if installer_path.is_file():
        if installer_path.stat().st_size == update.size and _file_sha256(installer_path) == expected_sha256:
            return installer_path
        installer_path.unlink()

    request = urllib.request.Request(
        update.download_url,
        headers={"User-Agent": f"SYMconnect/{VERSION}"},
    )
    downloaded = 0
    last_percent = -1
    digest = hashlib.sha256()

    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial_path.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                percent = min(100, int(downloaded * 100 / update.size))
                if percent // 5 != last_percent // 5:
                    last_percent = percent
                    _emit_status(
                        on_status,
                        "downloading",
                        f"Downloading verified update... {percent}%",
                    )

        if downloaded != update.size:
            raise UpdateVerificationError(
                f"Downloaded size mismatch: expected {update.size}, got {downloaded}."
            )
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise UpdateVerificationError("Downloaded installer failed SHA256 verification.")

        os.replace(partial_path, installer_path)
        return installer_path
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _launch_installer(installer_path: Path) -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise RuntimeError("Automatic installation is available only in the installed Windows app.")

    app_path = Path(sys.executable).resolve()
    log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SYMconnect" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    install_log = log_dir / f"update-{int(time.time())}.log"
    arguments = ", ".join(
        _powershell_literal(argument)
        for argument in (
            "/VERYSILENT",
            "/SP-",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/FORCECLOSEAPPLICATIONS",
            f'/LOG="{install_log}"',
        )
    )
    command = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            f"$installer = {_powershell_literal(str(installer_path))}",
            f"$app = {_powershell_literal(str(app_path))}",
            f"$arguments = @({arguments})",
            "Start-Sleep -Seconds 2",
            "$process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru",
            "$exitCode = $process.ExitCode",
            "if (Test-Path -LiteralPath $app) { Start-Process -FilePath $app }",
            "Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue",
            "exit $exitCode",
        )
    )
    encoded_command = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
    )
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-EncodedCommand",
            encoded_command,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )


def trigger_update(
    update: UpdateInfo,
    on_status: UpdateCallback | None = None,
) -> None:
    """Download, verify, and hand off installation without freezing the UI."""

    def _download_and_install() -> None:
        try:
            _emit_status(on_status, "downloading", "Preparing verified update...")
            installer_path = download_update(update, on_status=on_status)
            _emit_status(on_status, "installing", "Update verified. Restarting to install...")
            _launch_installer(installer_path)
            time.sleep(0.25)
            os._exit(0)
        except Exception as exc:
            logger.exception("Failed to install update")
            _emit_status(on_status, "error", f"Update failed: {exc}")

    threading.Thread(
        target=_download_and_install,
        name="symconnect-update-install",
        daemon=True,
    ).start()
