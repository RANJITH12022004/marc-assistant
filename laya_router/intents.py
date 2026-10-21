"""Marc intent taxonomy and Laya question schemas (v4)."""
from __future__ import annotations

from typing import Any, Dict

INTENT_LABELS: Dict[str, str] = {
    "open_app": "launch a desktop app, program, or browser",
    "close_app": "close or quit an application window",
    "focus_window": "bring an already-open app window to the front",
    "web_search": "search Google or the general web (not YouTube-specific)",
    "web_navigate": "go to a known site like YouTube or Gmail without a search query",
    "youtube_search": "search or find videos on YouTube",
    "youtube_media": "play pause next or previous video on YouTube",
    "play_video": "play a specific YouTube or search result by ordinal or title",
    "type_text": "type or dictate text into the focused window",
    "hotkey": "press a keyboard shortcut like copy, paste, or screenshot",
    "file_find": "search for files on the computer",
    "file_open": "open a specific file or folder path",
    "system_status": "ask about time, battery, volume, or system info",
    "volume_media": "change volume or play pause skip system media keys",
    "clipboard": "read or write the clipboard",
    "settings": "open Windows settings pages",
    "mail_search": "search the Gmail inbox by keyword",
    "mail_summarize": "summarize unread or recent emails",
    "mail_compose": "compose or send an email to someone",
    "whatsapp_send": "send a WhatsApp message to a contact",
    "multi_step": "chained multi-action request with and/then (needs a plan)",
    "clarify": "the request is ambiguous and needs a clarifying question",
    "chat": "general conversation with no OS side effects",
    "refuse": "unsafe, destructive, or out-of-policy request",
}

SIMPLE_AUTO_INTENTS = {
    "open_app",
    "close_app",
    "web_search",
    "web_navigate",
    "youtube_search",
    "youtube_media",
    "system_status",
    "volume_media",
    "settings",
    "focus_window",
    "hotkey",
    "type_text",
    "mail_search",
    "mail_summarize",
}

PLANNER_INTENTS = {
    "chat",
    "clarify",
    "file_find",
    "file_open",
    "clipboard",
    "multi_step",
    "mail_compose",
}


def marc_intent_questions() -> Dict[str, Any]:
    """Typed questions for Laya System-1 routing."""
    return {
        "intent": {
            "type": "choice",
            "instructions": "What should Marc do with the user utterance in `transcript`?",
            "criteria": INTENT_LABELS,
        },
        "needs_planner": {
            "type": "noul",
            "instructions": (
                "Does this need multi-step planning, missing slots, or complex reasoning "
                "beyond a single simple OS action? Score high for and/then chains."
            ),
        },
        "needs_confirm": {
            "type": "noul",
            "instructions": (
                "Should Marc ask the user to confirm before acting "
                "(close app, send email, send WhatsApp, destructive)?"
            ),
        },
        "is_multi_step": {
            "type": "noul",
            "instructions": (
                "Does the utterance chain two or more actions with and/then/plus "
                "(e.g. open browser then search YouTube)?"
            ),
        },
        "destructive": {
            "type": "noul",
            "instructions": (
                "Would obeying this delete files, format disks, shut down, send all emails, "
                "or otherwise cause irreversible harm?"
            ),
        },
    }


def state_from_transcript(transcript: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"transcript": transcript.strip()}
    payload.update(extra)
    return payload
