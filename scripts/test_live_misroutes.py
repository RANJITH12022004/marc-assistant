#!/usr/bin/env python3
"""Dry-routing regression for live misroutes (no mic, no Playwright side effects when possible)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _tools(result) -> list[str]:
    return [(s.get("tool") or "") for s in (result.steps_run or [])]


def main() -> int:
    from laya_router.compound import normalize_transcript, parse_compound
    from orchestrator import MarcOrchestrator
    from orchestrator.followup import resolve_followup
    from orchestrator.session import SessionState, VideoResult

    # Specious speak/confirm — no TTS
    orch = MarcOrchestrator(
        preload_laya=False,
        lazy_laya=False,
        speak_fn=lambda _m: None,
        confirm_fn=lambda _m: False,
        session=SessionState(),
    )
    # Force rules-only router for deterministic CI without Laya weights
    orch.router.rules_only = True
    orch.router._agent = None

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    # --- normalize ---
    check("normalize Bye.", normalize_transcript("Bye.") == "Bye")
    check(
        "normalize typhoid",
        normalize_transcript("typhoid this is Ranjit").lower().startswith("type "),
    )
    check(
        "normalize no type",
        normalize_transcript("no type hi this is Ranjeet").lower().startswith("type "),
    )
    check(
        "normalize entertainment",
        "enter" in normalize_transcript("hit entertainment").lower(),
    )

    # --- compound / followup dry ---
    plan = parse_compound("Bye.")
    # Bye is followup sleep, not compound
    check("Bye. not compound mail", plan is None or plan.get("intent") != "mail_summarize")

    orch.session = SessionState()
    r = orch.handle("Bye.")
    check("Bye. -> sleep", r.intent == "sleep", f"got {r.intent}")

    orch.session = SessionState()
    r = orch.handle("email Ranjith")
    check(
        "email Ranjith not whatsapp",
        r.intent != "whatsapp_send" and "whatsapp" not in ",".join(_tools(r)).lower(),
        f"intent={r.intent} tools={_tools(r)} reply={r.reply!r}",
    )

    orch.session = SessionState()
    r = orch.handle("what was the last email I have received")
    check(
        "last email -> mail_summarize",
        r.intent == "mail_summarize" or "mail_summarize" in _tools(r),
        f"intent={r.intent} tools={_tools(r)}",
    )

    orch.session = SessionState()
    r = orch.handle("open camera and click")
    check(
        "open camera and click -> camera_photo",
        r.intent == "camera_photo" or "camera_photo" in _tools(r),
        f"intent={r.intent} tools={_tools(r)}",
    )

    orch.session = SessionState()
    r = orch.handle("open the photo you have taken")
    check(
        "open last photo",
        r.intent == "open_last_photo" or "open_last_photo" in _tools(r) or "photos" in str(r.reply).lower(),
        f"intent={r.intent} tools={_tools(r)}",
    )

    orch.session = SessionState()
    r = orch.handle("what's the time now type the time in the Notepad")
    tools = _tools(r)
    check(
        "time+type compound",
        "system_status" in tools and "type_text" in tools,
        f"intent={r.intent} tools={tools}",
    )

    orch.session = SessionState()
    r = orch.handle("typhoid this is Ranjit")
    check(
        "typhoid -> type_text",
        r.intent == "type_text" or "type_text" in _tools(r),
        f"intent={r.intent} tools={_tools(r)} transcript_norm={normalize_transcript('typhoid this is Ranjit')!r}",
    )

    orch.session = SessionState()
    r = orch.handle("go to second")
    check(
        "go to second no pick -> clarify",
        r.intent == "clarify" and "focus_window" not in _tools(r),
        f"intent={r.intent} tools={_tools(r)}",
    )

    # With pick context
    sess = SessionState()
    sess.awaiting = "pick_video"
    sess.last_site = "youtube"
    sess.last_results = [
        VideoResult(title="A", url="https://youtu.be/a", index=0),
        VideoResult(title="B", url="https://youtu.be/b", index=1),
    ]
    fplan = resolve_followup("go to second", sess)
    check(
        "go to second with pick -> play",
        bool(fplan)
        and fplan.get("intent") in ("play_video", "open_result")
        and any(s.get("tool") == "youtube_play" for s in (fplan.get("steps") or [])),
        f"plan={fplan}",
    )

    # Confirm must not sticky-search YouTube
    sess = SessionState()
    sess.awaiting = "confirm"
    sess.last_site = "youtube"
    fplan = resolve_followup("yes", sess)
    check(
        "yes+confirm no youtube_search",
        fplan is None or fplan.get("intent") != "youtube_search",
        f"plan={fplan}",
    )

    orch.session = SessionState()
    r = orch.handle("shut down my system")
    check(
        "shut down -> refuse/clarify",
        r.intent in ("refuse", "clarify") and not any(
            t in _tools(r) for t in ("hotkey", "open_app", "volume_media")
        ),
        f"intent={r.intent} tools={_tools(r)}",
    )

    # Send it after type
    orch.session = SessionState()
    orch.session.last_typed = "hello"
    orch.session.last_tool = "type_text"
    r = orch.handle("send it")
    check(
        "send it after type -> enter",
        "hotkey" in _tools(r) or r.intent == "hotkey",
        f"intent={r.intent} tools={_tools(r)}",
    )

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("All live-misroute checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
