from __future__ import annotations

from typing import Any

from pynput import keyboard, mouse


KEY_ALIASES = {
    "Alt": keyboard.Key.alt_l,
    "AltGraph": keyboard.Key.alt_gr,
    "Backspace": keyboard.Key.backspace,
    "CapsLock": keyboard.Key.caps_lock,
    "Control": keyboard.Key.ctrl_l,
    "Delete": keyboard.Key.delete,
    "End": keyboard.Key.end,
    "Enter": keyboard.Key.enter,
    "Escape": keyboard.Key.esc,
    "F1": keyboard.Key.f1,
    "F2": keyboard.Key.f2,
    "F3": keyboard.Key.f3,
    "F4": keyboard.Key.f4,
    "F5": keyboard.Key.f5,
    "F6": keyboard.Key.f6,
    "F7": keyboard.Key.f7,
    "F8": keyboard.Key.f8,
    "F9": keyboard.Key.f9,
    "F10": keyboard.Key.f10,
    "F11": keyboard.Key.f11,
    "F12": keyboard.Key.f12,
    "Home": keyboard.Key.home,
    "Insert": keyboard.Key.insert,
    "Meta": keyboard.Key.cmd,
    "PageDown": keyboard.Key.page_down,
    "PageUp": keyboard.Key.page_up,
    "Shift": keyboard.Key.shift_l,
    "Tab": keyboard.Key.tab,
    "ArrowDown": keyboard.Key.down,
    "ArrowLeft": keyboard.Key.left,
    "ArrowRight": keyboard.Key.right,
    "ArrowUp": keyboard.Key.up,
    " ": keyboard.Key.space,
    "Space": keyboard.Key.space,
}

BUTTON_ALIASES = {
    "left": mouse.Button.left,
    "middle": mouse.Button.middle,
    "right": mouse.Button.right,
}


class InputController:
    def __init__(self, bounds: dict[str, int]) -> None:
        self.bounds = bounds
        self.mouse = mouse.Controller()
        self.keyboard = keyboard.Controller()

    def handle_mouse(self, event: dict[str, Any]) -> None:
        action = event.get("action")
        if action in {"move", "down", "up"}:
            x, y = self._screen_point(event)
            self.mouse.position = (x, y)

        if action == "down":
            self.mouse.press(self._button(event.get("button")))
        elif action == "up":
            self.mouse.release(self._button(event.get("button")))
        elif action == "wheel":
            delta_x = int(event.get("delta_x") or 0)
            delta_y = int(event.get("delta_y") or 0)
            self.mouse.scroll(-delta_x, -delta_y)

    def handle_key(self, event: dict[str, Any]) -> None:
        action = event.get("action")
        key = self._key(event.get("key"))
        if key is None:
            return

        if action == "down":
            self.keyboard.press(key)
        elif action == "up":
            self.keyboard.release(key)
        elif action == "press":
            self.keyboard.press(key)
            self.keyboard.release(key)

    def _screen_point(self, event: dict[str, Any]) -> tuple[int, int]:
        x_pct = clamp_float(event.get("x_pct"))
        y_pct = clamp_float(event.get("y_pct"))
        left = self.bounds["left"]
        top = self.bounds["top"]
        width = self.bounds["width"]
        height = self.bounds["height"]
        return left + int(x_pct * (width - 1)), top + int(y_pct * (height - 1))

    def _button(self, value: Any) -> mouse.Button:
        return BUTTON_ALIASES.get(str(value), mouse.Button.left)

    def _key(self, value: Any) -> keyboard.Key | str | None:
        if not isinstance(value, str):
            return None
        if value in KEY_ALIASES:
            return KEY_ALIASES[value]
        if len(value) == 1:
            return value
        return None


def clamp_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
