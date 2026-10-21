#!/usr/bin/env python3
"""Offline routing corpus (~100 cases) — no mic/TTS. Fast CI twin of live E2E."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ["MARC_STEP_GAP"] = "0.05"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "data" / "datasets" / "marc_live_e2e_v1.jsonl"


def _tools(steps_run) -> list[str]:
    return [str((s.get("tool") or "")).lower() for s in (steps_run or [])]


def _run_one(orch, case: dict) -> dict:
    from orchestrator.session import SessionState

    if case.get("clear_session_before"):
        orch.session = SessionState()
        orch._pending = None

    for setup in case.get("setup") or []:
        r = orch.handle(setup["say"])
        # Soft check setup
        if setup.get("expect_tools"):
            got = set(_tools(r.steps_run))
            want = set(t.lower() for t in setup["expect_tools"])
            if want and not (got & want) and r.intent not in (
                setup.get("expect_intent"),
                "multi_step",
                "open_app",
            ):
                pass  # continue; main assert is the final say

    t0 = time.perf_counter()
    result = orch.handle(case["say"])
    elapsed = time.perf_counter() - t0

    tools = _tools(result.steps_run)
    want_tools = [t.lower() for t in (case.get("expect_tools") or [])]
    expect_intent = case.get("expect_intent") or ""
    aliases = {
        "web_search": {"web_search", "google_search"},
        "mail_search": {"mail_search", "gmail_search", "clarify"},
        "mail_summarize": {"mail_summarize", "clarify"},
        "multi_step": {
            "multi_step",
            "open_app",
            "close_app",
            "type_text",
            "youtube_search",
            "camera_photo",
            "youtube_home",
        },
        "hotkey": {"hotkey"},
        "clarify": {"clarify", "chat"},
        "chat": {"chat", "clarify"},
        "sleep": {"sleep", "clarify"},
        "open_app": {"open_app", "youtube_home", "web_navigate"},
        "youtube_search": {"youtube_search", "web_search", "google_search", "play_video"},
        "close_app": {"close_app"},
        "type_text": {"type_text"},
        "play_video": {"play_video", "youtube_play"},
        "camera_photo": {"camera_photo"},
        "system_status": {"system_status"},
        "volume_media": {"volume_media"},
    }
    allowed = aliases.get(expect_intent, {expect_intent}) if expect_intent else {result.intent}
    intent_ok = (not expect_intent) or result.intent in allowed or (
        expect_intent == "open_app" and bool(set(tools) & {"open_app", "youtube_home"})
    )
    if expect_intent == "close_app" and ("close_app" in tools or "close_apps" in tools):
        intent_ok = True

    tools_ok = True
    if want_tools:
        got = set(tools)
        expanded_want = set(want_tools)
        if "close_app" in expanded_want:
            expanded_want.add("close_apps")
        if "mail_search" in expanded_want:
            expanded_want.add("gmail_search")
        if "open_app" in expanded_want:
            expanded_want.update({"youtube_home", "youtube_search"})
        if "youtube_search" in expanded_want:
            expanded_want.add("google_search")
        if "youtube_play" in expanded_want or "play_video" in expanded_want:
            expanded_want.update({"youtube_play", "play_nth"})
        tools_ok = bool(got & expanded_want) or (
            not want_tools and expect_intent in ("clarify", "chat", "sleep")
        )
        if "close" in (case.get("tags") or []):
            if result.pending_confirm or result.session.awaiting == "confirm":
                tools_ok = False
        if expect_intent == "close_app" and ("close_app" in tools or "close_apps" in tools):
            tools_ok = True

    forbid = case.get("forbid_awaiting") or ""
    await_ok = True
    if forbid and result.session.awaiting == forbid:
        # Exception: YouTube search cases may leave pick_video
        if not (
            forbid == "pick_video"
            and result.intent in ("youtube_search", "youtube_home", "play_video")
        ):
            await_ok = False

    # Spotify must not become YouTube
    if "not_youtube" in (case.get("tags") or []):
        if result.intent == "youtube_search" or "youtube_search" in tools:
            tools_ok = False
            intent_ok = False

    max_lat = float(case.get("max_latency_s") or 8.0)
    lat_ok = elapsed <= max_lat + 5.0  # offline slack

    ok = intent_ok and tools_ok and await_ok and lat_ok
    return {
        "id": case["id"],
        "ok": ok,
        "say": case["say"],
        "intent": result.intent,
        "expect_intent": expect_intent,
        "tools": tools,
        "awaiting": result.session.awaiting,
        "source": result.source,
        "elapsed_s": round(elapsed, 3),
        "pending_confirm": bool(result.pending_confirm),
        "reply": (result.reply or "")[:120],
        "fail_reasons": [
            x
            for x, good in [
                ("intent", intent_ok),
                ("tools", tools_ok),
                ("awaiting", await_ok),
                ("latency", lat_ok),
            ]
            if not good
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tag", default="")
    ap.add_argument("--regen", action="store_true")
    args = ap.parse_args()

    if args.regen or not CORPUS.exists():
        from scripts.generate_live_e2e_corpus import main as gen

        gen()

    cases = []
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))

    if args.tag:
        cases = [c for c in cases if args.tag in (c.get("tags") or [])]
    if args.limit:
        cases = cases[: args.limit]

    from orchestrator.agent import MarcOrchestrator
    from tools.os_tools import ToolResult

    orch = MarcOrchestrator(speak_fn=lambda *_a, **_k: None, preload_laya=False)

    # Dry-run: never launch real apps / browsers during corpus
    def _dry_exec(name, args=None, confirmed=False):
        args = args or {}
        n = (name or "").lower()
        if n == "close_app":
            return ToolResult(True, f"Closed {args.get('app') or 'window'}.", {"app": args.get("app")})
        if n == "close_apps":
            return ToolResult(True, f"Closed {args.get('apps')}.", {"apps": args.get("apps")})
        if n == "open_app":
            return ToolResult(True, f"Opened {args.get('app')}.", {"app": args.get("app")})
        if n == "type_text":
            return ToolResult(True, "Typed text into the focused window.", {"text": args.get("text")})
        if n == "hotkey":
            return ToolResult(True, f"Pressed {args.get('action')}.", {"action": args.get("action")})
        if n == "volume_media":
            return ToolResult(True, f"Media {args.get('action')}.", args)
        if n == "mail_summarize":
            return ToolResult(True, "You have 2 messages. Test mail.", {"summary": "You have 2 messages."})
        if n in ("mail_search", "gmail_search"):
            return ToolResult(
                True,
                "Mail results:\n1. Test",
                {"query": args.get("query"), "results": [{"id": "1", "title": "Test", "url": ""}]},
            )
        if n == "system_status":
            return ToolResult(True, "It is noon.", {"metric": args.get("metric")})
        return ToolResult(True, f"Dry {n}.", dict(args))

    orch.tools.execute = _dry_exec  # type: ignore[method-assign]
    orch._exec_tool_real = orch._exec_tool

    def _dry_browser_yt(q=""):
        return ToolResult(
            True,
            f"Showing YouTube results for {q}.",
            {
                "query": q,
                "results": [
                    {"title": "A", "url": "https://youtube.com/watch?v=a"},
                    {"title": "B", "url": "https://youtube.com/watch?v=b"},
                    {"title": "C", "url": "https://youtube.com/watch?v=c"},
                ],
            },
        )

    def _dry_browser_google(q=""):
        return ToolResult(
            True,
            f"Google results for {q}.",
            {"query": q, "results": [{"title": "R1", "url": "https://example.com"}]},
        )

    orch.browser.youtube_search = _dry_browser_yt  # type: ignore[method-assign]
    orch.browser.youtube_home = lambda: _dry_browser_yt("home")  # type: ignore[method-assign]
    orch.browser.google_search = _dry_browser_google  # type: ignore[method-assign]
    orch.browser.open_url = lambda url="", title="": ToolResult(True, f"Opened {title or url}.")  # type: ignore
    orch.browser.youtube_play = lambda url="", title="": ToolResult(True, f"Playing {title}.")  # type: ignore
    orch.browser.set_preferred_browser = lambda *_a, **_k: None  # type: ignore

    class _DryGmail:
        def search(self, query="in:inbox", max_results=5):
            return ToolResult(
                True,
                "Mail results:\n1. Test",
                {"query": query, "results": [{"id": "1", "title": "Test", "url": ""}]},
            )

        def summarize(self, query="is:unread", max_messages=5):
            return ToolResult(True, "You have 2 messages. Test mail.", {"summary": "You have 2 messages."})

        def compose(self, **kwargs):
            if not kwargs.get("confirmed"):
                return ToolResult(False, "Confirm?", needs_confirm=True)
            return ToolResult(True, "Email sent.")

        def reply(self, **kwargs):
            return ToolResult(True, "Reply sent.")

    import tools.gmail_api as gmail_mod

    gmail_mod.get_gmail = lambda: _DryGmail()  # type: ignore

    results = []
    for case in cases:
        results.append(_run_one(orch, case))

    passed = sum(1 for r in results if r["ok"])
    failed = [r for r in results if not r["ok"]]
    report = {
        "total": len(results),
        "passed": passed,
        "failed": len(failed),
        "failures": failed[:40],
    }
    out = ROOT / "data" / "logs" / "routing_corpus_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Routing corpus: {passed}/{len(results)} passed")
    for r in failed[:25]:
        print(
            f"  FAIL {r['id']}: say={r['say']!r} got intent={r['intent']} "
            f"tools={r['tools']} await={r['awaiting']} why={r['fail_reasons']}"
        )
    print(f"Report → {out}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
