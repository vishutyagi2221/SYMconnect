import json
import logging
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Callable

from symconnect.version import VERSION

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/vishutyagi2221/SYMconnect/releases/latest"


def check_for_updates(on_update_available: Callable[[str, str], None]) -> None:
    """Checks for updates in the background and fires a callback if available."""
    def _check() -> None:
        try:
            req = urllib.request.Request(GITHUB_API_URL, headers={"User-Agent": "SYMconnect-Updater"})
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    latest_tag = data.get("tag_name", "").lstrip("v")
                    if latest_tag:
                        try:
                            latest_tuple = tuple(map(int, latest_tag.split('.')))
                            current_tuple = tuple(map(int, VERSION.split('.')))
                            is_newer = latest_tuple > current_tuple
                        except ValueError:
                            is_newer = latest_tag != VERSION
                        
                        if is_newer:
                            # Found a newer version! Find the asset.
                        assets = data.get("assets", [])
                        download_url = None
                        for asset in assets:
                            if asset.get("name", "").startswith("SYMconnect-Setup") and asset.get("name", "").endswith(".exe"):
                                download_url = asset.get("browser_download_url")
                                break
                        
                        if download_url:
                            on_update_available(latest_tag, download_url)
        except Exception as e:
            logger.warning(f"Failed to check for updates: {e}")

    threading.Thread(target=_check, daemon=True).start()


def trigger_update(download_url: str) -> None:
    """Downloads the setup exe and runs it silently, then exits the current app."""
    def _download_and_install() -> None:
        try:
            # Save to temp dir
            temp_dir = Path(os.environ.get("TEMP", str(Path.home())))
            installer_path = temp_dir / "SYMconnect-Update.exe"
            
            # Download file
            req = urllib.request.Request(download_url, headers={"User-Agent": "SYMconnect-Updater"})
            with urllib.request.urlopen(req, timeout=30) as response:
                installer_path.write_bytes(response.read())
            
            # Run installer silently and restart
            # /SILENT shows progress bar. /SP- skips "This will install..." prompt.
            creation_flags = 0x00000008 | 0x00000200 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                [str(installer_path), "/SILENT", "/SP-"],
                creationflags=creation_flags,
                close_fds=True
            )
            
            # Exit current app to allow overwrite
            os._exit(0)
        except Exception as e:
            logger.error(f"Failed to download or run update: {e}")

    threading.Thread(target=_download_and_install, daemon=True).start()
