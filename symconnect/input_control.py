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
    "F13": keyboard.Key.f13,
    "F14": keyboard.Key.f14,
    "F15": keyboard.Key.f15,
    "F16": keyboard.Key.f16,
    "F17": keyboard.Key.f17,
    "F18": keyboard.Key.f18,
    "F19": keyboard.Key.f19,
    "F20": keyboard.Key.f20,
    "F21": keyboard.Key.f21,
    "F22": keyboard.Key.f22,
    "F23": keyboard.Key.f23,
    "F24": keyboard.Key.f24,
    "Home": keyboard.Key.home,
    "Insert": keyboard.Key.insert,
    "ContextMenu": keyboard.Key.menu,
    "NumLock": keyboard.Key.num_lock,
    "Pause": keyboard.Key.pause,
    "PrintScreen": keyboard.Key.print_screen,
    "ScrollLock": keyboard.Key.scroll_lock,
    "AudioVolumeDown": keyboard.Key.media_volume_down,
    "AudioVolumeMute": keyboard.Key.media_volume_mute,
    "AudioVolumeUp": keyboard.Key.media_volume_up,
    "MediaPlayPause": keyboard.Key.media_play_pause,
    "MediaStop": keyboard.Key.media_stop,
    "MediaTrackNext": keyboard.Key.media_next,
    "MediaTrackPrevious": keyboard.Key.media_previous,
    "Meta": keyboard.Key.cmd_l,
    "OS": keyboard.Key.cmd_l,
    "Super": keyboard.Key.cmd_l,
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

CODE_ALIASES = {
    "AltLeft": keyboard.Key.alt_l,
    "AltRight": keyboard.Key.alt_r,
    "ControlLeft": keyboard.Key.ctrl_l,
    "ControlRight": keyboard.Key.ctrl_r,
    "MetaLeft": keyboard.Key.cmd_l,
    "MetaRight": keyboard.Key.cmd_r,
    "ShiftLeft": keyboard.Key.shift_l,
    "ShiftRight": keyboard.Key.shift_r,
}

BUTTON_ALIASES = {
    "left": mouse.Button.left,
    "middle": mouse.Button.middle,
    "right": mouse.Button.right,
}


class InputController:
    def __init__(
        self,
        bounds: dict[str, int],
        *,
        mouse_controller: Any | None = None,
        keyboard_controller: Any | None = None,
    ) -> None:
        self.bounds = bounds
        self.mouse = mouse_controller if mouse_controller is not None else mouse.Controller()
        self.keyboard = keyboard_controller if keyboard_controller is not None else keyboard.Controller()
        self._pressed_buttons: set[mouse.Button] = set()
        self._pressed_keys: dict[str, keyboard.Key | str] = {}

    def handle_mouse(self, event: dict[str, Any]) -> None:
        action = event.get("action")
        if action in {"move", "down", "up"}:
            x, y = self._screen_point(event)
            self.mouse.position = (x, y)

        if action == "down":
            button = self._button(event.get("button"))
            if button not in self._pressed_buttons:
                self.mouse.press(button)
                self._pressed_buttons.add(button)
        elif action == "up":
            button = self._button(event.get("button"))
            self.mouse.release(button)
            self._pressed_buttons.discard(button)
        elif action == "wheel":
            delta_x = int(event.get("delta_x") or 0)
            delta_y = int(event.get("delta_y") or 0)
            self.mouse.scroll(-delta_x, -delta_y)

    def handle_key(self, event: dict[str, Any]) -> None:
        action = event.get("action")
        token = self._key_token(event)
        key = self._key(event.get("key"), event.get("code"))
        tracked_key = self._pressed_keys.get(token)
        if key is None and tracked_key is None:
            return

        if action == "down":
            if token in self._pressed_keys:
                return
            assert key is not None
            self.keyboard.press(key)
            self._pressed_keys[token] = key
        elif action == "up":
            released_key = self._pressed_keys.pop(token, key)
            if released_key is not None:
                self.keyboard.release(released_key)
        elif action == "press":
            assert key is not None
            self.keyboard.press(key)
            self.keyboard.release(key)

    def release_all(self) -> None:
        """Release every injected input after focus, control, or connection loss."""
        for key in reversed(tuple(self._pressed_keys.values())):
            try:
                self.keyboard.release(key)
            except Exception:
                pass
        self._pressed_keys.clear()

        for button in tuple(self._pressed_buttons):
            try:
                self.mouse.release(button)
            except Exception:
                pass
        self._pressed_buttons.clear()

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

    def _key(self, value: Any, code: Any = None) -> keyboard.Key | str | None:
        if isinstance(code, str) and code in CODE_ALIASES:
            return CODE_ALIASES[code]
        if not isinstance(value, str):
            return None
        if value in KEY_ALIASES:
            return KEY_ALIASES[value]
        if len(value) == 1:
            return value
        return None

    @staticmethod
    def _key_token(event: dict[str, Any]) -> str:
        code = event.get("code")
        if isinstance(code, str) and code:
            return f"code:{code}"
        value = event.get("key")
        if isinstance(value, str) and len(value) == 1:
            value = value.lower()
        return f"key:{value}"


def clamp_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
