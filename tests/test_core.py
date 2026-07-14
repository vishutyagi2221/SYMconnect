import asyncio
import re
from contextlib import suppress

from symconnect.agent import HostAgent, PAIRING_ALPHABET, default_pairing_code, default_session_id
from symconnect.desktop_app import Api
from symconnect.server import AUTH_ATTEMPT_LIMIT, AuthAttemptLimiter


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
    api.publish_bootstrap()
    api.set_host_status("ready", "Live session ready")

    events = api.get_events()
    assert len(events) == 2
    assert events[0]["name"] == "symconnectBootstrap"
    assert "CV-A1B2C3D4" in str(events[0]["payload"])
    assert "wss://relay.example" in str(events[0]["payload"])
    assert events[1]["name"] == "symconnectApplyHostStatus"
    assert "Live session ready" in str(events[1]["payload"])


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
