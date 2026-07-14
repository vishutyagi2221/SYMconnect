import asyncio
import json
import re
import socket
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pynput import keyboard, mouse
import uvicorn
import websockets

from symconnect import __version__
from symconnect.agent import HostAgent, PAIRING_ALPHABET, default_pairing_code, default_session_id
from symconnect.desktop_app import Api, build_ui_url
from symconnect.input_control import InputController, KEY_ALIASES
from symconnect.server import AUTH_ATTEMPT_LIMIT, AuthAttemptLimiter, app
from symconnect.version import VERSION


def test_package_version_has_one_source() -> None:
    assert __version__ == VERSION


def test_session_credentials_have_expected_shape() -> None:
    session_id = default_session_id()
    password = default_pairing_code()

    assert re.fullmatch(r"CV-[0-9A-F]{8}", session_id)
    assert len(password) == 8
    assert set(password) <= set(PAIRING_ALPHABET)


def test_credentials_change_between_sessions() -> None:
    session_ids = {default_session_id() for _ in range(20)}
    passwords = {default_pairing_code() for _ in range(20)}

    assert len(session_ids) == 20
    assert len(passwords) == 20


def test_auth_attempt_limiter_blocks_and_resets() -> None:
    async def scenario() -> None:
        limiter = AuthAttemptLimiter()
        for _ in range(AUTH_ATTEMPT_LIMIT):
            assert await limiter.record("test-client")
        assert not await limiter.record("test-client")
        await limiter.clear("test-client")
        assert await limiter.record("test-client")

    asyncio.run(scenario())


def test_desktop_api_pushes_bootstrap_and_status() -> None:
    api = Api("CV-A1B2C3D4", "ABCDEFGH", "wss://relay.example")
    api._publish_bootstrap()
    api._set_host_status("ready", "Live session ready")

    events = api.get_events()
    assert len(events) == 2
    assert events[0]["name"] == "symconnectBootstrap"
    assert "CV-A1B2C3D4" in str(events[0]["payload"])
    assert "wss://relay.example" in str(events[0]["payload"])
    assert events[1]["name"] == "symconnectApplyHostStatus"
    assert "Live session ready" in str(events[1]["payload"])


def test_desktop_api_keeps_native_window_private() -> None:
    api = Api("CV-A1B2C3D4", "ABCDEFGH", "wss://relay.example")
    api._attach_window(object())

    assert "window" not in vars(api)
    assert "_window" in vars(api)


def test_ui_url_contains_bridge_independent_bootstrap(tmp_path: Path) -> None:
    html_path = tmp_path / "index.html"
    html_path.touch()
    url = build_ui_url(
        html_path,
        "CV-A1B2C3D4",
        "ABCDEFGH",
        "wss://relay.example",
        {"state": "connecting", "detail": "Connecting"},
    )
    params = parse_qs(urlparse(url).fragment)

    assert params["session_id"] == ["CV-A1B2C3D4"]
    assert params["pairing_code"] == ["ABCDEFGH"]
    assert params["server_url"] == ["wss://relay.example"]


def test_stream_waits_for_viewer() -> None:
    async def exercise() -> None:
        class FakeCapture:
            def __init__(self) -> None:
                self.calls = 0

            def grab(self):
                self.calls += 1
                return type(
                    "Frame",
                    (),
                    {
                        "image": "frame",
                        "screen_width": 1,
                        "screen_height": 1,
                        "image_width": 1,
                        "image_height": 1,
                        "timestamp": 0,
                    },
                )()

        agent = object.__new__(HostAgent)
        agent.fps = 30
        agent.capture = FakeCapture()
        agent.viewer_connected = asyncio.Event()

        async def send(_payload) -> None:
            agent.viewer_connected.clear()

        agent.send = send
        task = asyncio.create_task(agent.stream_loop())
        try:
            await asyncio.sleep(0.03)
            assert agent.capture.calls == 0
            agent.viewer_connected.set()
            await asyncio.sleep(0.05)
            assert agent.capture.calls == 1
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(exercise())


class RecordingController:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.position = (0, 0)

    def press(self, value: object) -> None:
        self.events.append(("press", value))

    def release(self, value: object) -> None:
        self.events.append(("release", value))

    def scroll(self, x: int, y: int) -> None:
        self.events.append(("scroll", (x, y)))


def make_input_controller() -> tuple[InputController, RecordingController, RecordingController]:
    keyboard_controller = RecordingController()
    mouse_controller = RecordingController()
    controller = InputController(
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        keyboard_controller=keyboard_controller,
        mouse_controller=mouse_controller,
    )
    return controller, keyboard_controller, mouse_controller


