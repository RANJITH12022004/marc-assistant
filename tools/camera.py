"""Windows Camera mode control — photo / video / barcode / record."""
from __future__ import annotations

import time
from typing import Literal, Optional

from tools.os_tools import OSTools, ToolResult

Mode = Literal["photo", "video", "barcode"]

# Assumed cycle order when Tabbing the Windows Camera mode rail.
_MODE_ORDER: tuple[Mode, ...] = ("photo", "video", "barcode")


class CameraTools:
    """Drive Microsoft Windows Camera via open + keyboard (best-effort)."""

    def __init__(self) -> None:
        self._mode: Mode = "photo"

    def _focus(self) -> None:
        try:
            import pyautogui

            # Nudge focus toward the Camera window without requiring pygetwindow
            pyautogui.keyDown("alt")
            pyautogui.press("tab")
            pyautogui.keyUp("alt")
            time.sleep(0.35)
        except Exception:  # noqa: BLE001
            pass

    def _press(self, *keys: str) -> None:
        import pyautogui

        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)

    def _cycle_next(self) -> None:
        """Advance mode rail. Try Ctrl+N (mode), else Tab."""
        try:
            self._press("ctrl", "n")
        except Exception:  # noqa: BLE001
            try:
                self._press("tab")
            except Exception:  # noqa: BLE001
                return
        idx = _MODE_ORDER.index(self._mode)
        self._mode = _MODE_ORDER[(idx + 1) % len(_MODE_ORDER)]
        time.sleep(0.5)

    def set_mode(self, mode: Mode, open_first: bool = True) -> ToolResult:
        mode_l = (mode or "photo").lower()
        if mode_l not in _MODE_ORDER:
            return ToolResult(False, f"Unknown camera mode: {mode}")
        mode = mode_l  # type: ignore[assignment]

        if open_first:
            OSTools().open_app("camera")
            time.sleep(2.2)

        self._focus()
        # Reset tracking assumption, then cycle toward target
        self._mode = "photo"
        for _ in range(len(_MODE_ORDER) + 1):
            if self._mode == mode:
                break
            self._cycle_next()

        label = {"photo": "Photo", "video": "Video", "barcode": "Barcode"}[mode]
        confirmed = self._mode == mode
        msg = (
            f"Camera set to {label} mode."
            if confirmed
            else (
                f"Tried to switch Camera to {label}. "
                f"If it stayed on Photo or Barcode, tap {label} in the app, then say the command again."
            )
        )
        return ToolResult(True, msg, {"mode": mode, "confirmed": confirmed})

    def take_photo(self) -> ToolResult:
        prior = self.set_mode("photo", open_first=True)
        time.sleep(0.6)
        self._focus()
        before = self._newest_camera_file()
        try:
            self._press("space")
            time.sleep(1.2)
            after = self._newest_camera_file()
            path = ""
            if after and (not before or after != before):
                path = after
            elif after:
                path = after
            return ToolResult(
                True,
                "Taking a photo. Press the shutter if it did not click.",
                {"mode": "photo", "prior": prior.message, "path": path},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"Photo capture failed: {exc}")

    @staticmethod
    def _newest_camera_file() -> str:
        """Best-effort: newest image in Camera Roll / Pictures."""
        from pathlib import Path

        home = Path.home()
        roots = [
            home / "Pictures" / "Camera Roll",
            home / "OneDrive" / "Pictures" / "Camera Roll",
            home / "Pictures",
        ]
        newest = None
        newest_mtime = 0.0
        for root in roots:
            if not root.is_dir():
                continue
            try:
                for p in root.rglob("*"):
                    if not p.is_file():
                        continue
                    if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".heic", ".jxl"):
                        continue
                    try:
                        m = p.stat().st_mtime
                    except OSError:
                        continue
                    if m > newest_mtime:
                        newest_mtime = m
                        newest = p
            except Exception:  # noqa: BLE001
                continue
        return str(newest) if newest else ""

    def open_last_photo(self, path: str = "") -> ToolResult:
        from pathlib import Path

        p = (path or "").strip()
        if not p:
            p = self._newest_camera_file()
        if p and Path(p).exists():
            try:
                OSTools().file_open(p)
                return ToolResult(True, f"Opened {Path(p).name}.", {"path": p})
            except Exception as exc:  # noqa: BLE001
                return ToolResult(False, f"Could not open photo: {exc}", {"path": p})
        # Fallback: open Photos app
        return OSTools().open_app("photos")

    def start_recording(self) -> ToolResult:
        # Always force Video before record — never stay on barcode/photo
        prior = self.set_mode("video", open_first=True)
        time.sleep(0.9)
        self._focus()
        try:
            self._press("space")
            return ToolResult(
                True,
                "Video mode — starting recording. Tap Record if it did not start.",
                {"mode": "video", "prior": prior.message},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"Record failed: {exc}")

    def stop_recording(self) -> ToolResult:
        self._focus()
        try:
            self._press("space")
            return ToolResult(True, "Stopped recording (toggled capture).")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"Stop failed: {exc}")


_CAMERA: Optional[CameraTools] = None


def get_camera() -> CameraTools:
    global _CAMERA
    if _CAMERA is None:
        _CAMERA = CameraTools()
    return _CAMERA
