"""Push-to-talk listener using the `keyboard` package."""
from __future__ import annotations

import threading
from typing import Callable, Optional

from settings import settings


class PushToTalk:
    def __init__(self, hotkey: Optional[str] = None, on_trigger: Optional[Callable[[], None]] = None) -> None:
        self.hotkey = (hotkey or settings.ptt_hotkey).replace("ctrl+shift+m", "ctrl+shift+m")
        self.on_trigger = on_trigger
        self._stop = threading.Event()

    def start(self) -> None:
        import keyboard

        print(f"[marc] push-to-talk armed on {self.hotkey}")
        keyboard.add_hotkey(self.hotkey, self._fire)

    def _fire(self) -> None:
        if self.on_trigger:
            threading.Thread(target=self.on_trigger, daemon=True).start()

    def wait(self) -> None:
        self._stop.wait()

    def stop(self) -> None:
        self._stop.set()
        try:
            import keyboard

            keyboard.unhook_all_hotkeys()
        except Exception:  # noqa: BLE001
            pass
