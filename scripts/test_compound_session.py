#!/usr/bin/env python3
"""Regression checks for compound + follow-up session phrases."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["MARC_STEP_GAP"] = "0.05"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laya_router.compound import normalize_transcript, parse_compound
from laya_router.rules import rule_classify
from orchestrator.followup import resolve_followup
from orchestrator.session import SessionState, VideoResult


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    cases = [
        ("open chrome plus gmail", "open_app", 2),
        ("open browser and then open mail", "open_app", 2),
        ("open browser then search email and open it", "open_app", 2),
        ("open Chrome plus Gmail", "open_app", 2),
        ("open youtube", "youtube_home", 1),
        ("open YouTube and search for music", "youtube_search", 1),
        ("search youtube for music", "youtube_search", 1),
        ("open gmail", "open_app", 1),
        ("open notepad and type hello", "type_text", 2),
        ("open youtube on brave", "youtube_home", 2),
        ("search for email", "open_app", 1),
        ("now search for email", "open_app", 1),
        ("play hangover", "youtube_search", 1),
        ("google python tutorial", "web_search", 1),
        ("search for cats on google", "web_search", 1),
        ("go to barcode mode", "camera_barcode", 1),
        ("switch to photo mode", "camera_photo_mode", 1),
        ("stop recording", "camera_stop", 1),
    ]
    for phrase, intent, nsteps in cases:
        p = parse_compound(phrase)
        expect(p is not None, f"no parse: {phrase}")
        assert p is not None
        expect(p["intent"] == intent, f"{phrase}: intent {p['intent']} != {intent}")
        expect(len(p["steps"]) == nsteps, f"{phrase}: steps {len(p['steps'])} != {nsteps}")
        print("OK compound:", phrase)

    # Brave preference + youtube home
    p = parse_compound("open youtube on brave")
    assert p is not None
    expect(p["steps"][0]["tool"] == "set_preferred_browser", "brave pref tool")
    expect(p["steps"][0]["args"]["browser"] == "brave", "brave pref")
    expect(p["steps"][1]["tool"] == "youtube_home", "brave youtube_home")
    print("OK preferred_browser brave + home")

    p = parse_compound("open youtube")
    assert p is not None
    expect(p["steps"][0]["tool"] == "youtube_home", "open youtube → home scrape")
    print("OK open youtube → youtube_home")

    p = parse_compound("google lo-fi music")
    assert p is not None
    expect(p["steps"][0]["tool"] == "google_search", "google → google_search tool")
    print("OK google_search tool")

    # Wake strip: remark open browser
    stripped = normalize_transcript("remark open browser")
    expect(stripped.lower() == "open browser", f"wake strip got {stripped!r}")
    p = parse_compound("remark open browser")
    expect(p is not None and p["intent"] == "open_app", "remark open browser")
    expect(p["steps"][0]["args"]["app"] == "chrome", "remark → chrome")
    print("OK wake strip remark")

    session = SessionState()
    session.set_youtube_results(
        "music",
        [
            {"title": "Lo-fi Hip Hop Mix", "url": "https://www.youtube.com/watch?v=a"},
            {"title": "Jazz Cafe", "url": "https://www.youtube.com/watch?v=b"},
            {"title": "Rock Anthems", "url": "https://www.youtube.com/watch?v=c"},
        ],
    )
    f = resolve_followup("play the first", session)
    expect(f is not None and f["intent"] == "play_video", "play first")
    f = resolve_followup("play the third", session)
    expect(f is not None and "c" in f["steps"][0]["args"]["url"], "play third")
    f = resolve_followup("play the jazz one", session)
    expect(f is not None and "Jazz" in f["steps"][0]["args"]["title"], "play by desc")
    f = resolve_followup("search youtube for drums", session)
    expect(f is not None and f["intent"] == "youtube_search", "yt search followup")
    f = resolve_followup("summarize my email", session)
    expect(f is not None and f["intent"] == "mail_summarize", "mail summarize")
    expect(f["steps"][0]["tool"] == "mail_summarize", "mail summarize tool")
    f = resolve_followup("sleep", session)
    expect(f is not None and f["intent"] == "sleep", "sleep")
    f = resolve_followup("stop listening", session)
    expect(f is not None and f["intent"] == "sleep", "stop listening")
    f = resolve_followup("goodbye", session)
    expect(f is not None and f["intent"] == "sleep", "goodbye")
    f = resolve_followup("search for email", session)
    expect(f is not None and f["steps"][0]["args"]["app"] == "gmail", "search for email")
    print("OK followups")

    # Google open the first
    gsession = SessionState()
    gsession.set_results(
        "google",
        "python",
        [
            {"title": "Python.org", "url": "https://www.python.org"},
            {"title": "Docs", "url": "https://docs.python.org"},
        ],
    )
    f = resolve_followup("open the first", gsession)
    expect(f is not None and f["intent"] == "open_result", "google open first")
    expect(f["steps"][0]["tool"] == "open_url", "google open_url")
    expect("python.org" in f["steps"][0]["args"]["url"], "google first url")
    print("OK google open the first")

    # play hangover with youtube context → youtube_search (not volume_media)
    session2 = SessionState()
    session2.last_site = "youtube"
    f = resolve_followup("play hangover", session2)
    expect(f is not None, "play hangover followup")
    expect(f["intent"] == "youtube_search", f"play hangover intent={f['intent']}")
    expect(f["steps"][0]["tool"] == "youtube_search", "play hangover tool")
    intent, _ = rule_classify("play hangover")
    expect(intent != "volume_media", f"rules must not steal play: {intent}")
    print("OK play hangover → youtube not media")

    # play the first with empty results + youtube context → open home (no play_nth until list exists)
    session3 = SessionState()
    session3.last_site = "youtube"
    session3.awaiting = "none"
    session3.last_results = []
    f = resolve_followup("play the first", session3)
    expect(f is not None and f["intent"] == "youtube_home", "empty list → youtube_home")
    expect(len(f["steps"]) == 1 and f["steps"][0]["tool"] == "youtube_home", "home only")
    print("OK play the first empty youtube → home (ask again)")

    # Empty scrape clears awaiting
    session4 = SessionState()
    session4.set_youtube_results("x", [])
    expect(session4.awaiting == "none", "empty scrape awaiting")
    expect(session4.last_results == [], "empty scrape results")
    print("OK empty scrape session")

    # --- Recent orchestrator fixes ---
    p = parse_compound("open the browser and open the full screen")
    expect(p is not None and p["intent"] == "open_app", "browser+fullscreen intent")
    tools = [s["tool"] for s in p["steps"]]
    expect(tools == ["open_app", "hotkey"], f"browser+fullscreen tools={tools}")
    expect(p["steps"][1]["args"]["action"] == "fullscreen", "fullscreen action")
    print("OK open browser and fullscreen")

    p = parse_compound("open")
    expect(p is not None and p["intent"] == "hold_slot", "bare open hold")
    expect(p.get("awaiting") == "slot:open_app", "slot open_app")
    print("OK bare open hold_slot")

    p = parse_compound("open WhatsApp")
    expect(p is not None and p["steps"][0]["args"]["app"] == "whatsapp", "open whatsapp")
    print("OK open WhatsApp compound")

    f = resolve_followup("search WhatsApp", SessionState())
    expect(f is not None and f["intent"] == "open_app", "search WhatsApp → open")
    expect(f["steps"][0]["args"]["app"] == "whatsapp", "whatsapp app")
    print("OK search WhatsApp → open_app")

    session_g = SessionState()
    session_g.set_results(
        "google",
        "chatgpt",
        [{"title": "A", "url": "https://a.example"}, {"title": "B", "url": "https://b.example"}],
    )
    f = resolve_followup("the first", session_g)
    expect(f is not None and f["intent"] == "open_result", "the first → open_result")
    expect(f["steps"][0]["args"]["url"] == "https://a.example", "first url")
    f = resolve_followup("open the first", session_g)
    expect(f is not None and f["intent"] == "open_result", "open the first")
    print("OK google the first / open the first")

    session_h = SessionState()
    session_h.hold_slot("slot:open_app")
    f = resolve_followup("cancel", session_h)
    expect(f is not None and f["intent"] == "clarify", "cancel while hold → clarify")
    expect(f.get("intent") != "sleep", "cancel not sleep")
    print("OK soft cancel while holding")

    from tools.os_tools import OSTools

    tools_os = OSTools()
    canon, meta = tools_os.resolve_app("water")
    expect(canon != "whatsapp" and meta is None, f"water must not resolve to whatsapp: {canon}")
    print("OK resolve_app water ≠ WhatsApp")

    f = resolve_followup("play the third world", session)
    expect(f is not None and f["intent"] == "play_video", "play third world STT junk")
    expect("c" in f["steps"][0]["args"]["url"], "third world → third result")
    print("OK play the third world → third")

    # Live orchestrator smoke (no laya)
    from orchestrator import MarcOrchestrator
    from laya_router.compound import parse_compound as pc

    for phrase, intent in [
        ("make it full screen", "hotkey"),
        ("start recording", "camera_record"),
        ("switch to video", "camera_video"),
        ("go to barcode mode", "camera_barcode"),
        ("take a photo", "camera_photo"),
        ("fullscreen", "hotkey"),
        ("snap left", "hotkey"),
        ("maximize", "hotkey"),
        ("open wifi settings", "settings"),
        ("read the clipboard", "clipboard"),
    ]:
        p = pc(phrase)
        expect(p is not None, f"no parse: {phrase}")
        expect(p["intent"] == intent, f"{phrase}: {p['intent']} != {intent}")
        # camera_record must force video via camera_record tool
        if intent == "camera_record":
            expect(p["steps"][0]["tool"] == "camera_record", "record tool")
        if intent == "camera_video":
            expect(p["steps"][0]["args"].get("mode") == "video", "video mode arg")
        print("OK compound:", phrase)

    o = MarcOrchestrator(preload_laya=False, speak_fn=lambda m: None)
    r = o.handle("open chrome plus gmail")
    expect(r.source in ("compound", "followup"), f"source={r.source}")
    expect("gmail" in r.reply.lower() or "Opening" in r.reply or "Opened" in r.reply, r.reply)
    print("OK orchestrator:", r.intent, r.spoken)

    r = o.handle("stop listening")
    expect(r.should_continue is False, "stop listening should_continue")
    print("OK stop listening continue=False")

    r = o.handle("open youtube on brave")
    expect(o.session.preferred_browser == "brave", f"pref={o.session.preferred_browser}")
    print("OK orchestrator brave pref")

    # Phase 0: multi-close + search music + next video
    p = parse_compound("close camera and spotify")
    expect(p is not None, "close A and B parse")
    expect(p["steps"][0]["tool"] == "close_apps", f"tool={p['steps'][0]['tool']}")
    apps = p["steps"][0]["args"]["apps"]
    expect(len(apps) == 2, f"apps={apps}")
    print("OK close camera and spotify compound", apps)

    p = parse_compound("switch to the next video")
    expect(p is not None and p["intent"] == "youtube_media", "next video compound")
    expect(p["steps"][0]["args"]["action"] == "next", p["steps"][0])
    print("OK next video compound")

    f = resolve_followup("search music", SessionState())
    expect(f is not None, "search music followup")
    expect(f["intent"] in ("web_search", "youtube_search"), f"intent={f['intent']}")
    expect(f["steps"][0]["tool"] in ("google_search", "youtube_search", "web_search"), f["steps"])
    expect(f["steps"][0].get("args", {}).get("app") != "spotify", "not spotify")
    print("OK search music → search not Spotify")

    p = parse_compound("play music on Spotify")
    expect(p is not None, "spotify music parse")
    expect(p["intent"] != "youtube_search", p)
    expect(p["steps"][0]["tool"] == "open_app", p["steps"])
    expect((p["steps"][0]["args"].get("app") or "").lower() == "spotify", p["steps"][0])
    expect(any(s["tool"] == "volume_media" for s in p["steps"]), p["steps"])
    print("OK play music on Spotify compound")

    p = parse_compound("open Spotify and play music")
    expect(p is not None, "open spotify and play")
    tools = [s["tool"] for s in p["steps"]]
    expect(tools == ["open_app", "volume_media"], f"tools={tools}")
    expect((p["steps"][0]["args"].get("app") or "").lower() == "spotify", p["steps"][0])
    expect((p["steps"][1]["args"].get("action") or "").lower() == "play", p["steps"][1])
    print("OK open Spotify and play music")

    p = parse_compound("play music now")
    expect(p is not None and p["intent"] != "youtube_search", p)
    expect(p["steps"][0]["tool"] == "volume_media", p["steps"])
    print("OK play music now → media not YouTube")

    from orchestrator.session import SessionState as SS
    from orchestrator.followup import resolve_followup as rf

    s = SS()
    s.last_tool = "type_text"
    s.last_typed = "hello"
    f = rf("send it", s)
    expect(f is not None and f["steps"][0]["tool"] == "hotkey", f)
    print("OK send it followup after type")

    s2 = SS()
    s2.awaiting = "pick_video"
    s2.last_site = "youtube"
    s2.last_results = []  # empty — should not sticky-misroute bare yes
    from laya_router.compound import is_confirm

    expect(is_confirm("Yes."), "Yes. punctuation")

    ys = SessionState()
    ys.last_site = "youtube"
    f = resolve_followup("next video", ys)
    expect(f is not None and f["steps"][0]["tool"] == "youtube_media", "yt next followup")
    expect(f["steps"][0]["args"]["action"] == "next", f["steps"][0])
    print("OK next video followup")

    # Phase 2: WhatsApp + click-then-type
    p = parse_compound("message Ranjith on WhatsApp hi")
    expect(p is not None and p["intent"] == "whatsapp_send", f"wa intent={p}")
    expect(p["steps"][0]["tool"] == "whatsapp_send", p["steps"])
    expect(p["steps"][0]["args"]["contact"].lower() == "ranjith", p["steps"][0])
    expect("hi" in p["steps"][0]["args"]["message"].lower(), p["steps"][0])
    print("OK whatsapp message compound")

    p = parse_compound("copy that to whatsapp Mom")
    expect(p is not None and p["steps"][0]["args"].get("from_clipboard"), p)
    expect("mom" in p["steps"][0]["args"]["contact"].lower(), p["steps"][0])
    print("OK whatsapp copy compound")

    p = parse_compound("click then type hello world")
    expect(p is not None and p["steps"][0]["tool"] == "click_then_type", p)
    expect("hello world" in p["steps"][0]["args"]["text"].lower(), p["steps"][0])
    print("OK click then type compound")

    # Phase 4: N-step clause plan
    from laya_router.clause_plan import parse_clause_plan

    p = parse_clause_plan(
        "open browser and search for youtube and on youtube search for samsung"
    )
    expect(p is not None, "clause samsung plan")
    tools = [s["tool"] for s in p["steps"]]
    expect(len(tools) >= 2, f"need multi steps got {tools}")
    expect("open_app" in tools or "youtube_home" in tools, f"browser/yt nav missing: {tools}")
    expect(
        any(
            s["tool"] == "youtube_search" and "samsung" in (s.get("args") or {}).get("query", "").lower()
            for s in p["steps"]
        ),
        f"samsung youtube_search missing: {p['steps']}",
    )
    expect(
        not any(
            "youtube and on youtube" in str((s.get("args") or {}).get("query", "")).lower()
            for s in p["steps"]
        ),
        "must not stuff whole phrase into one google query",
    )
    print("OK clause plan samsung", tools)

    p = parse_clause_plan("open youtube and search for music and play the first")
    expect(p is not None, "yt music play first")
    tools = [s["tool"] for s in p["steps"]]
    expect("youtube_search" in tools, tools)
    expect("play_nth" in tools, tools)
    print("OK clause plan play first", tools)

    p = parse_compound("summarize my email")
    expect(p is not None and p["intent"] == "mail_summarize", p)
    expect(p["steps"][0]["tool"] == "mail_summarize", p["steps"])
    print("OK mail summarize compound")

    f = resolve_followup("summarize my email", SessionState())
    expect(f is not None and f["intent"] == "mail_summarize", f)
    expect(f["steps"][0]["tool"] == "mail_summarize", f["steps"])
    print("OK mail summarize followup")

    p = parse_compound("send email to alex saying hello there")
    expect(p is not None, p)
    # Placeholder / empty contact emails are refused (no fake send)
    if p.get("intent") == "mail_compose":
        expect(p["steps"][0]["tool"] == "mail_compose", p["steps"])
        print("OK mail compose compound")
    else:
        expect(p.get("intent") == "clarify", p)
        expect("contacts.json" in (p.get("reply") or "").lower(), p)
        print("OK mail compose blocked without real email")

    # Direct address still composes
    p = parse_compound("send email to someone@gmail.com saying hello there")
    expect(p is not None and p["intent"] == "mail_compose", p)
    expect(p["steps"][0]["args"]["to"] == "someone@gmail.com", p["steps"][0])
    print("OK mail compose with literal address")

    # Orchestrator end-to-end clause plan
    o2 = MarcOrchestrator(preload_laya=False, speak_fn=lambda m: None)
    r = o2.handle(
        "open browser and search for youtube and on youtube search for samsung"
    )
    expect(r.source == "clause_plan", f"source={r.source}")
    tools = [s.get("tool") for s in (r.steps_run or [])]
    expect(
        any(t == "youtube_search" for t in tools) or "samsung" in (r.reply or "").lower(),
        f"orch samsung steps={tools} reply={r.reply}",
    )
    print("OK orch clause samsung", r.source, tools)

    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
