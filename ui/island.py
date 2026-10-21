"""Top-center Dynamic Island for Marc (PySide6 with tkinter fallback)."""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Callable, Optional

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")


class DynamicIsland:
    """Always-on-top pill at top-center of the primary screen."""

    def __init__(self) -> None:
        self.state = "wake"
        self.subtitle = ""
        self._on_click: Optional[Callable[[], None]] = None
        self._on_quit: Optional[Callable[[], None]] = None
        self._on_mic: Optional[Callable[[], None]] = None
        self._impl = None
        self._bridge = None  # Qt signal bridge (thread-safe updates)
        self._lock = threading.Lock()
        self._shutdown = threading.Event()
        self._qt_ready = threading.Event()
        self._last_click = 0.0

    def set_click_handler(self, fn: Callable[[], None]) -> None:
        self._on_click = fn

    def _fire_click(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_click < 0.35:
                return
            self._last_click = now
        if self._on_click:
            self._on_click()

    def set_quit_handler(self, fn: Callable[[], None]) -> None:
        self._on_quit = fn

    def set_mic_handler(self, fn: Callable[[], None]) -> None:
        self._on_mic = fn

    def shutdown(self) -> None:
        self._shutdown.set()
        if self._impl is not None:
            try:
                self._impl.request_close()
            except Exception:  # noqa: BLE001
                pass

    def set(self, state: str, subtitle: str = "") -> None:
        with self._lock:
            self.state = state
            if subtitle:
                self.subtitle = subtitle[:48]
            print(f"[marc] island → {state}" + (f" | {self.subtitle}" if subtitle else ""))
            bridge = self._bridge
            impl = self._impl
            sub = self.subtitle
        # Marshal onto Qt thread via signal when available
        if bridge is not None:
            try:
                bridge.state_changed.emit(state, sub)
                return
            except Exception:  # noqa: BLE001
                pass
        if impl is not None:
            try:
                # tk path: schedule on mainloop if possible
                if hasattr(impl, "schedule_update"):
                    impl.schedule_update(state, sub)
                else:
                    impl.update_state(state, sub)
            except Exception:  # noqa: BLE001
                pass

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True, name="marc-island")
        t.start()
        # Wait briefly for Qt/tk to bind impl
        self._qt_ready.wait(timeout=2.0)
        time.sleep(0.15)

    def _run(self) -> None:
        try:
            self._run_pyside()
        except Exception as exc:  # noqa: BLE001
            print(f"[marc] PySide6 island unavailable ({exc}); using tkinter")
            self._bridge = None
            self._run_tk()
        # If Qt event loop ended unexpectedly (not shutdown), fall back to tk
        if not self._shutdown.is_set():
            print("[marc] Island Qt loop ended; restarting with tkinter", flush=True)
            self._bridge = None
            self._impl = None
            try:
                self._run_tk()
            except Exception as exc:  # noqa: BLE001
                print(f"[marc] Island tk fallback failed: {exc}", flush=True)

    def _run_pyside(self) -> None:
        from PySide6.QtCore import QObject, QTimer, Qt, QRectF, Signal, Slot
        from PySide6.QtGui import QColor, QPainter, QPainterPath, QBrush, QPen, QFont
        from PySide6.QtWidgets import QApplication, QWidget

        island_ref = self

        class IslandBridge(QObject):
            state_changed = Signal(str, str)

        class IslandWidget(QWidget):
            def __init__(self, island: "DynamicIsland", bridge: IslandBridge):
                super().__init__()
                self.island = island
                self._phase = 0.0
                self._state = "wake"
                self._subtitle = ""
                self.setWindowFlags(
                    Qt.FramelessWindowHint
                    | Qt.WindowStaysOnTopHint
                    | Qt.Tool
                    | Qt.WindowDoesNotAcceptFocus
                )
                self.setAttribute(Qt.WA_TranslucentBackground, True)
                self.setAttribute(Qt.WA_ShowWithoutActivating, True)
                self._place()
                bridge.state_changed.connect(self._on_state)
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._tick)
                self._timer.start(33)

            @Slot(str, str)
            def _on_state(self, state: str, subtitle: str) -> None:
                self.update_state(state, subtitle)

            def _place(self) -> None:
                screen = QApplication.primaryScreen().availableGeometry()
                w, h = 320, 48
                x = screen.x() + (screen.width() - w) // 2
                y = screen.y() + 8
                self.setGeometry(x, y, w, h)

            def update_state(self, state: str, subtitle: str) -> None:
                self._state = state
                self._subtitle = subtitle
                screen = QApplication.primaryScreen().availableGeometry()
                active = state in (
                    "listening",
                    "thinking",
                    "acting",
                    "speaking",
                    "followup",
                )
                w, h = (360, 56) if active else (300, 44)
                x = screen.x() + (screen.width() - w) // 2
                y = screen.y() + 8
                self.setGeometry(x, y, w, h)
                self.update()

            def request_close(self) -> None:
                QApplication.instance().quit()

            def _tick(self) -> None:
                self._phase += 0.18
                if island_ref._shutdown.is_set():
                    QApplication.instance().quit()
                    return
                self.update()

            def mousePressEvent(self, event) -> None:  # noqa: N802
                w = self.width()
                x = event.position().x() if hasattr(event, "position") else event.x()
                if x >= w - 36:
                    if self.island._on_quit:
                        self.island._on_quit()
                    return
                if self.island._on_click:
                    self.island._fire_click()

            def paintEvent(self, event) -> None:  # noqa: N802
                p = QPainter(self)
                p.setRenderHint(QPainter.Antialiasing)
                rect = self.rect().adjusted(2, 2, -2, -2)
                path = QPainterPath()
                path.addRoundedRect(QRectF(rect), rect.height() / 2, rect.height() / 2)

                colors = {
                    "sleeping": QColor(20, 20, 24, 200),
                    "wake": QColor(28, 28, 36, 210),
                    "listening": QColor(18, 80, 120, 230),
                    "followup": QColor(18, 100, 90, 230),
                    "thinking": QColor(60, 40, 100, 230),
                    "acting": QColor(20, 90, 60, 230),
                    "speaking": QColor(90, 50, 20, 230),
                    "idle": QColor(20, 20, 24, 200),
                }
                bg = colors.get(self._state, colors["wake"])
                p.fillPath(path, QBrush(bg))

                if self._state in ("listening", "followup"):
                    pulse = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._phase))
                    pen = QPen(QColor(120, 200, 255, int(180 * pulse)), 2)
                    p.setPen(pen)
                    p.drawPath(path)

                p.setPen(QColor(220, 120, 120))
                font_x = QFont("Segoe UI", 11, QFont.Bold)
                p.setFont(font_x)
                p.drawText(rect.adjusted(0, 0, -12, 0), Qt.AlignRight | Qt.AlignVCenter, "✕")

                cx, cy = rect.center().x(), rect.center().y() - (6 if self._subtitle else 0)
                bar_color = QColor(230, 240, 255, 220)
                p.setBrush(QBrush(bar_color))
                p.setPen(Qt.NoPen)
                n = 7
                for i in range(n):
                    if self._state in ("listening", "speaking", "followup"):
                        h = 4 + 10 * abs(math.sin(self._phase + i * 0.7))
                    elif self._state == "thinking":
                        h = 4 + 6 * abs(math.sin(self._phase * 0.5 + i))
                    elif self._state == "acting":
                        h = 6 + (i % 3) * 2
                    else:
                        h = 3
                    bw = 3
                    x = cx - (n * 6) / 2 + i * 6
                    p.drawRoundedRect(QRectF(x, cy - h / 2, bw, h), 1, 1)

                p.setPen(QColor(240, 245, 255))
                font = QFont("Segoe UI", 8, QFont.Bold)
                p.setFont(font)
                label = {
                    "sleeping": "SLEEP",
                    "wake": "WAKE",
                    "listening": "LISTEN",
                    "followup": "FOLLOW-UP",
                    "thinking": "THINK",
                    "acting": "ACT",
                    "speaking": "SPEAK",
                    "idle": "WAKE",
                }.get(self._state, "MARC")
                p.drawText(rect.adjusted(14, 2, -40, -2), Qt.AlignLeft | Qt.AlignVCenter, label)

                if self._subtitle:
                    font2 = QFont("Segoe UI", 7)
                    p.setFont(font2)
                    p.setPen(QColor(200, 210, 230, 200))
                    p.drawText(
                        rect.adjusted(14, 0, -40, -4),
                        Qt.AlignRight | Qt.AlignBottom,
                        self._subtitle,
                    )

        app = QApplication.instance() or QApplication([])
        bridge = IslandBridge()
        w = IslandWidget(self, bridge)
        self._bridge = bridge
        self._impl = w
        self._qt_ready.set()
        w.show()
        w.update_state(self.state, self.subtitle)
        app.exec()
        # Clear Qt refs when loop ends
        self._bridge = None
        self._impl = None

    def _run_tk(self) -> None:
        import tkinter as tk

        root = tk.Tk()
        root.title("Marc")
        root.attributes("-topmost", True)
        root.overrideredirect(True)
        try:
            root.attributes("-alpha", 0.92)
        except Exception:  # noqa: BLE001
            pass

        sw = root.winfo_screenwidth()
        w, h = 320, 48
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+8")

        canvas = tk.Canvas(root, width=w, height=h, highlightthickness=0, bg="#1c1c24")
        canvas.pack(fill="both", expand=True)

        class TkImpl:
            def __init__(self):
                self.phase = 0.0
                self._pending = None

            def schedule_update(self, state: str, subtitle: str) -> None:
                self._pending = (state, subtitle)
                try:
                    root.after(0, lambda: self.update_state(state, subtitle))
                except Exception:  # noqa: BLE001
                    self.update_state(state, subtitle)

            def update_state(self, state: str, subtitle: str) -> None:
                colors = {
                    "sleeping": "#141418",
                    "wake": "#1c1c24",
                    "listening": "#125078",
                    "followup": "#12645a",
                    "thinking": "#3c2864",
                    "acting": "#145a3c",
                    "speaking": "#5a3214",
                    "idle": "#1c1c24",
                }
                canvas.configure(bg=colors.get(state, "#1c1c24"))
                canvas.delete("all")
                label = {
                    "sleeping": "SLEEP",
                    "wake": "WAKE",
                    "listening": "LISTEN",
                    "followup": "FOLLOW-UP",
                    "thinking": "THINK",
                    "acting": "ACT",
                    "speaking": "SPEAK",
                    "idle": "WAKE",
                }.get(state, "MARC")
                canvas.create_text(14, h // 2, anchor="w", fill="#e8eefc", text=label, font=("Segoe UI", 9, "bold"))
                canvas.create_text(w - 14, h // 2, anchor="e", fill="#dc7878", text="✕", font=("Segoe UI", 12, "bold"))
                if subtitle:
                    canvas.create_text(w - 40, h - 8, anchor="se", fill="#a8b4cc", text=subtitle, font=("Segoe UI", 7))
                cx = w // 2
                for i in range(7):
                    bh = 4 + (i % 3) * 3
                    if state in ("listening", "speaking", "followup"):
                        bh = 4 + int(8 * abs(math.sin(self.phase + i)))
                    canvas.create_rectangle(
                        cx - 20 + i * 6,
                        h // 2 - bh // 2,
                        cx - 17 + i * 6,
                        h // 2 + bh // 2,
                        fill="#dce6ff",
                        outline="",
                    )

            def request_close(self) -> None:
                try:
                    root.quit()
                    root.destroy()
                except Exception:  # noqa: BLE001
                    pass

        impl = TkImpl()
        self._impl = impl
        self._qt_ready.set()

        def tick():
            if self._shutdown.is_set():
                try:
                    root.quit()
                except Exception:  # noqa: BLE001
                    pass
                return
            impl.phase += 0.2
            impl.update_state(self.state, self.subtitle)
            root.after(50, tick)

        def on_click(event):
            if event.x >= w - 36:
                if self._on_quit:
                    self._on_quit()
                return
            if self._on_click:
                self._fire_click()

        canvas.bind("<Button-1>", on_click)
        root.after(50, tick)
        root.mainloop()
