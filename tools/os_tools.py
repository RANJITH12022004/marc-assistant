"""Allowlisted Windows OS tools for Marc."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from settings import settings

pyautogui = None  # type: ignore


def _gui():
    """Lazy-load pyautogui so installing it does not require a worker restart forever."""
    global pyautogui
    if pyautogui is not None:
        return pyautogui
    try:
        import pyautogui as _pg

        _pg.FAILSAFE = False  # corner mouse must not kill Marc mid-command
        _pg.PAUSE = 0.01
        pyautogui = _pg
        return pyautogui
    except Exception:  # noqa: BLE001
        return None


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class ToolResult:
    def __init__(self, ok: bool, message: str, data: Optional[dict] = None, needs_confirm: bool = False):
        self.ok = ok
        self.message = message
        self.data = data or {}
        self.needs_confirm = needs_confirm

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "message": self.message,
            "data": self.data,
            "needs_confirm": self.needs_confirm,
        }


class OSTools:
    def __init__(self) -> None:
        self.apps = _load_json(settings.apps_config)
        self.hotkeys = _load_json(settings.hotkeys_config)
        self._alias_index = self._build_alias_index()
        # Last opened/focused app — used so type_text works for every application.
        self._last_app: str = ""
        self._last_pids: set[int] = set()

    def _build_alias_index(self) -> Dict[str, str]:
        idx: Dict[str, str] = {}
        for name, meta in self.apps.items():
            idx[name.lower()] = name
            for alias in meta.get("aliases", []):
                idx[alias.lower()] = name
        return idx

    def resolve_app(self, name: str) -> Tuple[Optional[str], Optional[dict]]:
        try:
            from laya_router.synonyms import expand_app_query

            name = expand_app_query(name)
        except Exception:  # noqa: BLE001
            pass
        key = name.strip().lower()
        if not key:
            return None, None
        # Exact key / alias
        if key in self._alias_index:
            canon = self._alias_index[key]
            return canon, self.apps[canon]
        # Whole-token match (avoid "wa" ⊂ "water")
        tokens = set(re.findall(r"[a-z0-9]+", key))
        for alias, canon in self._alias_index.items():
            if len(alias) < 3:
                # Short aliases: exact token only
                if alias in tokens:
                    return canon, self.apps[canon]
                continue
            alias_tokens = set(re.findall(r"[a-z0-9]+", alias))
            if alias_tokens and alias_tokens <= tokens:
                return canon, self.apps[canon]
            # Longer alias contained as whole phrase with word boundaries
            if re.search(rf"\b{re.escape(alias)}\b", key):
                return canon, self.apps[canon]
        return None, None

    def suggest_app(self, name: str) -> Optional[str]:
        key = name.strip().lower()
        for alias, canon in self._alias_index.items():
            if key and (key in alias or alias in key):
                return canon
        # common fallbacks
        if "chrome" in key or "google" in key:
            return "chrome"
        if "edge" in key:
            return "edge"
        if "code" in key or "cursor" in key:
            return "cursor" if "cursor" in key else "vscode"
        return None

    def open_app(self, name: str) -> ToolResult:
        raw = (name or "").strip()
        name = re.sub(r"^(?:the|my|a|an|this|current)\s+", "", raw, flags=re.I).strip() or raw
        canon, meta = self.resolve_app(name)
        if not meta:
            suggestion = self.suggest_app(name)
            if suggestion:
                return ToolResult(
                    False,
                    f"I don't know '{name}'. Did you mean {suggestion}?",
                    {"suggestion": suggestion},
                    needs_confirm=True,
                )
            return ToolResult(
                False,
                f"Unknown app '{name}'. Say open settings or add it to config/apps.json.",
                {"app": name},
            )

        launched = False
        launch_pid: Optional[int] = None
        before_pids = self._snapshot_pids()
        # Prefer local install / shell protocol; fall back to URL apps
        for cmd in meta.get("commands", []):
            if cmd.startswith("ms-settings:"):
                os.startfile(cmd)  # noqa: S606
                launched = True
                break
            # Allow simple wildcards in WindowsApps paths
            if "*" in cmd:
                import glob

                matches = glob.glob(os.path.expandvars(cmd))
                if matches:
                    proc = subprocess.Popen([matches[0]], shell=False)  # noqa: S603
                    launch_pid = proc.pid
                    launched = True
                    break
                continue
            path = Path(os.path.expandvars(cmd))
            if path.exists():
                proc = subprocess.Popen([str(path)], shell=False)  # noqa: S603
                launch_pid = proc.pid
                launched = True
                break

        if not launched:
            shell = meta.get("shell")
            if shell:
                try:
                    if shell.startswith("start "):
                        os.system(shell)  # noqa: S605
                    else:
                        proc = subprocess.Popen(shell, shell=True)  # noqa: S602
                        launch_pid = proc.pid
                    launched = True
                except Exception as exc:  # noqa: BLE001
                    # Fall through to URL if present
                    if not meta.get("url"):
                        return ToolResult(False, f"Failed to open {canon}: {exc}")

        if not launched:
            url = meta.get("url")
            if url:
                webbrowser.open(url)
                launched = True

        if not launched:
            return ToolResult(False, f"Could not find executable for {canon}.")

        # Remember this launch so later type_text focuses the right app (any application).
        time.sleep(0.25)
        new_pids = self._snapshot_pids() - before_pids
        if launch_pid:
            new_pids.add(launch_pid)
        self._remember_launch(canon, new_pids)

        # Critical: steal focus onto the app we just opened before any type_text.
        focused = self._await_focus(canon, timeout=2.8, pids=self._last_pids)
        return ToolResult(
            True,
            f"Opened {canon}.",
            {"app": canon, "focused": bool(focused), "pids": sorted(self._last_pids)[:8]},
        )

    def open_url(self, url: str) -> ToolResult:
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return ToolResult(False, "Only http/https URLs are allowed.")
        webbrowser.open(url)
        return ToolResult(True, f"Opened {url}")

    def web_search(self, query: str, engine: str = "google") -> ToolResult:
        q = query.strip()
        if not q:
            return ToolResult(False, "Empty search query.")
        engine = (engine or "google").lower()
        if engine in ("youtube", "yt"):
            url = f"https://www.youtube.com/results?search_query={quote_plus(q)}"
        elif engine in ("bing",):
            url = f"https://www.bing.com/search?q={quote_plus(q)}"
        else:
            url = f"https://www.google.com/search?q={quote_plus(q)}"
        webbrowser.open(url)
        return ToolResult(True, f"Searching {engine} for {q}.", {"url": url})

    def type_text(self, text: str, confirmed: bool = False, app: str = "") -> ToolResult:
        if not confirmed:
            return ToolResult(
                False,
                f"Type into the focused window: “{text[:80]}”? Confirm to proceed.",
                {"text": text, "app": app or ""},
                needs_confirm=True,
            )
        if _gui() is None:
            return ToolResult(False, "pyautogui not available.")
        text = text or ""
        if not text.strip():
            return ToolResult(False, "Nothing to type.")
        # Strip trailing send/enter cues (handled by followup, but harden here)
        send_after = False
        m = re.search(
            r"[\s,]+(?:and\s+)?(?:then\s+)?(?:send(?:\s+it)?|hit\s+enter|press\s+enter|enter)\s*$",
            text,
            re.I,
        )
        if m:
            text = text[: m.start()].rstrip(" .,")
            send_after = True
        if not text.strip():
            if send_after:
                return self.hotkey("enter", confirmed=True)
            return ToolResult(False, "Nothing to type.")

        target = (app or self._last_app or "").strip()
        focused = False
        if target:
            pids = self._last_pids if self._same_app(target, self._last_app) else set()
            focused = self._await_focus(target, timeout=2.5, pids=pids)
            if not focused:
                return ToolResult(
                    False,
                    f"I couldn't focus {target} to type into it.",
                    {"app": target},
                )
            self._remember_launch(target, pids or self._last_pids)
            time.sleep(0.18)

        method = self._insert_text(text)
        if send_after:
            time.sleep(0.12)
            self.hotkey("enter", confirmed=True)
        where = target or "focused window"
        return ToolResult(
            True,
            f"Typed text into {where}.",
            {"chars": len(text), "method": method, "sent": send_after, "app": target, "focused": focused},
        )

    def _insert_text(self, text: str) -> str:
        """Insert text into focused field. Prefer keystrokes for ASCII (reliable);
        clipboard paste for unicode — with settle delays so paste isn't empty."""
        # ASCII / simple Latin: typewrite is what worked before clipboard broke WhatsApp/etc.
        if text.isascii() and all(32 <= ord(c) <= 126 or c in "\n\t" for c in text):
            time.sleep(0.08)
            prev = getattr(pyautogui, "PAUSE", 0.01)
            try:
                pyautogui.PAUSE = 0
                # Newlines via enter; tabs via tab
                buf: list[str] = []
                for ch in text:
                    if ch == "\n":
                        if buf:
                            pyautogui.typewrite("".join(buf), interval=0.008)
                            buf.clear()
                        pyautogui.press("enter")
                    elif ch == "\t":
                        if buf:
                            pyautogui.typewrite("".join(buf), interval=0.008)
                            buf.clear()
                        pyautogui.press("tab")
                    else:
                        buf.append(ch)
                if buf:
                    pyautogui.typewrite("".join(buf), interval=0.008)
            finally:
                pyautogui.PAUSE = prev
            return "typewrite"

        self._paste_via_clipboard(text)
        return "clipboard"

    def _paste_via_clipboard(self, text: str) -> None:
        """Ctrl+V paste with enough settle time (restoring clipboard too soon caused empty pastes)."""
        import pyperclip

        old = None
        try:
            old = pyperclip.paste()
        except Exception:  # noqa: BLE001
            pass
        # Set clipboard and verify (Windows clipboard can lag)
        for _ in range(3):
            try:
                pyperclip.copy(text)
                time.sleep(0.12)
                if pyperclip.paste() == text:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        if _gui():
            prev = getattr(pyautogui, "PAUSE", 0.01)
            try:
                pyautogui.PAUSE = 0
                time.sleep(0.05)
                pyautogui.hotkey("ctrl", "v")
                # Target app must read clipboard BEFORE we restore
                time.sleep(0.35)
            finally:
                pyautogui.PAUSE = prev
        if old is not None:
            try:
                pyperclip.copy(old)
            except Exception:  # noqa: BLE001
                pass

    def _type_unicode(self, text: str) -> None:
        self._paste_via_clipboard(text)

    def click_then_type(self, text: str, delay: float = 3.0, confirmed: bool = True) -> ToolResult:
        """Countdown then type into whatever the user clicked/focused."""
        if _gui() is None:
            return ToolResult(False, "pyautogui not available.")
        delay = max(0.5, float(delay or 3.0))
        print(f"[marc] Click where to type — typing in {delay:.0f}s…", flush=True)
        time.sleep(delay)
        self._insert_text(text or "")
        return ToolResult(True, f"Typed after click countdown: {(text or '')[:60]}")

    def whatsapp_send(
        self,
        contact: str,
        message: str = "",
        from_clipboard: bool = False,
        confirmed: bool = False,
    ) -> ToolResult:
        """Open WhatsApp Desktop, find contact, type/paste message; Enter only if confirmed."""
        contact = (contact or "").strip()
        if not contact:
            return ToolResult(False, "Who should I message on WhatsApp?")

        body = (message or "").strip()
        if from_clipboard or not body:
            try:
                import pyperclip

                body = (pyperclip.paste() or "").strip()
            except Exception:  # noqa: BLE001
                clip = self.clipboard("read")
                body = (clip.data.get("text") or "").strip() if clip.ok else ""
        if not body:
            return ToolResult(False, "No message text (clipboard empty).")

        preview = body if len(body) <= 80 else body[:77] + "…"
        if not confirmed:
            return ToolResult(
                False,
                f"Send WhatsApp to {contact}: “{preview}”? Confirm to proceed.",
                {
                    "contact": contact,
                    "message": body,
                    "from_clipboard": from_clipboard,
                },
                needs_confirm=True,
            )

        if _gui() is None:
            return ToolResult(False, "pyautogui not available.")

        opened = self.open_app("whatsapp")
        time.sleep(1.6)
        # Focus search (WhatsApp Desktop: Ctrl+F)
        try:
            pyautogui.hotkey("ctrl", "f")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.35)
        self._insert_text(contact)
        time.sleep(0.55)
        pyautogui.press("enter")
        time.sleep(0.55)
        # Type or paste message
        if from_clipboard:
            time.sleep(0.1)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.25)
        else:
            self._insert_text(body)
        time.sleep(0.25)
        pyautogui.press("enter")
        return ToolResult(
            True,
            f"Sent WhatsApp to {contact}.",
            {"contact": contact, "opened": opened.ok},
        )

    def hotkey(self, action: str, confirmed: bool = False) -> ToolResult:
        action = (action or "").strip().lower()
        # STT near-misses
        if action in ("entertainment", "inter", "ender"):
            action = "enter"
        if action in ("open the existing tab", "existing tab", "reopen tab"):
            action = "reopen closed tab" if "reopen closed tab" in self.hotkeys else "new tab"
        keys = self.hotkeys.get(action)
        if not keys:
            # allow "ctrl+c" style
            if "+" in action:
                keys = [k.strip() for k in action.split("+")]
            else:
                return ToolResult(
                    False,
                    f"I don't know the shortcut '{action}'. Try copy, paste, enter, or screenshot.",
                    {"action": action},
                )
        risky = {"lock", "close tab", "task manager"}
        if action in risky and not confirmed:
            return ToolResult(
                False,
                f"Press {action} ({'+'.join(keys)})? Confirm to proceed.",
                {"action": action, "keys": keys},
                needs_confirm=True,
            )
        if _gui() is None:
            return ToolResult(False, "pyautogui not available.")
        prev = getattr(pyautogui, "PAUSE", 0.01)
        try:
            pyautogui.PAUSE = 0
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys)
        finally:
            pyautogui.PAUSE = prev
        return ToolResult(True, f"Pressed {'+'.join(keys)}.")

    def find_files(self, query: str, limit: int = 10) -> ToolResult:
        q = query.strip().lower()
        if not q:
            return ToolResult(False, "Empty file query.")
        hits: List[str] = []
        for root in settings.file_roots:
            if not root.exists():
                continue
            try:
                for p in root.rglob("*"):
                    if p.is_file() and q in p.name.lower():
                        hits.append(str(p))
                        if len(hits) >= limit:
                            break
            except PermissionError:
                continue
            if len(hits) >= limit:
                break
        if not hits:
            return ToolResult(False, f"No files matching '{query}' in allowed folders.")
        return ToolResult(True, f"Found {len(hits)} file(s).", {"files": hits})

    def file_open(self, path: str) -> ToolResult:
        p = Path(path)
        allowed = False
        for root in settings.file_roots:
            try:
                p.resolve().relative_to(root.resolve())
                allowed = True
                break
            except ValueError:
                continue
        if not allowed:
            return ToolResult(False, "Path outside allowed folders (Desktop/Downloads/Documents).")
        if not p.exists():
            return ToolResult(False, f"File not found: {path}")
        os.startfile(str(p))  # noqa: S606
        return ToolResult(True, f"Opened {p.name}.")

    def system_status(self, metric: str = "time") -> ToolResult:
        metric = (metric or "time").lower()
        if metric in ("time", "date"):
            now = datetime.now()
            msg = now.strftime("It's %I:%M %p on %A, %B %d.")
            return ToolResult(True, msg, {"iso": now.isoformat()})
        if metric == "battery":
            try:
                import psutil

                bat = psutil.sensors_battery()
                if bat is None:
                    return ToolResult(True, "No battery detected (desktop?).")
                plugged = "plugged in" if bat.power_plugged else "on battery"
                return ToolResult(True, f"Battery at {bat.percent}% ({plugged}).")
            except Exception as exc:  # noqa: BLE001
                return ToolResult(False, f"Battery unavailable: {exc}")
        if metric == "volume":
            return ToolResult(True, "Use volume commands to change level; current OS volume APIs vary.")
        return ToolResult(False, f"Unknown metric '{metric}'.")

    def volume_media(self, action: str, level: Optional[int] = None) -> ToolResult:
        if _gui() is None:
            return ToolResult(False, "pyautogui not available.")
        action = (action or "").lower()
        # VK codes via pyautogui press names
        mapping = {
            "mute": "volumemute",
            "unmute": "volumemute",
            "play": "playpause",
            "pause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
        }
        if action in mapping:
            # Instant media key — no focus hunt (Windows routes to active media session)
            prev = getattr(pyautogui, "PAUSE", 0.01)
            try:
                pyautogui.PAUSE = 0
                pyautogui.press(mapping[action])
            finally:
                pyautogui.PAUSE = prev
            return ToolResult(True, f"Media action: {action}.")
        if action == "set" and level is not None:
            # Approximate: mute then raise N times (rough)
            pyautogui.press("volumemute")
            time.sleep(0.05)
            pyautogui.press("volumemute")
            steps = max(0, min(50, int(level) // 2))
            for _ in range(50):
                pyautogui.press("volumedown")
            for _ in range(steps):
                pyautogui.press("volumeup")
            return ToolResult(True, f"Volume set approximately to {level}.")
        return ToolResult(False, f"Unknown volume/media action '{action}'.")

    def clipboard(self, action: str = "read", text: str = "", confirmed: bool = False) -> ToolResult:
        import pyperclip

        action = action.lower()
        if action == "read":
            try:
                content = pyperclip.paste()
                preview = (content or "")[:200]
                return ToolResult(True, f"Clipboard: {preview}", {"text": content})
            except Exception as exc:  # noqa: BLE001
                return ToolResult(False, str(exc))
        if action == "write":
            if not confirmed:
                return ToolResult(
                    False,
                    "Overwrite clipboard?",
                    {"text": text},
                    needs_confirm=True,
                )
            pyperclip.copy(text)
            return ToolResult(True, "Clipboard updated.")
        return ToolResult(False, "clipboard action must be read or write.")

    def settings_page(self, page: str = "home") -> ToolResult:
        page = (page or "home").lower().replace("wi-fi", "wifi")
        uris = {
            "home": "ms-settings:",
            "wifi": "ms-settings:network-wifi",
            "bluetooth": "ms-settings:bluetooth",
            "display": "ms-settings:display",
            "sound": "ms-settings:sound",
            "network": "ms-settings:network",
            "apps": "ms-settings:appsfeatures",
            "privacy": "ms-settings:privacy",
        }
        uri = uris.get(page, "ms-settings:")
        try:
            os.startfile(uri)  # noqa: S606
            label = page if page != "home" else "settings"
            return ToolResult(True, f"Opened {label} settings.")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"Could not open settings: {exc}")

    def _focus_hwnd(self, hwnd: int) -> bool:
        """Force a window to the foreground (AttachThreadInput bypasses Windows focus steal)."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if not hwnd:
                return False
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            else:
                user32.ShowWindow(hwnd, 5)  # SW_SHOW
            fg = user32.GetForegroundWindow()
            if fg == hwnd:
                return True
            cur_tid = kernel32.GetCurrentThreadId()
            fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
            target_tid = user32.GetWindowThreadProcessId(hwnd, None)
            attached_fg = False
            attached_tg = False
            if fg_tid and fg_tid != cur_tid:
                attached_fg = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
            if target_tid and target_tid != cur_tid and target_tid != fg_tid:
                attached_tg = bool(user32.AttachThreadInput(cur_tid, target_tid, True))
            try:
                user32.AllowSetForegroundWindow(-1)
            except Exception:  # noqa: BLE001
                pass
            user32.BringWindowToTop(hwnd)
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)  # HWND_TOPMOST
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)  # HWND_NOTOPMOST
            user32.SetForegroundWindow(hwnd)
            if attached_tg and target_tid:
                user32.AttachThreadInput(cur_tid, target_tid, False)
            if attached_fg and fg_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
            time.sleep(0.05)
            return int(user32.GetForegroundWindow()) == int(hwnd)
        except Exception:  # noqa: BLE001
            return False

    def _snapshot_pids(self) -> set[int]:
        """Current process IDs (best-effort)."""
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            arr = (wintypes.DWORD * 4096)()
            needed = wintypes.DWORD()
            if not kernel32.K32EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
                return set()
            count = int(needed.value) // ctypes.sizeof(wintypes.DWORD)
            return {int(arr[i]) for i in range(count) if arr[i]}
        except Exception:  # noqa: BLE001
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FO", "CSV", "/NH"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                pids: set[int] = set()
                for line in out.splitlines():
                    parts = line.split(",")
                    if len(parts) >= 2:
                        try:
                            pids.add(int(parts[1].strip().strip('"')))
                        except ValueError:
                            pass
                return pids
            except Exception:  # noqa: BLE001
                return set()

    def _remember_launch(self, app: str, pids: set[int] | None = None) -> None:
        label = (app or "").strip()
        if label:
            self._last_app = label
        if pids is not None:
            self._last_pids = {int(p) for p in pids if p}

    def _same_app(self, a: str, b: str) -> bool:
        ca, _ = self.resolve_app(a or "")
        cb, _ = self.resolve_app(b or "")
        left = (ca or a or "").strip().lower()
        right = (cb or b or "").strip().lower()
        return bool(left and right and left == right)

    def _process_images_for(self, name: str) -> list[str]:
        """Resolve exe names for ANY configured app from apps.json + aliases."""
        canon, meta = self.resolve_app(name)
        key = (canon or name or "").strip().lower()
        targets: list[str] = []

        def add(image: str) -> None:
            image = (image or "").strip().lower()
            if image and image not in targets:
                if not image.endswith(".exe"):
                    image = f"{image}.exe"
                if image not in targets:
                    targets.append(image)

        # Known Windows aliases (optional extras; apps.json remains source of truth).
        extras = {
            "edge": ["msedge.exe"],
            "vscode": ["code.exe"],
            "code": ["code.exe"],
            "calculator": ["calculatorapp.exe", "calc.exe"],
            "terminal": ["windowsterminal.exe", "wt.exe", "powershell.exe", "pwsh.exe", "cmd.exe"],
            "camera": ["windowscamera.exe"],
            "photos": ["photos.exe"],
            "snip": ["screenclippinghost.exe", "snippingtool.exe"],
            "store": ["winstore.app.exe"],
            "clock": ["time.exe"],
            "task manager": ["taskmgr.exe"],
        }
        for img in extras.get(key, []):
            add(img)

        if meta:
            for cmd in meta.get("commands") or []:
                raw = str(cmd)
                if raw.startswith("ms-") or "://" in raw:
                    continue
                base = Path(os.path.expandvars(raw.split("*")[0] + ("*" if "*" in raw else ""))).name
                # For wildcard paths take the filename pattern end.
                if "*" in raw:
                    base = Path(raw.replace("\\", "/").split("/")[-1]).name.replace("*", "")
                    if base.lower().endswith(".exe"):
                        add(base)
                    continue
                base = Path(os.path.expandvars(raw)).name
                if base.lower().endswith(".exe"):
                    add(base)
            shell = str(meta.get("shell") or "").strip()
            if shell and not shell.lower().startswith("start "):
                token = shell.split()[0]
                base = Path(token).name
                if base.lower().endswith(".exe") or "." not in base:
                    add(base)

        # Canon + spoken name + aliases from apps.json
        add(key)
        add((name or "").strip().lower())
        if meta:
            for alias in meta.get("aliases") or []:
                token = re.sub(r"[^a-z0-9]+", "", str(alias).lower())
                if len(token) >= 3:
                    add(token)
        return targets

    def _focus_by_pids(self, pids: set[int]) -> bool:
        """Focus the newest visible top-level window owned by one of these PIDs."""
        wanted = {int(p) for p in pids if p}
        if not wanted:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            found: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def enum_proc(hwnd, _lp):  # noqa: N803
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetWindow(hwnd, 4):  # GW_OWNER
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if int(pid.value) not in wanted:
                    return True
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                if (rect.right - rect.left) < 40 or (rect.bottom - rect.top) < 40:
                    return True
                found.append(int(hwnd))
                return True

            user32.EnumWindows(enum_proc, 0)
            for hwnd in reversed(found):
                if self._focus_hwnd(hwnd):
                    return True
            return False
        except Exception:  # noqa: BLE001
            return False

    def _focus_by_process(self, images: list[str]) -> bool:
        """Focus the newest visible top-level window owned by one of these exe names."""
        wanted = {img.lower() for img in images if img}
        if not wanted:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            psapi = ctypes.windll.psapi
            found: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def enum_proc(hwnd, _lp):  # noqa: N803
                if not user32.IsWindowVisible(hwnd):
                    return True
                # Owned/tool windows are usually not the main app surface.
                if user32.GetWindow(hwnd, 4):  # GW_OWNER
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if not pid.value:
                    return True
                handle = kernel32.OpenProcess(0x0410, False, pid.value)  # QUERY | VM_READ
                if not handle:
                    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED
                if not handle:
                    return True
                try:
                    image = ""
                    buf = ctypes.create_unicode_buffer(260)
                    if psapi.GetModuleBaseNameW(handle, None, buf, 260):
                        image = buf.value.lower()
                    else:
                        size = wintypes.DWORD(260)
                        full = ctypes.create_unicode_buffer(260)
                        if kernel32.QueryFullProcessImageNameW(handle, 0, full, ctypes.byref(size)):
                            image = Path(full.value).name.lower()
                    if image in wanted:
                        rect = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        if (rect.right - rect.left) < 40 or (rect.bottom - rect.top) < 40:
                            return True
                        found.append(int(hwnd))
                finally:
                    kernel32.CloseHandle(handle)
                return True

            user32.EnumWindows(enum_proc, 0)
            if not found:
                return False
            for hwnd in reversed(found):
                if self._focus_hwnd(hwnd):
                    return True
            return False
        except Exception:  # noqa: BLE001
            return False

    def _focus_by_title(self, needle: str) -> bool:
        """Bring a window whose title contains needle to the foreground (Windows)."""
        needle = (needle or "").strip().lower()
        if not needle:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            found: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def enum_proc(hwnd, _lp):  # noqa: N803
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                # Win11 Notepad often has an empty title — still consider via process path.
                title = ""
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.lower()
                if needle and needle in title:
                    found.append(int(hwnd))
                return True

            user32.EnumWindows(enum_proc, 0)
            if not found:
                return False
            for hwnd in reversed(found):
                if self._focus_hwnd(hwnd):
                    return True
            return False
        except Exception:  # noqa: BLE001
            return False

    def _title_needles_for(self, name: str) -> list[str]:
        canon, meta = self.resolve_app(name)
        label = (canon or name or "").strip()
        needles: list[str] = []
        for item in (label, label.replace(" ", ""), (name or "").strip()):
            item = (item or "").strip().lower()
            if item and item not in needles:
                needles.append(item)
        if meta:
            for alias in meta.get("aliases") or []:
                item = str(alias).strip().lower()
                if item and item not in needles:
                    needles.append(item)
        return needles

    def _await_focus(self, name: str, timeout: float = 2.5, pids: set[int] | None = None) -> bool:
        """Poll until the named app window exists and is focused (any application)."""
        canon, _meta = self.resolve_app(name)
        label = (canon or name or "").strip()
        if not label and not pids:
            return False
        needles = self._title_needles_for(label or name or "")
        images = self._process_images_for(label or name or "")
        use_pids = {int(p) for p in (pids or self._last_pids or set()) if p}
        deadline = time.time() + max(0.4, float(timeout))
        while time.time() < deadline:
            if use_pids and self._focus_by_pids(use_pids):
                return True
            if images and self._focus_by_process(images):
                return True
            for needle in needles:
                if self._focus_by_title(needle):
                    return True
            time.sleep(0.12)
        if use_pids and self._focus_by_pids(use_pids):
            return True
        if images and self._focus_by_process(images):
            return True
        for needle in needles:
            if self._focus_by_title(needle):
                return True
        return False

    def _focus_existing(self, name: str) -> ToolResult:
        canon, _meta = self.resolve_app(name)
        label = (canon or name or "").strip()
        if not label:
            return ToolResult(False, "No app to focus.")
        pids = self._last_pids if self._same_app(label, self._last_app) else set()
        if self._await_focus(label, timeout=1.8, pids=pids):
            self._remember_launch(label, self._last_pids if pids else self._last_pids)
            return ToolResult(True, f"Focused {label}.", {"app": label})
        return ToolResult(False, f"Could not find an open window for {label}.")

    def _kill_app_process(self, name: str, wait: bool = False) -> bool:
        """Best-effort taskkill for known apps. Default: fire-and-forget (instant return)."""
        canon, _meta = self.resolve_app(name)
        targets = self._process_images_for(canon or name)
        if not targets:
            return False

        launched = False
        for img in dict.fromkeys(targets):  # dedupe preserve order
            try:
                if wait:
                    r = subprocess.run(
                        ["taskkill", "/IM", img, "/F"],
                        capture_output=True,
                        text=True,
                        timeout=1.2,
                        check=False,
                    )
                    if r.returncode == 0:
                        launched = True
                else:
                    # Don't block the voice loop waiting for processes to die
                    subprocess.Popen(
                        ["taskkill", "/IM", img, "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    launched = True
            except Exception:  # noqa: BLE001
                continue
        return launched

    def execute(self, name: str, args: Dict[str, Any], confirmed: bool = False) -> ToolResult:
        name = name.lower()
        if name == "open_app":
            return self.open_app(args.get("app") or args.get("name") or "")
        if name == "open_url":
            return self.open_url(args.get("url", ""))
        if name == "web_search":
            return self.web_search(args.get("query", ""), args.get("engine", "google"))
        if name == "type_text":
            return self.type_text(
                args.get("text", ""),
                confirmed=confirmed,
                app=str(args.get("app") or args.get("into") or args.get("window") or ""),
            )
        if name == "click_then_type":
            return self.click_then_type(
                args.get("text", ""),
                delay=float(args.get("delay") or 3.0),
                confirmed=confirmed,
            )
        if name == "whatsapp_send":
            return self.whatsapp_send(
                args.get("contact", ""),
                message=args.get("message", ""),
                from_clipboard=bool(args.get("from_clipboard")),
                confirmed=confirmed,
            )
        if name == "hotkey":
            return self.hotkey(args.get("action") or args.get("keys") or "", confirmed=confirmed)
        if name == "file_find":
            return self.find_files(args.get("query", ""))
        if name == "file_open":
            return self.file_open(args.get("path", ""))
        if name == "system_status":
            return self.system_status(args.get("metric", "time"))
        if name == "volume_media":
            return self.volume_media(args.get("action", ""), args.get("level"))
        if name == "clipboard":
            return self.clipboard(args.get("action", "read"), args.get("text", ""), confirmed)
        if name == "settings":
            return self.settings_page(args.get("page", "home"))
        if name == "close_app":
            raw = (args.get("app") or "").strip()
            # Strip filler: "the terminal" / "my chrome"
            app = re.sub(r"^(?:the|my|a|an|this|current)\s+", "", raw, flags=re.I).strip()
            app = re.sub(r"\s+windows?$", "", app, flags=re.I).strip() or app
            # Fast path: known apps → fire-and-forget taskkill (don't block on process exit)
            if app:
                try:
                    canon, _meta = self.resolve_app(app)
                except Exception:  # noqa: BLE001
                    canon = None
                kill_name = canon or app
                killed = self._kill_app_process(kill_name, wait=False)
                if killed:
                    return ToolResult(
                        True,
                        f"Closed {canon or app}.",
                        {"app": canon or app, "method": "taskkill"},
                    )
                # Focus + Alt+F4 if process kill missed (unknown / already closed)
                focused = self._focus_existing(kill_name)
                if focused.ok and _gui() is not None:
                    prev = getattr(pyautogui, "PAUSE", 0.01)
                    try:
                        pyautogui.PAUSE = 0
                        pyautogui.hotkey("alt", "f4")
                    finally:
                        pyautogui.PAUSE = prev
                    return ToolResult(True, f"Closed {canon or app}.", {"app": canon or app})
            # Unnamed / current window
            if _gui() is None:
                return ToolResult(False, "pyautogui not available.")
            prev = getattr(pyautogui, "PAUSE", 0.01)
            try:
                pyautogui.PAUSE = 0
                pyautogui.hotkey("alt", "f4")
            finally:
                pyautogui.PAUSE = prev
            return ToolResult(True, f"Closed {app or 'window'}.", {"app": app})
        if name == "focus_window":
            raw = (args.get("app") or "").strip()
            app = re.sub(r"^(?:the|my|a|an|this|current)\s+", "", raw, flags=re.I).strip() or raw
            focused = self._focus_existing(app)
            if focused.ok:
                return focused
            return self.open_app(app)
        if name == "speak":
            return ToolResult(True, args.get("text", ""))
        return ToolResult(False, f"Unknown tool '{name}'.")


TOOL_SCHEMAS = [
    {"name": "open_app", "args": {"app": "string"}},
    {"name": "web_search", "args": {"query": "string", "engine": "google|youtube|bing"}},
    {"name": "google_search", "args": {"query": "string"}},
    {"name": "youtube_search", "args": {"query": "string"}},
    {"name": "youtube_home", "args": {}},
    {"name": "youtube_media", "args": {"action": "play|pause|next|prev"}},
    {"name": "youtube_play", "args": {"url": "string", "title": "string"}},
    {"name": "play_nth", "args": {"index": "0-based int"}},
    {"name": "set_preferred_browser", "args": {"browser": "chrome|brave|edge"}},
    {"name": "open_url", "args": {"url": "string", "title": "string"}},
    {"name": "type_text", "args": {"text": "string"}},
    {"name": "click_then_type", "args": {"text": "string", "delay": "seconds"}},
    {
        "name": "whatsapp_send",
        "args": {
            "contact": "string",
            "message": "string",
            "from_clipboard": "bool",
        },
    },
    {"name": "mail_search", "args": {"query": "string"}},
    {"name": "mail_summarize", "args": {"query": "string", "max": "int"}},
    {
        "name": "mail_compose",
        "args": {"to": "string", "subject": "string", "body": "string"},
    },
    {"name": "mail_reply", "args": {"message_id": "string", "body": "string"}},
    {"name": "mail_send", "args": {"draft_id": "string"}},
    {"name": "set_reminder", "args": {"text": "string", "when": "string", "minutes": "number"}},
    {"name": "list_reminders", "args": {}},
    {"name": "calendar_list", "args": {"query": "string", "days": "int"}},
    {
        "name": "calendar_create",
        "args": {
            "title": "string",
            "when": "string",
            "duration_minutes": "int",
            "location": "string",
        },
    },
    {"name": "drive_search", "args": {"query": "string"}},
    {"name": "drive_open", "args": {"file_id": "string", "url": "string"}},
    {"name": "maps_search", "args": {"query": "string"}},
    {
        "name": "maps_directions",
        "args": {"destination": "string", "origin": "string", "mode": "driving|walking|transit"},
    },
    {"name": "hotkey", "args": {"action": "string"}},
    {"name": "file_find", "args": {"query": "string"}},
    {"name": "file_open", "args": {"path": "string"}},
    {"name": "system_status", "args": {"metric": "time|battery|volume|date"}},
    {"name": "volume_media", "args": {"action": "mute|unmute|play|pause|next|previous|set", "level": "0-100"}},
    {"name": "clipboard", "args": {"action": "read|write", "text": "string"}},
    {"name": "settings", "args": {"page": "string"}},
    {"name": "speak", "args": {"text": "string"}},
    {"name": "close_app", "args": {"app": "string"}},
    {"name": "focus_window", "args": {"app": "string"}},
]
