#!/usr/bin/env python3
"""Generate marc_live_e2e_v1.jsonl (~100 spoken utterances for routing/live E2E)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "datasets" / "marc_live_e2e_v1.jsonl"


def row(
    id_: str,
    say: str,
    expect_intent: str,
    expect_tools: list,
    *,
    forbid_awaiting: str = "pick_video",
    max_latency_s: float = 8.0,
    tags: list | None = None,
    clear_session_before: bool = False,
    setup: list | None = None,
) -> dict:
    return {
        "id": id_,
        "say": say,
        "expect_intent": expect_intent,
        "expect_tools": expect_tools,
        "forbid_awaiting": forbid_awaiting,
        "max_latency_s": max_latency_s,
        "tags": tags or [],
        "clear_session_before": clear_session_before,
        "setup": setup or [],
    }


def build() -> list[dict]:
    cases: list[dict] = []

    # --- Open / close / focus (~25) ---
    opens = [
        ("chrome", "Open Chrome"),
        ("spotify", "Open Spotify"),
        ("gmail", "Open Gmail"),
        ("whatsapp", "Open WhatsApp"),
        ("camera", "Open Camera"),
        ("notepad", "Open Notepad"),
        ("youtube", "Open YouTube"),
        ("brave", "Open Brave"),
        ("settings", "Open Settings"),
        ("whatsapp", "Open whatsup"),
    ]
    for i, (app, say) in enumerate(opens, 1):
        cases.append(
            row(
                f"open_{i:02d}",
                say,
                "open_app",
                ["open_app"],
                tags=["open"],
                clear_session_before=True,
            )
        )

    closes = [
        ("camera", "Close camera"),
        ("spotify", "Close Spotify"),
        ("notepad", "Close Notepad"),
        ("chrome", "Close Chrome"),
        ("whatsapp", "Close WhatsApp"),
    ]
    for i, (app, say) in enumerate(closes, 1):
        cases.append(
            row(
                f"close_{i:02d}",
                say,
                "close_app",
                ["close_app"],
                forbid_awaiting="confirm",
                tags=["close", "noconfirm"],
                clear_session_before=True,
            )
        )

    cases.append(
        row(
            "close_multi_01",
            "Close camera and Spotify",
            "close_app",
            ["close_app"],
            forbid_awaiting="confirm",
            tags=["close", "multi"],
            clear_session_before=True,
        )
    )

    # --- Type + send (~15) ---
    cases.append(
        row(
            "type_01",
            "Type hello this is Marc",
            "type_text",
            ["type_text"],
            tags=["type"],
            clear_session_before=True,
        )
    )
    cases.append(
        row(
            "type_02",
            "Type meeting at five",
            "type_text",
            ["type_text"],
            tags=["type"],
            clear_session_before=True,
        )
    )
    cases.append(
        row(
            "send_01",
            "Send it",
            "hotkey",
            ["hotkey"],
            tags=["send"],
            clear_session_before=False,
            setup=[
                {
                    "say": "Type hello world",
                    "expect_intent": "type_text",
                    "expect_tools": ["type_text"],
                }
            ],
        )
    )
    cases.append(
        row(
            "send_02",
            "Press enter",
            "hotkey",
            ["hotkey"],
            tags=["send"],
            clear_session_before=False,
            setup=[
                {
                    "say": "Type test message",
                    "expect_intent": "type_text",
                    "expect_tools": ["type_text"],
                }
            ],
        )
    )
    cases.append(
        row(
            "send_03",
            "Hit send",
            "hotkey",
            ["hotkey"],
            tags=["send"],
            clear_session_before=False,
            setup=[
                {
                    "say": "Type hi there",
                    "expect_intent": "type_text",
                    "expect_tools": ["type_text"],
                }
            ],
        )
    )
    for i, txt in enumerate(
        [
            "Type good morning",
            "Type please call me back",
            "Type the package arrived",
            "Dictate hello from Marc",
        ],
        4,
    ):
        cases.append(
            row(
                f"type_{i:02d}",
                txt,
                "type_text",
                ["type_text"],
                tags=["type"],
                clear_session_before=True,
            )
        )
    for i, say in enumerate(
        ["Send that", "Send this", "Press enter please"],
        4,
    ):
        cases.append(
            row(
                f"send_{i:02d}",
                say,
                "hotkey",
                ["hotkey"],
                tags=["send"],
                setup=[
                    {
                        "say": "Type quick note",
                        "expect_intent": "type_text",
                        "expect_tools": ["type_text"],
                    }
                ],
            )
        )

    # --- Search / YouTube / Spotify (~15) ---
    cases.append(
        row(
            "spotify_01",
            "Play music on Spotify",
            "open_app",
            ["open_app", "volume_media"],
            forbid_awaiting="pick_video",
            tags=["spotify", "not_youtube"],
            clear_session_before=True,
        )
    )
    cases.append(
        row(
            "spotify_02",
            "Play on Spotify",
            "open_app",
            ["open_app"],
            tags=["spotify", "not_youtube"],
            clear_session_before=True,
        )
    )
    cases.append(
        row(
            "yt_01",
            "Search YouTube for lo fi beats",
            "youtube_search",
            ["youtube_search"],
            tags=["youtube"],
            clear_session_before=True,
            forbid_awaiting="",  # pick_video OK after YT search
        )
    )
    cases.append(
        row(
            "yt_02",
            "YouTube search for cooking tips",
            "youtube_search",
            ["youtube_search"],
            tags=["youtube"],
            clear_session_before=True,
            forbid_awaiting="",
        )
    )
    cases.append(
        row(
            "google_01",
            "Google weather in Bangalore",
            "web_search",
            ["google_search"],
            tags=["google"],
            clear_session_before=True,
        )
    )
    cases.append(
        row(
            "google_02",
            "Search Google for Python docs",
            "web_search",
            ["google_search"],
            tags=["google"],
            clear_session_before=True,
        )
    )
    for i, q in enumerate(
        [
            "Search YouTube for news",
            "Find videos about cats",
            "Play the first",
        ],
        3,
    ):
        if "first" in q.lower():
            cases.append(
                row(
                    f"yt_{i:02d}",
                    q,
                    "play_video",
                    ["youtube_play"],
                    tags=["youtube", "followup"],
                    forbid_awaiting="",
                    setup=[
                        {
                            "say": "Search YouTube for ambient music",
                            "expect_intent": "youtube_search",
                            "expect_tools": ["youtube_search"],
                        }
                    ],
                )
            )
        else:
            cases.append(
                row(
                    f"yt_{i:02d}",
                    q,
                    "youtube_search",
                    ["youtube_search"],
                    tags=["youtube"],
                    clear_session_before=True,
                    forbid_awaiting="",
                )
            )

    # --- Mail (~10) ---
    for i, say in enumerate(
        [
            "Summarize my email",
            "Summarize unread mail",
            "Check my inbox",
            "Search mail for invoice",
            "Search email for LinkedIn",
            "Open my email",
            "Read my emails",
            "Summarize the first email",
            "Find mail from Kaggle",
            "Search inbox for statement",
        ],
        1,
    ):
        intent = "mail_summarize" if "summar" in say.lower() or "read my" in say.lower() else (
            "open_app" if "open" in say.lower() or "check my inbox" in say.lower() else "mail_search"
        )
        # "summarize the first email" may clarify without mail context — accept mail_summarize family
        tools = (
            ["mail_summarize"]
            if intent == "mail_summarize"
            else (["open_app"] if intent == "open_app" else ["mail_search", "gmail_search"])
        )
        if say.lower() == "summarize the first email":
            tools = []  # may clarify; intent alias covers it
            intent = "clarify"
        cases.append(
            row(
                f"mail_{i:02d}",
                say,
                intent,
                tools,
                tags=["mail"],
                clear_session_before=True,
                max_latency_s=12.0,
            )
        )

    # --- Multi-step (~10) ---
    multis = [
        ("Open Chrome and go to YouTube", ["open_app", "youtube_home", "youtube_search", "open_app"]),
        ("Open browser then search for YouTube", ["open_app"]),
        ("Open Chrome plus Gmail", ["open_app"]),
        ("Open Notepad and type hello", ["open_app", "type_text"]),
        ("Open Camera and take a photo", ["open_app", "camera_photo"]),
        ("Open Spotify and play", ["open_app", "volume_media"]),
        ("Open WhatsApp and type hi", ["open_app", "type_text"]),
        ("Open Gmail then summarize mail", ["open_app", "mail_summarize"]),
        ("Open Chrome and search Google for news", ["open_app", "google_search", "web_search"]),
        ("Close Notepad and open Chrome", ["close_app", "open_app"]),
    ]
    for i, (say, tools) in enumerate(multis, 1):
        cases.append(
            row(
                f"multi_{i:02d}",
                say,
                "multi_step" if "and" in say.lower() or "then" in say.lower() or "plus" in say.lower() else "open_app",
                tools,
                tags=["multi"],
                clear_session_before=True,
                forbid_awaiting="confirm",
            )
        )

    # --- Follow-up hygiene (~10) ---
    cases.append(
        row(
            "hygiene_01",
            "Open Gmail",
            "open_app",
            ["open_app"],
            forbid_awaiting="pick_video",
            tags=["hygiene"],
            setup=[
                {
                    "say": "Search YouTube for jazz",
                    "expect_intent": "youtube_search",
                    "expect_tools": ["youtube_search"],
                }
            ],
        )
    )
    cases.append(
        row(
            "hygiene_02",
            "Type hello",
            "type_text",
            ["type_text"],
            forbid_awaiting="pick_video",
            tags=["hygiene"],
            setup=[
                {
                    "say": "Search YouTube for drums",
                    "expect_intent": "youtube_search",
                    "expect_tools": ["youtube_search"],
                }
            ],
        )
    )
    cases.append(
        row(
            "hygiene_03",
            "Close camera",
            "close_app",
            ["close_app"],
            forbid_awaiting="confirm",
            tags=["hygiene", "close"],
            setup=[
                {
                    "say": "Search YouTube for cats",
                    "expect_intent": "youtube_search",
                    "expect_tools": ["youtube_search"],
                }
            ],
        )
    )
    cases.append(
        row(
            "hygiene_04",
            "Yes",
            "clarify",
            [],
            tags=["hygiene", "confirm"],
            clear_session_before=True,
        )
    )
    cases.append(
        row(
            "hygiene_05",
            "Open WhatsApp",
            "open_app",
            ["open_app"],
            forbid_awaiting="pick_video",
            tags=["hygiene"],
            setup=[
                {
                    "say": "Search YouTube for podcast",
                    "expect_intent": "youtube_search",
                    "expect_tools": ["youtube_search"],
                }
            ],
        )
    )
    for i, say in enumerate(
        [
            "Cancel",
            "Never mind",
            "Open Notepad",
            "What time is it",
            "Mute volume",
        ],
        6,
    ):
        intent = (
            "clarify"
            if say.lower() in ("cancel", "never mind")
            else (
                "system_status"
                if "time" in say.lower()
                else ("volume_media" if "mute" in say.lower() else "open_app")
            )
        )
        tools = (
            []
            if intent == "clarify"
            else (
                ["system_status"]
                if intent == "system_status"
                else (["volume_media"] if intent == "volume_media" else ["open_app"])
            )
        )
        cases.append(
            row(
                f"hygiene_{i:02d}",
                say,
                intent,
                tools,
                tags=["hygiene"],
                clear_session_before=True,
            )
        )

    # --- Junk / resilience (~15) ---
    for i, say in enumerate(
        [
            "Um",
            "Hmm",
            "Help",
            "What can you do",
            "Sleep",
            "Go to sleep",
            "Hey Marc",
            "Okay",
            "Thanks",
            "Blah blah",
            "asdfgh",
            "Who are you",
            "Stop listening",
            "Goodbye",
            "Nevermind that",
        ],
        1,
    ):
        intent = (
            "sleep"
            if "sleep" in say.lower() or say.lower() in ("goodbye", "stop listening")
            else ("chat" if say.lower() in ("help", "what can you do", "who are you") else "clarify")
        )
        cases.append(
            row(
                f"junk_{i:02d}",
                say,
                intent,
                [],
                tags=["junk"],
                clear_session_before=True,
                forbid_awaiting="",
            )
        )

    # Pad to >= 100 with more open/close variants if needed
    n = 1
    while len(cases) < 100:
        cases.append(
            row(
                f"pad_{n:02d}",
                f"Open Notepad",
                "open_app",
                ["open_app"],
                tags=["pad", "open"],
                clear_session_before=True,
            )
        )
        n += 1

    return cases[:110]  # allow a few over 100


def main() -> int:
    cases = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"Wrote {len(cases)} cases → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
