from __future__ import annotations

import base64
import threading
import time
from dataclasses import dataclass
from io import BytesIO

import mss
from PIL import Image


@dataclass(frozen=True)
class Frame:
    image: str
    screen_width: int
    screen_height: int
    image_width: int
    image_height: int
    timestamp: float


class ScreenCapture:
    def __init__(self, monitor_index: int = 1, max_width: int = 1366, jpeg_quality: int = 62) -> None:
        self.monitor_index = monitor_index
        self.max_width = max_width
        self.jpeg_quality = jpeg_quality
        self._thread_state = threading.local()
        with mss.mss() as capture:
            if monitor_index >= len(capture.monitors):
                available = len(capture.monitors) - 1
                raise ValueError(f"Monitor {monitor_index} not available. Available monitors: 1-{available}.")
            self.monitor = dict(capture.monitors[monitor_index])

    @property
    def bounds(self) -> dict[str, int]:
        return {
            "left": int(self.monitor["left"]),
            "top": int(self.monitor["top"]),
            "width": int(self.monitor["width"]),
            "height": int(self.monitor["height"]),
        }

    def grab(self) -> Frame:
        capture = getattr(self._thread_state, "capture", None)
        if capture is None:
            capture = mss.mss()
            self._thread_state.capture = capture
        raw = capture.grab(self.monitor)
        image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        screen_width, screen_height = image.size

        if self.max_width > 0 and screen_width > self.max_width:
            ratio = self.max_width / screen_width
            resized_height = max(1, int(screen_height * ratio))
            image = image.resize((self.max_width, resized_height), Image.Resampling.BILINEAR)

        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=self.jpeg_quality, subsampling=2)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

        return Frame(
            image=encoded,
            screen_width=screen_width,
            screen_height=screen_height,
            image_width=image.width,
            image_height=image.height,
            timestamp=time.time(),
        )