def test_input_reset_releases_windows_key_and_all_pressed_inputs() -> None:
    controller, keyboard_controller, mouse_controller = make_input_controller()

    controller.handle_key({"action": "down", "key": "Meta", "code": "MetaLeft"})
    controller.handle_key({"action": "down", "key": "Meta", "code": "MetaLeft"})
    controller.handle_key({"action": "down", "key": "e", "code": "KeyE"})
    controller.handle_mouse(
        {"action": "down", "button": "left", "x_pct": 0.5, "y_pct": 0.5}
    )
    controller.release_all()

    assert keyboard_controller.events == [
        ("press", keyboard.Key.cmd_l),
        ("press", "e"),
        ("release", "e"),
        ("release", keyboard.Key.cmd_l),
    ]
    assert mouse_controller.events == [
        ("press", mouse.Button.left),
        ("release", mouse.Button.left),
    ]


def test_key_codes_preserve_right_modifier_and_recover_unknown_keyup() -> None:
    controller, keyboard_controller, _ = make_input_controller()

    controller.handle_key({"action": "down", "key": "Shift", "code": "ShiftRight"})
    controller.handle_key({"action": "up", "key": "Shift", "code": "ShiftRight"})
    controller.handle_key({"action": "down", "key": "e", "code": "KeyE"})
    controller.handle_key({"action": "up", "key": "Unidentified", "code": "KeyE"})

    assert keyboard_controller.events == [
        ("press", keyboard.Key.shift_r),
        ("release", keyboard.Key.shift_r),
        ("press", "e"),
        ("release", "e"),
    ]


def test_extended_windows_and_media_keys_are_mapped() -> None:
    expected = {
        "ContextMenu": keyboard.Key.menu,
        "NumLock": keyboard.Key.num_lock,
        "PrintScreen": keyboard.Key.print_screen,
        "ScrollLock": keyboard.Key.scroll_lock,
        "AudioVolumeMute": keyboard.Key.media_volume_mute,
        "MediaPlayPause": keyboard.Key.media_play_pause,
        "MediaTrackNext": keyboard.Key.media_next,
        "F24": keyboard.Key.f24,
    }

    assert {name: KEY_ALIASES[name] for name in expected} == expected


def test_capture_encoding_does_not_block_input_event_loop() -> None:
    async def exercise() -> None:
        class SlowCapture:
            def grab(self):
                time.sleep(0.2)
                return type(
                    "Frame",
                    (),
                    {
                        "image": "frame",
                        "screen_width": 1,
                        "screen_height": 1,
                        "image_width": 1,
                        "image_height": 1,
                        "timestamp": 0,
                    },
                )()

        agent = object.__new__(HostAgent)
        agent.fps = 30
        agent.capture = SlowCapture()
        agent.viewer_connected = asyncio.Event()
        agent.viewer_connected.set()

        async def send(_payload) -> None:
            agent.viewer_connected.clear()

        agent.send = send
        task = asyncio.create_task(agent.stream_loop())
        started = time.perf_counter()
        try:
            await asyncio.sleep(0.03)
            assert time.perf_counter() - started < 0.12
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(exercise())


def test_viewer_has_focus_loss_input_cleanup_and_bounded_frame_decode() -> None:
    source = (Path(__file__).parents[1] / "symconnect" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert 'window.addEventListener("blur", releaseRemoteInputs)' in source
    assert 'send({ type: "input:reset" })' in source
    assert "state.pendingFrameImage = data.image" in source
    assert "if (state.frameDecoding || !state.pendingFrameImage) return" in source


def test_live_relay_forwards_input_reset_and_disconnect_cleanup() -> None:
    async def scenario() -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])

        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", lifespan="off")
        )
        server_task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.01)
            assert server.started

            async with websockets.connect(f"ws://127.0.0.1:{port}/ws/host") as host:
                await host.send(
                    json.dumps(
                        {
                            "type": "host:hello",
                            "session_id": "CV-RESET001",
                            "pairing_code": "ABCDEFGH",
                            "host_name": "Regression Host",
                        }
                    )
                )
                assert json.loads(await host.recv())["type"] == "host:registered"

                async with websockets.connect(f"ws://127.0.0.1:{port}/ws/viewer") as viewer:
                    await viewer.send(
                        json.dumps(
                            {
                                "type": "viewer:hello",
                                "session_id": "CV-RESET001",
                                "pairing_code": "ABCDEFGH",
                            }
                        )
                    )
                    assert json.loads(await viewer.recv())["type"] == "viewer:registered"
                    assert json.loads(await viewer.recv())["type"] == "session:state"
                    assert json.loads(await host.recv())["type"] == "viewer:connected"

                    await viewer.send(json.dumps({"type": "control:request"}))
                    assert json.loads(await host.recv())["type"] == "control:request"
                    assert json.loads(await viewer.recv())["type"] == "control:state"
                    await host.send(
                        json.dumps(
                            {
                                "type": "control:decision",
                                "approved": True,
                                "reason": "Approved for reset test.",
                            }
                        )
                    )
                    assert json.loads(await viewer.recv())["allowed"] is True

                    await viewer.send(json.dumps({"type": "input:reset"}))
                    assert json.loads(await host.recv())["type"] == "input:reset"

                assert json.loads(await host.recv())["type"] == "viewer:disconnected"
        finally:
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=3)

    asyncio.run(scenario())
