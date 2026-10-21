"""Minimal tray status for Marc (Edith-style state)."""
from __future__ import annotations

import threading
from typing import Optional

# States: idle | listening | thinking | acting | confirm


class TrayStatus:
    def __init__(self) -> None:
        self.state = "idle"
        self._lock = threading.Lock()
        self._root = None
        self._label = None

    def set(self, state: str) -> None:
        with self._lock:
            self.state = state
            print(f"[marc] status → {state}")
            if self._label is not None:
                try:
                    self._label.config(text=f"Marc: {state}")
                except Exception:  # noqa: BLE001
                    pass

    def run_tk_badge(self) -> None:
        """Small always-on-top status window (no full tray dependency)."""
        import tkinter as tk

        root = tk.Tk()
        root.title("Marc")
        root.attributes("-topmost", True)
        root.geometry("180x40+20+20")
        root.resizable(False, False)
        label = tk.Label(root, text="Marc: idle", font=("Segoe UI", 11))
        label.pack(expand=True, fill="both")
        self._root = root
        self._label = label

        def _tick():
            with self._lock:
                label.config(text=f"Marc: {self.state}")
            root.after(200, _tick)

        root.after(200, _tick)
        root.mainloop()

    def start_background(self) -> None:
        t = threading.Thread(target=self.run_tk_badge, daemon=True)
        t.start()
