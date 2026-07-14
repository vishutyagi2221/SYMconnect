from __future__ import annotations

import argparse
import asyncio
import json

import websockets


async def verify_viewer(
    server: str,
    session_id: str,
    pairing_code: str,
    timeout: float,
) -> None:
    viewer_url = f"{server.rstrip('/')}/ws/viewer"
    event_types: list[str] = []
    async with websockets.connect(
        viewer_url,
        open_timeout=timeout,
        max_size=20 * 1024 * 1024,
    ) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "viewer:hello",
                    "session_id": session_id,
                    "pairing_code": pairing_code,
                }
            )
        )
        for _ in range(12):
            raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            event = json.loads(raw)
            event_type = str(event.get("type", "unknown"))
            event_types.append(event_type)
            if event_type == "server:error":
                raise RuntimeError(str(event.get("detail", "Relay rejected the session.")))
            if event_type == "host:frame":
                image_size = len(str(event.get("image", "")))
                dimensions = (event.get("screen_width"), event.get("screen_height"))
                print(
                    "Relay smoke test passed: "
                    f"events={event_types}, frame_base64_bytes={image_size}, "
                    f"screen={dimensions[0]}x{dimensions[1]}"
                )
                return

    raise RuntimeError(f"No host frame received. Events: {event_types}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a live SYMconnect session view-only.")
    parser.add_argument("--server", default="wss://symconnect.onrender.com")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--pairing-code", required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    asyncio.run(
        verify_viewer(
            args.server,
            args.session_id,
            args.pairing_code,
            args.timeout,
        )
    )


if __name__ == "__main__":
    main()
