# SYMconnect

SYMconnect is a consent-first Windows remote-support application. The same installed app works in both roles:

- **Remote user:** runs SYMconnect and shares the current `CV-...` session ID and password.
- **Supporter:** runs SYMconnect, enters those credentials, joins the screen stream, and requests control.
- **Relay:** connects both outbound WebSocket clients through a stable public `wss://` endpoint.

Mouse and keyboard control is disabled until the remote user approves the native Windows confirmation dialog.

## Installed workflow

1. Install `SYMconnect-Setup-<version>.exe` on both PCs.
2. The remote user opens SYMconnect and waits for `Live session ready`.
3. The remote user shares the displayed session ID and password with the supporter.
4. The supporter enters them under `Join Session`.
5. The supporter selects `Request Control`.
6. The remote user selects `OK` to enable mouse and keyboard control.

Credentials are regenerated whenever the app starts. Closing the app ends that host session.

## Architecture

```text
Remote-user app  --wss-->  SYMconnect relay  <--wss--  Supporter app
   screen host                                      viewer/controller
```

GitHub stores source code, builds installers, publishes releases, and builds the relay container. GitHub does **not** run the live WebSocket relay. Production installers need a permanent relay URL on a VPS or container platform with TLS.

## Build the Windows installer

Prerequisites:

- Windows 10/11 x64
- Python 3.12
- [Inno Setup 6](https://jrsoftware.org/isinfo.php)

Install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements-build.txt
```

Build the one-file app and installer:

```powershell
.\scripts\build_windows.ps1 `
  -ServerUrl "wss://relay.your-domain.example"
```

Output:

```text
installer\output\SYMconnect-Setup-<version>.exe
```

The version is read from `symconnect/version.py`; the build fails if an explicitly supplied version does not match it. The installer includes Microsoft's signed Evergreen WebView2 bootstrapper and installs the runtime only when it is missing. The relay URL is written beside the installed executable and embedded as a fallback. Do not use a temporary TryCloudflare URL for a production release.

## GitHub Actions releases

The workflow at `.github/workflows/windows-release.yml` builds the app and installer on a clean Windows runner.

1. Create or connect the GitHub repository.
2. In repository **Settings > Secrets and variables > Actions > Variables**, add:

   ```text
   SYMCONNECT_SERVER_URL = wss://relay.your-domain.example
   ```

3. Push the version commit and wait for the `Quality checks` workflow to pass.
4. Create the matching release tag:

   ```powershell
   $Version = .\.venv\Scripts\python.exe -c "from symconnect.version import VERSION; print(VERSION)"
   git tag "v$Version"
   git push origin "v$Version"
   ```

A tag build runs the full preflight again, creates a draft release, uploads or replaces the installer, SHA256 checksum, and `update.json` manifest, and publishes it only after every upload succeeds. Installed apps check the manifest through GitHub's `releases/latest/download` endpoint, avoiding the unauthenticated API rate limit. Public distribution should additionally use a trusted Windows code-signing certificate to avoid unsigned-app warnings.

## Run the relay

For local development:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-server.txt
.\.venv\Scripts\python.exe -m symconnect.server --host 127.0.0.1 --port 8765
```

Health endpoint:

```text
http://127.0.0.1:8765/health
```

Container build:

```powershell
docker build -t symconnect-relay .
docker run --rm -p 8765:8765 symconnect-relay
```

The `Relay container` GitHub workflow publishes `ghcr.io/<owner>/symconnect-relay`. Deploy that image behind a TLS-enabled reverse proxy or managed platform that supports WebSockets. Keep a single relay instance for now because active sessions are stored in memory.

## Development commands

Install all app dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run a local single-PC demo:

```powershell
.\scripts\run_local_demo.ps1
```

## Security behavior

- Session IDs use eight random hexadecimal characters.
- Session passwords use eight characters from an unambiguous random alphabet.
- The relay rate-limits failed pairing attempts and returns a generic rejection message.
- A valid session password permits viewing; interactive control still requires explicit host approval.
- File transfer and clipboard operations are available only while control is approved.
- Injected keys and mouse buttons are tracked and released on focus loss, control release, or disconnect.
- Screen capture runs outside the input event loop and the viewer drops stale undecoded frames to limit latency.
- There is no unattended `Easy Access`, stealth mode, or approval bypass.

See [SECURITY.md](SECURITY.md) before exposing a relay publicly.
