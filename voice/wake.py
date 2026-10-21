"""Optional Porcupine wake-word stub (requires PICOVOICE_ACCESS_KEY + model file)."""
from __future__ import annotations

import os
from typing import Callable, Optional


class WakeWord:
    """Best-effort Porcupine wrapper. Falls back to disabled if SDK/key missing."""

    def __init__(
        self,
        keyword: str = "jarvis",
        on_wake: Optional[Callable[[], None]] = None,
    ) -> None:
        self.keyword = keyword
        self.on_wake = on_wake
        self.enabled = False
        self._err: Optional[str] = None

    def try_enable(self) -> bool:
        key = os.getenv("PICOVOICE_ACCESS_KEY", "")
        if not key:
            self._err = "PICOVOICE_ACCESS_KEY not set"
            return False
        try:
            import pvporcupine  # type: ignore

            self._porcupine = pvporcupine.create(access_key=key, keywords=[self.keyword])
            self.enabled = True
            return True
        except Exception as exc:  # noqa: BLE001
            self._err = str(exc)
            self.enabled = False
            return False

    @property
    def status(self) -> str:
        if self.enabled:
            return f"wake word '{self.keyword}' enabled"
        return f"wake word disabled ({self._err or 'not configured'})"
