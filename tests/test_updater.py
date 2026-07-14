import hashlib
import io
from pathlib import Path

import pytest

from symconnect import updater
from symconnect.updater import UpdateInfo, UpdateVerificationError


def update_manifest(version: str, payload: bytes) -> dict:
    installer_name = f"SYMconnect-Setup-{version}.exe"
    digest = hashlib.sha256(payload).hexdigest()
    base_url = f"https://github.com/vishutyagi2221/SYMconnect/releases/download/v{version}"
    return {
        "version": version,
        "download_url": f"{base_url}/{installer_name}",
        "size": len(payload),
        "sha256": digest,
    }


def test_parse_manifest_requires_newer_exact_installer() -> None:
    payload = b"verified installer"
    update = updater.parse_update_manifest(update_manifest("0.2.26", payload), "0.2.25")

    assert update is not None
    assert update.version == "0.2.26"
    assert update.size == len(payload)
    assert update.sha256 == hashlib.sha256(payload).hexdigest()
    assert updater.parse_update_manifest(update_manifest("0.2.25", payload), "0.2.25") is None


def test_parse_manifest_rejects_untrusted_download_url() -> None:
    data = update_manifest("0.2.26", b"installer")
    data["download_url"] = "https://example.com/setup.exe"

    with pytest.raises(UpdateVerificationError):
        updater.parse_update_manifest(data, "0.2.25")


def test_parse_manifest_rejects_mismatched_installer_name() -> None:
    data = update_manifest("0.2.26", b"installer")
    data["download_url"] = data["download_url"].replace("0.2.26.exe", "0.2.25.exe")

    with pytest.raises(UpdateVerificationError):
        updater.parse_update_manifest(data, "0.2.25")


class FakeResponse:
    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_download_update_verifies_size_and_sha256(monkeypatch, tmp_path: Path) -> None:
    payload = b"signed release bytes"
    digest = hashlib.sha256(payload).hexdigest()
    update = UpdateInfo(
        version="0.2.26",
        download_url=(
            "https://github.com/vishutyagi2221/SYMconnect/releases/download/"
            "v0.2.26/SYMconnect-Setup-0.2.26.exe"
        ),
        size=len(payload),
        sha256=digest,
    )
    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )

    installer_path = updater.download_update(update, destination_dir=tmp_path)

    assert installer_path.read_bytes() == payload
    assert installer_path.name == "SYMconnect-Setup-0.2.26.exe"


def test_download_update_removes_tampered_partial(monkeypatch, tmp_path: Path) -> None:
    payload = b"tampered bytes"
    update = UpdateInfo(
        version="0.2.26",
        download_url=(
            "https://github.com/vishutyagi2221/SYMconnect/releases/download/"
            "v0.2.26/SYMconnect-Setup-0.2.26.exe"
        ),
        size=len(payload),
        sha256="0" * 64,
    )
    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )

    with pytest.raises(UpdateVerificationError):
        updater.download_update(update, destination_dir=tmp_path)

    assert not list(tmp_path.glob("*.part"))
