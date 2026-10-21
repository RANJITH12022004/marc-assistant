"""Edith / Jarvis style short spoken replies."""
from __future__ import annotations

import random
import re
from typing import Any, Dict, Optional


def _short(text: str, limit: int = 160) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def speakable(text: str) -> str:
    """Strip long help / markdown for TTS."""
    if not text:
        return ""
    if "\n" in text and len(text) > 120:
        first = text.split("\n", 1)[0].strip()
        return _short(first, 120)
    return _short(text, 180)


def closer_for(
    intent: str,
    tool_ok: bool,
    message: str = "",
    *,
    awaiting: str = "none",
    site: str = "",
    query: str = "",
) -> str:
    """Return a short Edith-style follow-up after an action."""
    msg = message.strip()
    low_intent = (intent or "").lower()

    # Always speak confirm prompts verbatim
    if "confirm to proceed" in msg.lower():
        return speakable(msg)

    if not tool_ok and low_intent not in ("clarify", "chat", "refuse", "sleep"):
        # Pending confirm questions must be spoken as-is
        if "confirm to proceed" in msg.lower():
            return speakable(msg)
        return random.choice(
            [
                "That didn't work. Want another try?",
                "Something went wrong. What next?",
                "I hit a snag. Anything else?",
            ]
        )

    if low_intent in ("sleep", "stop", "goodbye"):
        return random.choice(
            [
                "Going quiet. Say hey marc when you need me.",
                "Standing down.",
                "I'll be here.",
            ]
        )

    if low_intent == "refuse":
        return "I won't do that. What else can I help with?"

    if low_intent == "clarify":
        # Prefer explicit message when provided (e.g. empty scrape / no list)
        if msg and len(msg) > 12 and not msg.lower().startswith("i didn't"):
            return speakable(msg)
        return random.choice(
            [
                "I didn't catch that. Try again.",
                "Say that again?",
                "Hmm — one more time?",
            ]
        )

    # Only attach pick-video closer for THIS turn's youtube search / when awaiting
    # was set by a successful scrape this turn
    if low_intent in ("youtube_search", "youtube_home") and awaiting == "pick_video":
        q = query or "that"
        if low_intent == "youtube_home":
            return "YouTube home is open. Say play the first, or describe the video."
        return f"Showing YouTube results for {q}. Say play the first, or describe the video."

    if low_intent in ("youtube_search",) and awaiting != "pick_video":
        # Empty scrape / honest failure path
        if msg and ("couldn't read" in msg.lower() or "say the video" in msg.lower()):
            return speakable(msg)
        return f"Opened YouTube search for {query or 'that'}. Say the video name if you want me to play one."

    if low_intent in ("youtube_home",) and awaiting != "pick_video":
        if msg and "couldn't read" in msg.lower():
            return speakable(msg)
        return "Opened YouTube. Say search for a title, or play the first if the feed loaded."

    if low_intent in ("web_search",) and site == "youtube":
        return f"YouTube results for {query or 'your search'}. Which one should I play?"

    if low_intent in ("web_search",) and (site == "google" or awaiting == "pick_result"):
        return f"Google results for {query or 'your search'}. Say open the first or second."

    if low_intent == "open_result":
        return "Opened. What next?"

    if low_intent in ("play_video", "youtube_play"):
        return random.choice(
            [
                "Playing. Anything else?",
                "On it. What next?",
                "Playing now. Need anything else?",
            ]
        )

    if low_intent == "open_app":
        name = ""
        m = re.search(r"(?:Opened|Opening)\s+([^.]+)", msg, re.I)
        if m:
            name = m.group(1).strip()
        # Multi-step open+play: keep short
        if "playing" in msg.lower() or "and play" in msg.lower():
            return "Done."
        if name:
            return f"Opened {name}."
        return "Opened."

    if low_intent == "type_text":
        return "Typed."

    if low_intent == "close_app":
        return "Closed."

    if low_intent == "hotkey":
        return "Done."

    if low_intent == "volume_media":
        low = msg.lower()
        if "pause" in low:
            return "Paused."
        if "play" in low:
            return "Playing."
        return "Done."

    if low_intent == "system_status":
        core = speakable(msg)
        return f"{core}" if core else "Done."

    if low_intent == "chat":
        return speakable(msg) or "What next?"

    if low_intent == "mail_summarize_blocked":
        return (
            "Authorize Gmail first with python main.py gmail-auth, "
            "then ask me to summarize again."
        )

    if low_intent == "mail_summarize" and msg:
        return speakable(msg)

    if low_intent == "mail_compose" and msg:
        return speakable(msg)

    # Never leak a stale pick_video closer onto unrelated intents
    if msg and len(msg) < 80 and not msg.lower().startswith("opening"):
        # Keep rapid OS replies short (no trailing "What next?")
        if low_intent in (
            "close_app",
            "hotkey",
            "volume_media",
            "open_app",
            "type_text",
            "focus_window",
            "camera_photo",
            "camera_mode",
            "open_last_photo",
            "settings",
            "clipboard",
        ):
            return speakable(msg)
        return f"{speakable(msg)} What next?"
    return random.choice(
        [
            "Done.",
            "All set.",
            "Finished.",
        ]
    )


def wake_greeting() -> str:
    return random.choice(
        [
            "Yes?",
            "Listening.",
            "I'm here.",
            "Go ahead.",
        ]
    )


def ready_line() -> str:
    return "Marc is ready. Say hey marc or hey jarvis when you need me."
