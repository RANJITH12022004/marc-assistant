#!/usr/bin/env python3
"""End-to-end orchestrator smoke (rules-only, no mic / no TTS)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["MARC_STEP_GAP"] = "0.05"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import MarcOrchestrator
from orchestrator.session import SessionState
from tools.os_tools import OSTools


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    speak_log: list[str] = []

    def speak(m: str) -> None:
        speak_log.append(m)

    orch = MarcOrchestrator(preload_laya=False, speak_fn=speak)

    # Browser + fullscreen (hotkey may fail without pyautogui — still check routing)
    orch.session = SessionState()
    r = orch.handle("open the browser and open the full screen")
    expect(
        r.intent in ("open_app", "multi_step", "hotkey"),
        f"fullscreen compound intent={r.intent}",
    )
    tools = [s.get("tool") for s in (r.steps_run or [])]
    expect(
        "open_app" in tools or "chrome" in (r.reply or "").lower() or "fullscreen" in (r.reply or "").lower()
        or "pyautogui" in (r.reply or "").lower()
        or bool(r.steps_run),
        f"reply={r.reply} tools={tools}",
    )
    print("OK", r.reply)

    # Bare open → hold → WhatsApp
    orch.session = SessionState()
    r = orch.handle("open")
    expect(orch.session.awaiting == "slot:open_app", f"awaiting={orch.session.awaiting}")
    expect("open what" in r.reply.lower(), r.reply)
    r = orch.handle("WhatsApp")
    expect(r.intent == "open_app", f"fill open={r.intent}")
    print("OK open → WhatsApp", r.reply)

    # search WhatsApp → open
    orch.session = SessionState()
    r = orch.handle("search WhatsApp")
    expect(r.intent == "open_app", f"search wa intent={r.intent}")
    print("OK search WhatsApp", r.reply)

    # open browser and → fullscreen
    orch.session = SessionState()
    r = orch.handle("open browser and")
    expect(orch.session.awaiting == "slot:continue", orch.session.awaiting)
    r = orch.handle("fullscreen")
    expect(r.intent == "open_app", r.intent)
    print("OK open browser and → fullscreen", r.reply)

    # Soft cancel while holding
    orch.session = SessionState()
    orch.handle("open")
    r = orch.handle("cancel")
    expect(r.intent == "clarify", r.intent)
    expect(r.should_continue is True, "cancel stays awake")
    print("OK cancel while hold")

    # Empty google results must not leave pick_result
    orch.session = SessionState()
    orch.session.set_results("google", "x", [])
    expect(orch.session.awaiting == "none", "empty set_results")

    # resolve_app water ≠ whatsapp
    tools = OSTools()
    canon, meta = tools.resolve_app("water")
    expect(meta is None and canon is None, f"water→{canon}")
    canon, meta = tools.resolve_app("whatsapp")
    expect(canon == "whatsapp", f"whatsapp→{canon}")
    print("OK resolve_app")

    # Pick first with mock results via followup path
    orch.session = SessionState()
    orch.session.set_results(
        "google",
        "q",
        [{"title": "One", "url": "https://one.example"}],
    )
    r = orch.handle("open the first")
    expect(r.intent == "open_result", r.intent)
    print("OK open the first", r.reply)

    # Close camera immediately — no confirm
    orch.session = SessionState()
    speak_log.clear()
    r = orch.handle("close camera")
    expect(orch.session.awaiting != "confirm", f"awaiting={orch.session.awaiting}")
    expect(orch._pending is None, f"pending={orch._pending}")
    expect("confirm to proceed" not in (r.reply or "").lower(), r.reply)
    tools = [s.get("tool") for s in (r.steps_run or [])]
    expect("close_app" in tools or r.intent == "close_app", f"tools={tools} intent={r.intent}")
    print("OK close camera no-confirm", r.reply)

    # Multi-close — no confirm
    orch.session = SessionState()
    r = orch.handle("close camera and spotify")
    expect(orch.session.awaiting != "confirm", f"multi awaiting={orch.session.awaiting}")
    expect(orch._pending is None, f"pending={orch._pending}")
    expect("confirm to proceed" not in (r.reply or "").lower(), r.reply)
    print("OK close camera and spotify no-confirm", r.reply)

    # Sticky pick cleared: YouTube then open Gmail must leave pick_video
    orch.session = SessionState()
    orch.handle("search youtube for jazz")
    r = orch.handle("open gmail")
    expect(orch.session.awaiting != "pick_video", f"awaiting={orch.session.awaiting}")
    expect(r.intent == "open_app" or "open_app" in [s.get("tool") for s in (r.steps_run or [])], r.intent)
    print("OK sticky pick cleared after open gmail")

    # Type then send it → Enter hotkey
    orch.session = SessionState()
    orch.handle("type hello world")
    r = orch.handle("send it")
    tools = [s.get("tool") for s in (r.steps_run or [])]
    expect("hotkey" in tools or r.intent == "hotkey", f"send tools={tools} intent={r.intent}")
    expect(r.intent != "youtube_search", r.intent)
    print("OK send it after type", r.intent, tools)

    # Play music on Spotify — not YouTube
    orch.session = SessionState()
    r = orch.handle("play music on Spotify")
    tools = [s.get("tool") for s in (r.steps_run or [])]
    expect(r.intent != "youtube_search", r.intent)
    expect("youtube_search" not in tools, tools)
    expect(
        "open_app" in tools or r.intent == "open_app",
        f"spotify intent={r.intent} tools={tools}",
    )
    expect("volume_media" in tools, f"must play: {tools}")
    print("OK play music on Spotify", r.intent, tools)

    # open Spotify and play music — open then media play (not second open_app)
    orch.session = SessionState()
    r = orch.handle("open Spotify and play music")
    tools = [s.get("tool") for s in (r.steps_run or [])]
    expect(tools[:2] == ["open_app", "volume_media"] or (
        "open_app" in tools and "volume_media" in tools and "youtube_search" not in tools
    ), f"open+play tools={tools}")
    print("OK open Spotify and play music", tools)

    # Yes. with pending close confirm punctuation (legacy pending path)
    from laya_router.compound import is_confirm

    expect(is_confirm("Yes."), "Yes. should confirm")
    expect(is_confirm("yes"), "yes should confirm")

    # search music → google/youtube, never Spotify
    orch.session = SessionState()
    r = orch.handle("search music")
    tools = [s.get("tool") for s in (r.steps_run or [])]
    expect(
        r.intent in ("web_search", "youtube_search") or any(
            t in ("google_search", "youtube_search", "web_search") for t in tools
        ),
        f"search music intent={r.intent} tools={tools} reply={r.reply}",
    )
    expect("spotify" not in (r.reply or "").lower(), r.reply)
    expect(
        not any(
            (s.get("args") or {}).get("app") == "spotify" for s in (r.steps_run or [])
        ),
        f"must not open spotify: {r.steps_run}",
    )
    print("OK search music", r.intent, r.reply)

    # next video with youtube context
    orch.session = SessionState()
    orch.session.last_site = "youtube"
    r = orch.handle("switch to the next video")
    expect(
        r.intent in ("youtube_media", "youtube_play")
        or any(
            (s.get("tool") == "youtube_media" and (s.get("args") or {}).get("action") == "next")
            for s in (r.steps_run or [])
        ),
        f"next video intent={r.intent} steps={r.steps_run}",
    )
    print("OK next video", r.intent, r.reply)

    print("ORCHESTRATOR SMOKE ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
