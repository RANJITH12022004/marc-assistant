"""Rule-based intent + slot extraction for MVP and Laya fallback."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from laya_router.intents import INTENT_LABELS
from laya_router.synonyms import expand_app_query

_OPEN = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|start|run|fire up|bring up)\s+(.+)$",
    re.I,
)
_SEARCH = re.compile(
    r"^\s*(?:please\s+)?(?:search(?:\s+(?:for|on))?\s+|google\s+|look up\s+)(.+)$",
    re.I,
)
_YT = re.compile(
    r"^\s*(?:please\s+)?(?:search|find|play)?\s*(?:on\s+)?youtube\s+(?:for\s+)?(.+)$",
    re.I,
)
_TYPE = re.compile(
    r"^\s*(?:please\s+)?(?:type|write|dictate|enter)\s+(.+)$",
    re.I,
)
_HOTKEY = re.compile(
    r"^\s*(?:please\s+)?(?:press|hit|do)\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)?(.+)$",
    re.I,
)
_COPY_PASTE = re.compile(
    r"^\s*(copy|paste|cut|undo|redo|save|select all|screenshot|"
    r"take a screenshot|new tab|close tab|refresh|fullscreen|full screen|"
    r"lock|emoji|task manager|find|new window|close window|show desktop|"
    r"snap left|snap right|maximize|minimize|task view|"
    r"address bar|mute|unmute|volume up|volume down|"
    r"alt tab|new desktop|close desktop|"
    r"switch desktop left|switch desktop right|"
    r"open explorer|open settings|run dialog|"
    r"play pause|next track|previous track)\s*$",
    re.I,
)
_FIND_FILE = re.compile(
    r"^\s*(?:please\s+)?(?:find|locate|search for)\s+(?:the\s+)?file\s+(.+)$",
    re.I,
)
_OPEN_FILE = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch)\s+(?:the\s+)?file\s+(.+)$",
    re.I,
)
_CLIPBOARD = re.compile(
    r"^\s*(?:please\s+)?(?:read|show|what(?:'s|\s+is)\s+on)\s+(?:the\s+)?clipboard|"
    r"^\s*(?:please\s+)?(?:copy|write|put)\s+(?:this\s+)?(?:to\s+)?(?:the\s+)?clipboard\b|"
    r"^\s*(?:please\s+)?clipboard\b",
    re.I,
)
_STATUS = re.compile(
    r"^\s*(?:what(?:'s|\s+is)?\s+)?(?:the\s+)?(time|battery|volume|date)(?:\s+is\s+it)?\??\s*$",
    re.I,
)
_VOLUME = re.compile(
    r"^\s*(?:please\s+)?(?:set\s+)?(?:volume|mute|unmute)\b(.*)$|"
    r"^\s*(?:please\s+)?(?:pause|next|previous)\s+(?:track|song|music|media)\b(.*)$|"
    r"^\s*(?:please\s+)?(?:pause\s+music|play\s+music|media\s+(?:play|pause))\b(.*)$|"
    r"^\s*(?:please\s+)?volume\s+(?:up|down|\d+)\b(.*)$",
    re.I,
)
_SETTINGS = re.compile(
    r"^\s*(?:please\s+)?(?:open\s+)?(?:windows\s+)?settings(?:\s+(?:for|to|->)?\s*(wifi|wi-fi|bluetooth|display|sound|apps|privacy|network))?\s*$|"
    r"^\s*(?:please\s+)?(?:open\s+)?(wifi|wi-fi|bluetooth|display)\s+settings\s*$",
    re.I,
)
_CLOSE = re.compile(
    r"^\s*(?:please\s+|now\s+)*(?:close|quit|exit|kill)\s+(.+)$",
    re.I,
)
_FOCUS = re.compile(
    r"^\s*(?:please\s+)?(?:focus|switch to|go to|bring)\s+(.+?)(?:\s+to\s+front)?\s*$",
    re.I,
)
_ORDINAL_APP = re.compile(
    r"^(?:the\s+)?(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|\d+)$",
    re.I,
)
_REFUSE = re.compile(
    r"(format\s+(the\s+)?(disk|drive)|delete\s+(everything|system|all)|"
    r"rm\s+-rf|shutdown\s+now|wipe\s+(the\s+)?(disk|drive)|"
    r"send\s+(all\s+)?(my\s+)?(emails?|passwords?)|system32|"
    r"shut\s+down\s+(?:my\s+)?(?:system|computer|pc|laptop))",
    re.I,
)


def rule_classify(transcript: str) -> Tuple[str, float]:
    t = transcript.strip()
    if not t:
        return "clarify", 0.9
    if _REFUSE.search(t):
        return "refuse", 0.95
    if _CLIPBOARD.search(t):
        return "clipboard", 0.9
    if _OPEN_FILE.search(t):
        return "file_open", 0.88
    if _YT.search(t) or _SEARCH.search(t):
        return "web_search", 0.9
    if _TYPE.search(t):
        return "type_text", 0.88
    if _COPY_PASTE.match(t) or _HOTKEY.search(t):
        return "hotkey", 0.9
    if _FIND_FILE.search(t):
        return "file_find", 0.85
    if _STATUS.match(t):
        return "system_status", 0.92
    if _VOLUME.match(t):
        return "volume_media", 0.88
    if _SETTINGS.match(t):
        return "settings", 0.9
    if _CLOSE.search(t):
        return "close_app", 0.85
    m_focus = _FOCUS.search(t)
    if m_focus:
        app = (m_focus.group(1) or "").strip()
        app = re.sub(r"\s+to\s+front$", "", app, flags=re.I).strip()
        # "go to second" is an ordinal pick, not focus_window
        if _ORDINAL_APP.match(app):
            return "clarify", 0.7
        return "focus_window", 0.85
    if _OPEN.search(t):
        return "open_app", 0.9
    if t.endswith("?") or t.lower().startswith(("what ", "who ", "why ", "how ", "tell me")):
        return "chat", 0.75
    return "clarify", 0.55


def extract_slots(transcript: str, intent: Optional[str] = None) -> Dict[str, Any]:
    t = transcript.strip()
    if intent is None:
        intent, _ = rule_classify(t)

    slots: Dict[str, Any] = {"intent": intent, "raw": t}

    if intent == "open_app":
        m = _OPEN.search(t)
        app = (m.group(1) if m else t).strip(" .")
        slots["app"] = expand_app_query(app)
    elif intent == "close_app":
        m = _CLOSE.search(t)
        slots["app"] = expand_app_query((m.group(1) if m else t).strip(" ."))
    elif intent == "focus_window":
        m = _FOCUS.search(t)
        app = (m.group(1) if m else t).strip(" .")
        app = re.sub(r"\s+to\s+front$", "", app, flags=re.I)
        slots["app"] = expand_app_query(app)
    elif intent == "web_search":
        yt = _YT.search(t)
        if yt:
            slots["engine"] = "youtube"
            slots["query"] = yt.group(1).strip(" .")
        else:
            m = _SEARCH.search(t)
            slots["engine"] = "google"
            slots["query"] = (m.group(1) if m else t).strip(" .")
            if re.search(r"\bon youtube\b", t, re.I):
                slots["engine"] = "youtube"
                slots["query"] = re.sub(r"\s+on youtube\s*$", "", slots["query"], flags=re.I)
    elif intent == "type_text":
        m = _TYPE.search(t)
        text = (m.group(1) if m else t).strip()
        text = re.sub(r"^['\"]|['\"]$", "", text)
        slots["text"] = text
    elif intent == "hotkey":
        m = _COPY_PASTE.match(t) or _HOTKEY.search(t)
        action = (m.group(1) if m else t).strip(" .").lower()
        if action in ("take a screenshot", "screenshot"):
            action = "screenshot"
        if action in ("full screen", "fullscreen"):
            action = "fullscreen"
        if action == "show desktop":
            action = "desktop"
        if action == "unmute":
            action = "mute"  # toggle via same media key
        slots["action"] = action
    elif intent == "file_find":
        m = _FIND_FILE.search(t)
        slots["query"] = (m.group(1) if m else t).strip(" .")
    elif intent == "file_open":
        m = _OPEN_FILE.search(t)
        slots["query"] = (m.group(1) if m else t).strip(" .")
    elif intent == "clipboard":
        low = t.lower()
        if "write" in low or "put" in low or ("copy" in low and "clipboard" in low):
            slots["action"] = "write"
            m = re.search(r"clipboard\s+(.+)$", t, re.I)
            slots["text"] = (m.group(1).strip() if m else "")
        else:
            slots["action"] = "read"
    elif intent == "system_status":
        m = _STATUS.match(t)
        slots["metric"] = (m.group(1) if m else "time").lower()
    elif intent == "volume_media":
        low = t.lower()
        if "mute" in low and "unmute" not in low:
            slots["action"] = "mute"
        elif "unmute" in low:
            slots["action"] = "unmute"
        elif "pause" in low:
            slots["action"] = "pause"
        elif re.search(r"\bplay\b", low):
            slots["action"] = "play"
        elif "next" in low:
            slots["action"] = "next"
        elif "previous" in low or "prev" in low:
            slots["action"] = "previous"
        else:
            m = re.search(r"(\d{1,3})", t)
            slots["action"] = "set"
            slots["level"] = int(m.group(1)) if m else 50
    elif intent == "settings":
        m = _SETTINGS.match(t)
        page = "home"
        if m:
            g = next((x for x in m.groups() if x), None)
            if g:
                page = g.lower().replace("wi-fi", "wifi")
        slots["page"] = page

    return slots


def describe_intents() -> str:
    lines = ["I can help with:"]
    for k, v in INTENT_LABELS.items():
        if k in ("refuse", "clarify"):
            continue
        lines.append(f"  - {k}: {v}")
    return "\n".join(lines)
