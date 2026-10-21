"""Playwright-backed browser with recovery + Brave preference."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from tools.os_tools import ToolResult

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "data" / "browser-profile"
APPS_JSON = ROOT / "config" / "apps.json"


def _brave_path() -> Optional[str]:
    try:
        apps = json.loads(APPS_JSON.read_text(encoding="utf-8"))
        for cmd in apps.get("brave", {}).get("commands", []):
            p = Path(cmd)
            if p.exists():
                return str(p)
    except Exception:  # noqa: BLE001
        pass
    candidates = [
        Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
        Path.home() / r"AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


class BrowserTools:
    """Long-lived Playwright browser for Marc sessions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._available: Optional[bool] = None
        self._error = ""
        self.preferred_browser = "chrome"

    @property
    def available(self) -> bool:
        if self._available is None:
            try:
                import playwright  # noqa: F401

                self._available = True
            except Exception as exc:  # noqa: BLE001
                self._available = False
                self._error = str(exc)
        return bool(self._available)

    def set_preferred_browser(self, name: str) -> None:
        name = (name or "chrome").lower()
        if name in ("brave", "chrome", "edge", "msedge"):
            if name == "msedge":
                name = "edge"
            if name != self.preferred_browser:
                # Relaunch with new channel next time
                self.close()
            self.preferred_browser = name

    def _reset(self) -> None:
        self._page = None
        self._context = None
        try:
            if self._browser:
                self._browser.close()
        except Exception:  # noqa: BLE001
            pass
        self._browser = None
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = None

    def _ensure_page(self):
        # Detect dead page
        if self._page is not None:
            try:
                _ = self._page.url
                return self._page
            except Exception:  # noqa: BLE001
                self._reset()

        from playwright.sync_api import sync_playwright

        PROFILE.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        browser = self.preferred_browser
        launched = False
        last_exc: Optional[Exception] = None

        if browser == "brave":
            exe = _brave_path()
            if exe:
                try:
                    self._browser = self._pw.chromium.launch(
                        headless=False,
                        executable_path=exe,
                        args=["--start-maximized"],
                    )
                    launched = True
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc

        if not launched and browser == "edge":
            try:
                self._browser = self._pw.chromium.launch(
                    headless=False, channel="msedge", args=["--start-maximized"]
                )
                launched = True
            except Exception as exc:  # noqa: BLE001
                last_exc = exc

        if not launched:
            try:
                self._browser = self._pw.chromium.launch(
                    headless=False, channel="chrome", args=["--start-maximized"]
                )
                launched = True
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._browser = self._pw.chromium.launch(
                    headless=False, args=["--start-maximized"]
                )
                launched = True

        self._context = self._browser.new_context(no_viewport=True)
        self._page = self._context.new_page()
        if last_exc and browser == "brave":
            print(f"[marc] Brave launch fallback ({last_exc})")
        return self._page

    def close(self) -> None:
        with self._lock:
            self._reset()

    def _with_page(self, fn):
        """Run fn(page); on TargetClosedError, relaunch and retry once."""
        with self._lock:
            try:
                page = self._ensure_page()
                return fn(page)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                if "has been closed" in msg or "target" in msg and "closed" in msg:
                    print("[marc] browser was closed — relaunching")
                    self._reset()
                    page = self._ensure_page()
                    return fn(page)
                raise

    def youtube_search(self, query: str) -> ToolResult:
        q = (query or "").strip()
        if not q:
            return ToolResult(False, "Empty YouTube query.")
        url = f"https://www.youtube.com/results?search_query={quote_plus(q)}"

        def _go(page):
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1800)
            return self._scrape_youtube_results(page)

        if not self.available:
            import webbrowser

            webbrowser.open(url)
            return ToolResult(
                True,
                f"Opened YouTube search for {q}, but I couldn't read the result list.",
                {"query": q, "results": [], "fallback": True, "scrape_ok": False},
            )
        try:
            results = self._with_page(_go)
            if results:
                return ToolResult(
                    True,
                    f"Showing YouTube results for {q}.",
                    {"query": q, "results": results, "scrape_ok": True},
                )
            return ToolResult(
                True,
                f"Opened YouTube search for {q}, but I couldn't read the list. Say the video name.",
                {"query": q, "results": [], "scrape_ok": False},
            )
        except Exception as exc:  # noqa: BLE001
            import webbrowser

            webbrowser.open(url)
            return ToolResult(
                True,
                f"Opened YouTube search for {q}, but scrape failed. Say the video name.",
                {"query": q, "results": [], "fallback": True, "scrape_ok": False, "error": str(exc)},
            )

    def _scrape_youtube_results(self, page) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        seen: set[str] = set()
        selectors = [
            "ytd-video-renderer a#video-title",
            "ytd-rich-item-renderer a#video-title-link",
            "ytd-rich-grid-media a#video-title-link",
            "a#video-title-link",
            "a#video-title",
        ]
        links = []
        for sel in selectors:
            found = page.query_selector_all(sel)
            if found:
                links.extend(found)
        for el in links:
            if len(results) >= 10:
                break
            try:
                title = (el.get_attribute("title") or el.inner_text() or "").strip()
                href = el.get_attribute("href") or ""
                if not title or not href:
                    continue
                if href.startswith("/"):
                    href = "https://www.youtube.com" + href
                if "watch" not in href:
                    continue
                href = href.split("&")[0]
                if href in seen:
                    continue
                seen.add(href)
                results.append({"title": title, "url": href})
            except Exception:  # noqa: BLE001
                continue
        return results

    def youtube_home(self) -> ToolResult:
        """Open YouTube home and scrape the home feed into a pickable result list."""
        url = "https://www.youtube.com"

        def _go(page):
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            return self._scrape_youtube_results(page)

        if not self.available:
            import webbrowser

            webbrowser.open(url)
            return ToolResult(
                True,
                "Opened YouTube, but I couldn't read the home feed.",
                {"query": "", "results": [], "scrape_ok": False, "fallback": True},
            )
        try:
            results = self._with_page(_go)
            if results:
                return ToolResult(
                    True,
                    f"YouTube home is open with {len(results)} videos. Say play the first, second, or a title.",
                    {"query": "", "results": results, "scrape_ok": True},
                )
            return ToolResult(
                True,
                "Opened YouTube home, but I couldn't read the feed. Say search YouTube for a title.",
                {"query": "", "results": [], "scrape_ok": False},
            )
        except Exception as exc:  # noqa: BLE001
            import webbrowser

            webbrowser.open(url)
            return ToolResult(
                True,
                f"Opened YouTube ({exc}).",
                {"query": "", "results": [], "scrape_ok": False, "error": str(exc)},
            )

    def google_search(self, query: str) -> ToolResult:
        """Search Google and scrape organic results for open-first / open-Nth."""
        q = (query or "").strip()
        if not q:
            return ToolResult(False, "Empty Google query.")
        url = f"https://www.google.com/search?q={quote_plus(q)}"

        def _go(page):
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1800)
            return self._scrape_google_results(page)

        if not self.available:
            import webbrowser

            webbrowser.open(url)
            return ToolResult(
                True,
                f"Opened Google search for {q}, but I couldn't read the results.",
                {"query": q, "results": [], "scrape_ok": False, "fallback": True},
            )
        try:
            results = self._with_page(_go)
            if results:
                return ToolResult(
                    True,
                    f"Showing Google results for {q}. Say open the first or second.",
                    {"query": q, "results": results, "scrape_ok": True},
                )
            return ToolResult(
                True,
                f"Opened Google search for {q}, but I couldn't read the list.",
                {"query": q, "results": [], "scrape_ok": False},
            )
        except Exception as exc:  # noqa: BLE001
            import webbrowser

            webbrowser.open(url)
            return ToolResult(
                True,
                f"Opened Google search for {q} ({exc}).",
                {"query": q, "results": [], "scrape_ok": False, "error": str(exc)},
            )

    def _scrape_google_results(self, page) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        seen: set[str] = set()
        # Prefer classic organic result blocks
        blocks = page.query_selector_all("div#search a h3")
        for h3 in blocks:
            if len(results) >= 10:
                break
            try:
                parent = h3.evaluate_handle("el => el.closest('a')")
                a = parent.as_element() if parent else None
                if a is None:
                    continue
                title = (h3.inner_text() or "").strip()
                href = a.get_attribute("href") or ""
                if not title or not href or not href.startswith("http"):
                    continue
                if "google." in href and "/search" in href:
                    continue
                if href in seen:
                    continue
                seen.add(href)
                results.append({"title": title, "url": href})
            except Exception:  # noqa: BLE001
                continue
        return results

    def open_url(self, url: str = "", title: str = "") -> ToolResult:
        if not url:
            return ToolResult(False, "No URL to open.")

        def _go(page):
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            return True

        if not self.available:
            import webbrowser

            webbrowser.open(url)
            return ToolResult(True, f"Opened{': ' + title if title else ' link'}.", {"url": url})
        try:
            self._with_page(_go)
            label = title or "page"
            return ToolResult(True, f"Opened {label}.", {"url": url, "title": title})
        except Exception as exc:  # noqa: BLE001
            import webbrowser

            webbrowser.open(url)
            return ToolResult(True, f"Opened link ({exc}).", {"url": url})

    def youtube_play(self, url: str = "", title: str = "") -> ToolResult:
        if not url:
            return ToolResult(False, "No video URL to play. Search YouTube first.")

        def _go(page):
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1200)
            try:
                page.keyboard.press("k")
            except Exception:  # noqa: BLE001
                pass
            return True

        if not self.available:
            import webbrowser

            webbrowser.open(url)
            return ToolResult(True, f"Opened video{': ' + title if title else ''}.", {"url": url})
        try:
            self._with_page(_go)
            label = title or "video"
            return ToolResult(True, f"Playing {label}.", {"url": url, "title": title})
        except Exception as exc:  # noqa: BLE001
            import webbrowser

            webbrowser.open(url)
            return ToolResult(True, f"Opened video ({exc}).", {"url": url})

    def youtube_media(self, action: str = "play") -> ToolResult:
        action = (action or "play").lower().strip()
        if action in ("next", "skip", "next video", "next track"):
            key = "Shift+N"
            press = ("shift", "n")
            label = "next"
        elif action in ("prev", "previous", "previous video", "prev video"):
            key = "Shift+P"
            press = ("shift", "p")
            label = "previous"
        else:
            key = "k"
            press = ("k",)
            label = action or "play"

        def _go(page):
            page.bring_to_front()
            if len(press) == 1:
                page.keyboard.press(press[0])
            else:
                page.keyboard.press(key)
            return True

        if not self.available or self._page is None:
            try:
                import pyautogui

                if label in ("next", "previous"):
                    pyautogui.hotkey(*press)
                else:
                    pyautogui.press("playpause")
                return ToolResult(True, f"Media {label}.")
            except Exception as exc:  # noqa: BLE001
                return ToolResult(False, f"Media control failed: {exc}")
        try:
            self._with_page(_go)
            return ToolResult(True, f"YouTube {label}.")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, str(exc))

    def gmail_open(self) -> ToolResult:
        import webbrowser

        webbrowser.open("https://mail.google.com")
        return ToolResult(True, "Opened Gmail.")

    def gmail_search(self, query: str) -> ToolResult:
        q = (query or "").strip()
        if not q:
            return self.gmail_open()
        import webbrowser

        url = f"https://mail.google.com/mail/u/0/#search/{quote_plus(q)}"
        webbrowser.open(url)
        return ToolResult(True, f"Opened Gmail search for {q}.", {"query": q})


_BROWSER: Optional[BrowserTools] = None


def get_browser() -> BrowserTools:
    global _BROWSER
    if _BROWSER is None:
        _BROWSER = BrowserTools()
    return _BROWSER
