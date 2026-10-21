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

try:
    import pyautogui

    pyautogui.FAILSAFE = False  # corner mouse must not kill Marc mid-command
    # Keep PAUSE near-zero so hotkey/media/close feel instant
    pyautogui.PAUSE = 0.01
except Exception:  # noqa: BLE001
    pyautogui = None  # type: ignore


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

        # Prefer local install / shell protocol; fall back to URL apps
        for cmd in meta.get("commands", []):
            if cmd.startswith("ms-settings:"):
                os.startfile(cmd)  # noqa: S606
                return ToolResult(True, f"Opened {canon}.")
            # Allow simple wildcards in WindowsApps paths
            if "*" in cmd:
                import glob

                matches = glob.glob(os.path.expandvars(cmd))
                if matches:
                    subprocess.Popen([matches[0]], shell=False)  # noqa: S603
                    return ToolResult(True, f"Opened {canon}.")
                continue
            path = Path(os.path.expandvars(cmd))
            if path.exists():
                subprocess.Popen([str(path)], shell=False)  # noqa: S603
                return ToolResult(True, f"Opened {canon}.")

        shell = meta.get("shell")
        if shell:
            try:
                if shell.startswith("start "):
                    os.system(shell)  # noqa: S605
                else:
                    subprocess.Popen(shell, shell=True)  # noqa: S602
                return ToolResult(True, f"Opened {canon}.")
            except Exception as exc:  # noqa: BLE001
                # Fall through to URL if present
                if not meta.get("url"):
                    return ToolResult(False, f"Failed to open {canon}: {exc}")

        url = meta.get("url")
        if url:
            webbrowser.open(url)
            return ToolResult(True, f"Opened {canon}.")

        return ToolResult(False, f"Could not find executable for {canon}.")

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

    def type_text(self, text: str, confirmed: bool = False) -> ToolResult:
        if not confirmed:
            return ToolResult(
                False,
                f"Type into the focused window: “{text[:80]}”? Confirm to proceed.",
                {"text": text},
                needs_confirm=True,
            )
        if pyautogui is None:
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

        method = self._insert_text(text)
        if send_after:
            time.sleep(0.12)
            self.hotkey("enter", confirmed=True)
        return ToolResult(
            True,
            "Typed text into the focused window.",
            {"chars": len(text), "method": method, "sent": send_after},
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
        if pyautogui:
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
        if pyautogui is None:
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

        if pyautogui is None:
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
        if pyautogui is None:
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
        if pyautogui is None:
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

    def _focus_by_title(self, needle: str) -> bool:
        """Bring a window whose title contains needle to the foreground (Windows)."""
        needle = (needle or "").strip().lower()
        if not needle:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            found = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def enum_proc(hwnd, _lp):  # noqa: N803
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.lower()
                if needle in title:
                    found.append(hwnd)
                return True

            user32.EnumWindows(enum_proc, 0)
            if not found:
                return False
            hwnd = found[0]
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _focus_existing(self, name: str) -> ToolResult:
        canon, _meta = self.resolve_app(name)
        label = (canon or name or "").strip()
        if not label:
            return ToolResult(False, "No app to focus.")
        # Try common title fragments
        for needle in {label, label.replace(" ", ""), name.strip().lower()}:
            if needle and self._focus_by_title(needle):
                return ToolResult(True, f"Focused {label}.", {"app": label})
        return ToolResult(False, f"Could not find an open window for {label}.")

    def _kill_app_process(self, name: str, wait: bool = False) -> bool:
        """Best-effort taskkill for known apps. Default: fire-and-forget (instant return)."""
        canon, meta = self.resolve_app(name)
        key = (canon or name or "").strip().lower()
        # Map canonical apps → common Windows image names
        images = {
            "camera": ["WindowsCamera.exe"],
            "spotify": ["Spotify.exe"],
            "chrome": ["chrome.exe"],
            "brave": ["brave.exe"],
            "edge": ["msedge.exe"],
            "firefox": ["firefox.exe"],
            "notepad": ["notepad.exe"],
            "whatsapp": ["WhatsApp.exe"],
            "vlc": ["vlc.exe"],
            "cursor": ["Cursor.exe"],
            "code": ["Code.exe"],
            "vscode": ["Code.exe"],
            "terminal": ["WindowsTerminal.exe", "wt.exe", "powershell.exe", "pwsh.exe", "cmd.exe"],
            "powershell": ["powershell.exe", "pwsh.exe", "WindowsTerminal.exe"],
            "cmd": ["cmd.exe"],
        }
        targets = list(images.get(key) or [])
        if meta:
            for cmd in meta.get("commands") or []:
                base = Path(str(cmd)).name
                if base and base.lower().endswith(".exe"):
                    targets.append(base)
        if not targets:
            return False
        import subprocess

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
            return self.type_text(args.get("text", ""), confirmed=confirmed)
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
                if focused.ok and pyautogui is not None:
                    prev = getattr(pyautogui, "PAUSE", 0.01)
                    try:
                        pyautogui.PAUSE = 0
                        pyautogui.hotkey("alt", "f4")
                    finally:
                        pyautogui.PAUSE = prev
                    return ToolResult(True, f"Closed {canon or app}.", {"app": canon or app})
            # Unnamed / current window
            if pyautogui is None:
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
