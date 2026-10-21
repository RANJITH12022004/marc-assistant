"""Compound / multi-step command parsing (no Gemini required)."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple


def _step_gap(preferred: float = 0.7) -> float:
    """Inter-step wait after previous tool finishes. MARC_STEP_GAP overrides (tests use 0.05)."""
    raw = os.getenv("MARC_STEP_GAP")
    if raw is not None and str(raw).strip() != "":
        try:
            return float(raw)
        except ValueError:
            pass
    return preferred

# Strip wake-word / name prefixes from STT (incl. remark / partial hey marc)
_WAKE = re.compile(
    r"^\s*(?:hey\s+)?(?:mark|marc|jarvis|edith|hammer|ok\s+marc|okay\s+marc|"
    r"remark|hey\s+marc)[,:]?\s+",
    re.I,
)

_TIME = re.compile(
    r"(?:what(?:'s|\s+is)?\s+)?(?:the\s+)?time(?:\s+(?:is\s+it|right\s+now))?",
    re.I,
)

# open X and search/google/look up Y
_OPEN_AND_SEARCH = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|start)\s+(.+?)\s+and\s+"
    r"(?:then\s+)?(?:search(?:\s+(?:for|on))?\s+|google\s+|look up\s+|type in(?:\s+the)?\s+search(?:\s+bar)?\s+|in the search bar type\s+|search for\s+)"
    r"(.+?)(?:\s+and\s+enter)?\s*$",
    re.I,
)

# open chrome and in the search bar type X and enter
_OPEN_SEARCH_BAR = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|start)\s+(.+?)\s+and\s+"
    r"(?:in\s+(?:the\s+)?search\s+bar\s+)?(?:type|enter|search(?:\s+for)?)\s+(.+?)(?:\s+and\s+enter)?\s*$",
    re.I,
)

# open youtube / open youtube and search X
_OPEN_YT = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|go to|play)\s+youtube(?:\s+and\s+(?:search(?:\s+for)?\s+|find\s+)(.+))?\s*$",
    re.I,
)

# search youtube for X / youtube search X
_YT_SEARCH = re.compile(
    r"^\s*(?:please\s+)?(?:search|find|play)?\s*(?:on\s+)?youtube\s+(?:for\s+)?(.+)$|"
    r"^\s*(?:please\s+)?(?:search|find)\s+(.+?)\s+on\s+youtube\s*$|"
    r"^\s*(?:please\s+)?youtube\s+(.+)$",
    re.I,
)

# open gmail / email / mail
_OPEN_MAIL = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|go to|check)\s+(?:my\s+)?(?:gmail|email|mail|inbox)\s*$",
    re.I,
)

# open X and fullscreen / maximize / new tab / mute (second clause is action, not app)
_OPEN_AND_ACTION = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|start)\s+(.+?)\s+"
    r"(?:and(?:\s+then)?|then|plus|,)\s+"
    r"(?:also\s+)?(?:open\s+(?:the\s+)?|make\s+(?:it\s+)?|go\s+)?"
    r"(?:the\s+)?(full[\s-]*screen|fullscreen|maximize|minimize|new\s+tab|mute|unmute)\s*$",
    re.I,
)

# Trailing "and" / "then" with nothing after → hold for continuation
_INCOMPLETE_AND = re.compile(
    r"^\s*(?:please\s+)?(.+?)\s+(?:and(?:\s+then)?|then)\s*$",
    re.I,
)

# Trailing incomplete second verb: "open browser and open" / "… and search"
_INCOMPLETE_AND_VERB = re.compile(
    r"^\s*(?:please\s+)?(.+?)\s+(?:and(?:\s+then)?|then)\s+"
    r"(?:also\s+)?(open|launch|start|search|find|type|write|close|focus)\s*$",
    re.I,
)

# Bare incomplete verbs
_BARE_VERB = re.compile(
    r"^\s*(?:please\s+)?(open|launch|start|search|find|type|write|close|focus)\s*$",
    re.I,
)

_ACTION_HOTKEY = {
    "full screen": "fullscreen",
    "fullscreen": "fullscreen",
    "maximize": "maximize",
    "minimize": "minimize",
    "new tab": "new tab",
    "mute": "mute",
    "unmute": "unmute",
}

# open browser and open mail / open chrome and open youtube / then / plus
_OPEN_AND_OPEN = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|start)\s+(.+?)\s+"
    r"(?:and(?:\s+then)?|then|plus|,)\s+"
    r"(?:also\s+)?(?:open|launch|start|go to\s+)?(.+)\s*$",
    re.I,
)

# close camera and spotify / now close the camera and spotify
_CLOSE_AND = re.compile(
    r"^\s*(?:please\s+|now\s+)*(?:close|quit|exit|kill)\s+(?:the\s+)?(.+?)\s+"
    r"(?:and(?:\s+then)?|then|plus|,)\s+(?:also\s+)?(?:close\s+)?(?:the\s+)?(.+)\s*$",
    re.I,
)

# next / previous video on YouTube
_NEXT_PREV_VIDEO = re.compile(
    r"^\s*(?:please\s+)?(?:switch\s+to\s+(?:the\s+)?)?(?:next|previous|prev)\s+(?:video|one|track)?\s*$|"
    r"^\s*(?:please\s+)?(?:play\s+)?(?:the\s+)?(?:next|previous|prev)\s+(?:video|one)\s*$|"
    r"^\s*(?:please\s+)?(?:skip|next)\s+(?:this\s+)?(?:video)?\s*$",
    re.I,
)

# open browser then search email and open it → chrome + gmail
_OPEN_THEN_MAIL = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?(?:browser|chrome|brave|edge)"
    r".*?\b(?:mail|email|gmail|inbox)\b",
    re.I,
)

# open X then/plus Y (two apps without second "open")
_OPEN_PLUS = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|start)\s+(.+?)\s+(?:plus|then|,)\s+(.+)\s*$",
    re.I,
)

# open youtube and search for X (prefer youtube_search tool)
_OPEN_YT_SEARCH = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|go to)\s+youtube\s+and\s+"
    r"(?:then\s+)?(?:search(?:\s+for)?|find)\s+(.+?)(?:\s+and\s+play.*)?\s*$",
    re.I,
)

# open notepad and type X / in notepad type X
_OPEN_AND_TYPE = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|start)\s+(.+?)\s+and\s+(?:then\s+)?(?:type|write|dictate)\s+(.+)\s*$",
    re.I,
)

_TYPE_CLEAN = re.compile(
    r"^\s*(?:please\s+)?(?:now\s+)?(?:on\s+(?:the\s+)?(?:opened\s+)?(?:new\s+)?window\s+)?"
    r"(?:please\s+)?(?:type|write|dictate|enter)\s+(.+)$",
    re.I,
)

# click then type / click and type / point and type
_CLICK_THEN_TYPE = re.compile(
    r"^\s*(?:please\s+)?(?:click|point)\s+(?:then|and|where\s+to)\s+type\s+(.+)$|"
    r"^\s*(?:please\s+)?(?:click\s+then\s+type|point\s+and\s+type)\s+(.+)$",
    re.I,
)

# message <contact> on whatsapp <text> / send whatsapp to <contact> saying <text>
_WHATSAPP_MSG = re.compile(
    r"^\s*(?:please\s+)?(?:message|text|msg)\s+(.+?)\s+on\s+whatsapp\s+(.+)$|"
    r"^\s*(?:please\s+)?(?:send\s+)?(?:a\s+)?(?:whatsapp|wa)\s+(?:message\s+)?to\s+(.+?)\s+"
    r"(?:saying|that\s+says|with|:)\s+(.+)$|"
    r"^\s*(?:please\s+)?send\s+(.+?)\s+(?:on|via|with)\s+whatsapp\s+(?:saying\s+|that\s+)?(.+)$",
    re.I,
)

# send email to X saying Y / email X about Y / mail X that Y
_MAIL_COMPOSE = re.compile(
    r"^\s*(?:please\s+)?(?:send\s+(?:an?\s+)?(?:email|mail)\s+to|email|mail)\s+(.+?)\s+"
    r"(?:saying|that\s+says|about|with(?:\s+body)?|:)\s+(.+)$",
    re.I,
)
# Bare "email Ranjith" / "mail Mom" — compose with empty body (ask what to say)
_MAIL_TO_ONLY = re.compile(
    r"^\s*(?:please\s+)?(?:email|mail)\s+(?!me\b)(.+)$",
    re.I,
)

_MAIL_SUMMARIZE = re.compile(
    r"^\s*(?:please\s+)?(?:summarize|summary\s+of|read)\s+(?:my\s+|the\s+|first\s+|last\s+)?"
    r"(?:unread\s+)?(?:email|emails|mail|inbox|messages)\b|"
    r"^\s*(?:please\s+)?(?:what\s+was|what'?s|whats)\s+(?:the\s+)?(?:last|latest|recent)\s+"
    r"(?:email|mail|message)\b|"
    r"^\s*(?:please\s+)?(?:last|latest)\s+(?:email|mail)(?:\s+i\s+(?:got|received|have\s+received))?\b",
    re.I,
)

# Time ask + type into notepad (with or without "and")
_TIME_THEN_TYPE = re.compile(
    r"^\s*(?:please\s+)?(?:what(?:'s|\s+is)?\s+(?:the\s+)?time(?:\s+(?:is\s+it|right\s+now|now))?|"
    r"(?:tell\s+me\s+)?(?:the\s+)?time)\s+"
    r"(?:now\s+)?(?:and\s+)?(?:then\s+)?(?:type|write|dictate)\s+"
    r"(?:(?:the\s+)?time\s+)?"
    r"(?:(?:in|into|on)\s+(?:the\s+)?(notepad|notes?))?\s*"
    r"(?:(?:the\s+)?time)?\s*$",
    re.I,
)

# Last photo taken by Marc
_OPEN_LAST_PHOTO = re.compile(
    r"^\s*(?:please\s+)?(?:open|show|view)\s+(?:the\s+)?(?:photo|picture|image)\s+"
    r"(?:(?:that\s+)?(?:you|i)\s+)?(?:have\s+|just\s+)?(?:taken|captured|shot)\b|"
    r"^\s*(?:please\s+)?(?:open|show)\s+(?:my\s+)?(?:last|latest)\s+(?:photo|picture)\b",
    re.I,
)

_CALENDAR_LIST = re.compile(
    r"^\s*(?:please\s+)?(?:what(?:'?s| is)?\s+)?(?:on\s+)?(?:my\s+)?(?:calendar|schedule)\b|"
    r"^\s*(?:please\s+)?(?:list|show|check)\s+(?:my\s+)?(?:calendar|upcoming\s+events?|schedule)\b|"
    r"^\s*(?:please\s+)?(?:any|what)\s+(?:events?|meetings?)\s+(?:today|tomorrow|this\s+week)?\s*$",
    re.I,
)
_CALENDAR_CREATE = re.compile(
    r"^\s*(?:please\s+)?(?:add|create|put)\s+(?:an?\s+)?(?:event|meeting)\s+(?:on\s+(?:my\s+)?calendar\s+)?(?:for\s+|called\s+|titled\s+)?(.+)$|"
    r"^\s*(?:please\s+)?schedule\s+(?:an?\s+)?(?:event|meeting)\s+(.+)$",
    re.I,
)
_DRIVE_SEARCH = re.compile(
    r"^\s*(?:please\s+)?(?:search|find|look\s+up)\s+(?:in\s+)?(?:my\s+)?(?:google\s+)?drive\s+(?:for\s+)?(.+)$|"
    r"^\s*(?:please\s+)?(?:find|search)\s+(?:the\s+)?(?:file|document|doc|pdf)\s+(.+)$|"
    r"^\s*(?:please\s+)?(?:open|show)\s+(?:my\s+)?drive\s*$",
    re.I,
)
_MAPS_DIR = re.compile(
    r"^\s*(?:please\s+)?(?:directions?|navigate|nav)\s+(?:to\s+)?(.+)$|"
    r"^\s*(?:please\s+)?(?:how\s+(?:do\s+i|to)\s+get\s+to)\s+(.+)$|"
    r"^\s*(?:please\s+)?take\s+me\s+to\s+(.+)$",
    re.I,
)
_MAPS_SEARCH = re.compile(
    r"^\s*(?:please\s+)?(?:search|find|look\s+up)\s+(?:on\s+)?(?:google\s+)?maps\s+(?:for\s+)?(.+)$|"
    r"^\s*(?:please\s+)?(?:where\s+is)\s+(.+)$|"
    r"^\s*(?:please\s+)?(?:open\s+)?maps?\s+(?:for\s+|near\s+)?(.+)$",
    re.I,
)

_REMIND = re.compile(
    r"^\s*(?:please\s+)?(?:remind\s+me(?:\s+to)?|set\s+(?:a\s+)?reminder|set\s+(?:an?\s+)?alarm)\s+(.+)$|"
    r"^\s*(?:please\s+)?alarm\s+(.+)$",
    re.I,
)

# copy that to whatsapp <contact>
_WHATSAPP_COPY = re.compile(
    r"^\s*(?:please\s+)?(?:copy|paste|send)\s+(?:that|this|it|the\s+clipboard)\s+"
    r"(?:to\s+)?whatsapp\s+(?:to\s+)?(.+)$|"
    r"^\s*(?:please\s+)?whatsapp\s+(.+?)\s+(?:the\s+)?(?:clipboard|copied\s+text)\s*$",
    re.I,
)

_NEW_TAB = re.compile(
    r"^\s*(?:please\s+)?(?:open\s+)?(?:a\s+)?new\s+tab(?:\s+on\s+(.+))?\s*$",
    re.I,
)

_NEW_FILE_NOTEPAD = re.compile(
    r"^\s*(?:please\s+)?(?:open\s+)?(?:a\s+)?new\s+(?:file|window|document)(?:\s+on\s+(?:the\s+)?notepad)?\s*$|"
    r"^\s*(?:please\s+)?open\s+new\s+file\s+on\s+(?:the\s+)?notepad\s*$",
    re.I,
)

# Camera
_CAMERA_OPEN = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?camera\s*$",
    re.I,
)
_CAMERA_PHOTO = re.compile(
    r"^\s*(?:please\s+)?(?:take|capture|click)\s+(?:a\s+|my\s+)?(?:photo|picture|selfie)\b|"
    r"^\s*(?:please\s+)?(?:click)\s+(?:my\s+)?(?:photo|picture)\b|"
    r"^\s*(?:please\s+)?(?:open\s+)?camera\s+and\s+(?:take|capture|click)(?:\s+(?:a\s+)?(?:photo|picture))?\b|"
    r"^\s*(?:please\s+)?(?:open\s+)?(?:the\s+)?camera\s+and\s+(?:click|take|capture)\s*$",
    re.I,
)
_CAMERA_RECORD = re.compile(
    r"^\s*(?:please\s+)?(?:start\s+)?(?:recording|record)(?:\s+(?:a\s+)?(?:video|clip))?\s*$|"
    r"^\s*(?:please\s+)?(?:open\s+)?camera\s+and\s+(?:start\s+)?record|"
    r"^\s*(?:please\s+)?(?:start|begin)\s+(?:a\s+)?(?:video\s+)?recording\s*$",
    re.I,
)
_CAMERA_STOP = re.compile(
    r"^\s*(?:please\s+)?stop\s+(?:recording|record(?:ing)?)\s*$",
    re.I,
)
_CAMERA_VIDEO_MODE = re.compile(
    r"^\s*(?:please\s+)?(?:switch|change|go)\s+to\s+(?:video|record(?:ing)?(?:\s+mode)?)|"
    r"^\s*(?:please\s+)?(?:video|record(?:ing)?)\s+mode|"
    r"^\s*(?:please\s+)?switch\s+to\s+video\s*$",
    re.I,
)
_CAMERA_PHOTO_MODE = re.compile(
    r"^\s*(?:please\s+)?(?:switch|change|go)\s+to\s+photo(?:\s+mode)?|"
    r"^\s*(?:please\s+)?photo\s+mode\s*$",
    re.I,
)
_CAMERA_BARCODE = re.compile(
    r"^\s*(?:please\s+)?(?:switch|change|go)\s+to\s+(?:barcode|qr)(?:\s+(?:mode|scanner))?|"
    r"^\s*(?:please\s+)?(?:barcode|qr)\s+(?:mode|scanner)|"
    r"^\s*(?:please\s+)?(?:scan\s+(?:a\s+)?(?:barcode|qr(?:\s+code)?))\s*$",
    re.I,
)
_GOOGLE_SEARCH = re.compile(
    r"^\s*(?:please\s+)?google\s+(.+)$|"
    r"^\s*(?:please\s+)?search\s+(?:on\s+)?google\s+(?:for\s+)?(.+)$|"
    r"^\s*(?:please\s+)?search\s+(?:for\s+)?(.+?)\s+on\s+google\s*$",
    re.I,
)
_OPEN_FIRST_RESULT = re.compile(
    r"^\s*(?:please\s+)?(?:open|click|play)\s+(?:the\s+)?(first|second|third|1st|2nd|3rd|\d+)\s+"
    r"(?:result|link|one|page|video)?\s*$",
    re.I,
)
_FULLSCREEN = re.compile(
    r"^\s*(?:please\s+)?(?:make\s+(?:it\s+)?)?(?:full[\s-]*screen|fullscreen)|"
    r"^\s*(?:please\s+)?(?:go\s+)?full[\s-]*screen|"
    r"^\s*(?:please\s+)?(?:enter|toggle)\s+full[\s-]*screen",
    re.I,
)
_WINDOW_SNAP = re.compile(
    r"^\s*(?:please\s+)?(?:snap|move)\s+(?:the\s+)?(?:window\s+)?(?:to\s+the\s+)?(left|right)\s*$|"
    r"^\s*(?:please\s+)?snap\s+(left|right)\s*$|"
    r"^\s*(?:please\s+)?(maximize|minimize)(?:\s+(?:the\s+)?window)?\s*$|"
    r"^\s*(?:please\s+)?(?:show\s+)?(?:task\s+view|desktop)\s*$",
    re.I,
)
_SETTINGS_PAGE = re.compile(
    r"^\s*(?:please\s+)?(?:open\s+)?(wifi|wi-fi|bluetooth|display|sound|network)\s+settings\s*$|"
    r"^\s*(?:please\s+)?open\s+settings\s+(?:for\s+)?(wifi|wi-fi|bluetooth|display)\s*$",
    re.I,
)
_CLIPBOARD_READ = re.compile(
    r"^\s*(?:please\s+)?(?:read|show)\s+(?:the\s+)?clipboard|"
    r"^\s*(?:please\s+)?what(?:'s|\s+is)\s+on\s+(?:the\s+)?clipboard",
    re.I,
)


# open youtube on brave / in brave open youtube / search youtube for X on brave
_YT_ON_BROWSER = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|go to)\s+youtube\s+(?:on|in|with)\s+(brave|chrome|edge)\s*$|"
    r"^\s*(?:please\s+)?(?:in|on|with)\s+(brave|chrome|edge)\s+(?:open|launch|go to)\s+youtube\s*$|"
    r"^\s*(?:please\s+)?(?:open|launch)\s+(brave|chrome|edge)\s+(?:and\s+)?(?:open\s+)?youtube\s*$",
    re.I,
)
_YT_SEARCH_ON_BROWSER = re.compile(
    r"^\s*(?:please\s+)?(?:search|find)\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+?)\s+(?:on|in|with)\s+(brave|chrome|edge)\s*$|"
    r"^\s*(?:please\s+)?(?:in|on|with)\s+(brave|chrome|edge)\s+(?:search|find)\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)\s*$|"
    r"^\s*(?:please\s+)?(?:search|find)\s+(.+?)\s+on\s+youtube\s+(?:on|in|with)\s+(brave|chrome|edge)\s*$",
    re.I,
)

_CONFIRM = re.compile(r"^\s*(yes|y|yeah|yep|confirm|ok|okay|do it|go ahead|sure)\s*$", re.I)
_CANCEL = re.compile(r"^\s*(no|n|cancel|never mind|nevermind)\s*$", re.I)


def normalize_transcript(transcript: str) -> str:
    t = (transcript or "").strip()
    t = _WAKE.sub("", t).strip()
    # Strip trailing punctuation so "Bye." matches sleep / confirms
    t = re.sub(r"[.!?…]+$", "", t).strip()
    # Strip trailing fillers from STT
    t = re.sub(r"\s+(please|thanks|thank you)\s*$", "", t, flags=re.I).strip()
    # STT near-misses
    t = re.sub(r"\btyphoid\b", "type", t, flags=re.I)
    t = re.sub(
        r"^\s*(?:please\s+)?(?:hit|press)\s+entertainment\b",
        "hit enter",
        t,
        flags=re.I,
    )
    # Leading negation filler before type: "no type hi" → "type hi"
    t = re.sub(r"^\s*no\s+(?=type\b)", "", t, flags=re.I).strip()
    parts = t.split()
    if not parts:
        return t
    # Collapse exact A+A duplication (any even length)
    if len(parts) >= 4 and len(parts) % 2 == 0:
        half = len(parts) // 2
        if parts[:half] == parts[half:]:
            parts = parts[:half]
    # Collapse consecutive repeated n-grams (2–4 tokens), e.g. "open browser open browser please"
    for n in (4, 3, 2):
        changed = True
        while changed and len(parts) >= n * 2:
            changed = False
            i = 0
            out: list[str] = []
            while i < len(parts):
                if i + 2 * n <= len(parts) and parts[i : i + n] == parts[i + n : i + 2 * n]:
                    out.extend(parts[i : i + n])
                    i += 2 * n
                    changed = True
                else:
                    out.append(parts[i])
                    i += 1
            parts = out
    # Triple single-token repeats: "open open open" → "open"
    out2: list[str] = []
    for w in parts:
        if len(out2) >= 2 and out2[-1].lower() == w.lower() and out2[-2].lower() == w.lower():
            continue
        if out2 and out2[-1].lower() == w.lower() and w.lower() in (
            "open", "please", "the", "a", "and",
        ):
            continue
        out2.append(w)
    return " ".join(out2)


def is_confirm(transcript: str) -> bool:
    t = re.sub(r"[.!?]+$", "", (transcript or "").strip()).strip()
    return bool(_CONFIRM.match(t))


def is_cancel(transcript: str) -> bool:
    t = re.sub(r"[.!?]+$", "", (transcript or "").strip()).strip()
    return bool(_CANCEL.match(t))


def _app_token(raw: str) -> str:
    from laya_router.synonyms import expand_app_query

    raw = raw.strip(" .,!")
    raw = re.sub(r"^(the|my|a|an)\s+", "", raw, flags=re.I)
    low = raw.lower()
    if low in ("browser", "web browser", "google"):
        return "chrome"
    if "brave" in low:
        return "brave"
    if low in ("mail", "email", "gmail", "inbox"):
        return "gmail"
    if "youtube" in low or low in ("yt",):
        return "youtube"
    if "note pad" in low or "notepad" in low:
        return "notepad"
    if "camera" in low:
        return "camera"
    return expand_app_query(raw)


def parse_compound(transcript: str) -> Optional[Dict[str, Any]]:
    """
    Return a plan dict:
      {intent, confidence, steps:[{tool,args}], reply?, auto_confirm_type?}
    or None if not a known compound/simple override pattern.
    """
    t = normalize_transcript(transcript)
    if not t:
        return None

    # Time + type into notepad (before bare time gate)
    if _TIME_THEN_TYPE.search(t) or (
        _TIME.search(t)
        and re.search(r"\b(?:type|write|dictate)\b", t, re.I)
        and len(t.split()) <= 16
    ):
        steps: List[Dict[str, Any]] = [
            {"tool": "system_status", "args": {"metric": "time"}},
        ]
        if re.search(r"\bnotepad\b|\bnotes?\b", t, re.I):
            steps.append({"tool": "open_app", "args": {"app": "notepad"}, "delay": _step_gap()})
        steps.append(
            {
                "tool": "type_text",
                "args": {"text": "__SPOKEN_TIME__"},
                "confirm": False,
                "delay": _step_gap(),
            }
        )
        return {
            "intent": "multi_step",
            "confidence": 0.94,
            "steps": steps,
            "source": "compound",
            "reply": "Typing the time.",
            "inject_spoken_time": True,
        }

    if _TIME.search(t) and len(t.split()) <= 8:
        return {
            "intent": "system_status",
            "confidence": 0.95,
            "steps": [{"tool": "system_status", "args": {"metric": "time"}}],
            "source": "compound",
        }

    if _OPEN_LAST_PHOTO.search(t):
        return {
            "intent": "open_last_photo",
            "confidence": 0.93,
            "steps": [{"tool": "open_last_photo", "args": {}}],
            "source": "compound",
            "reply": "Opening the last photo.",
        }

    if _CAMERA_PHOTO.search(t):
        return {
            "intent": "camera_photo",
            "confidence": 0.92,
            "steps": [{"tool": "camera_photo", "args": {}}],
            "source": "compound",
        }

    if _CAMERA_BARCODE.search(t):
        return {
            "intent": "camera_barcode",
            "confidence": 0.92,
            "steps": [{"tool": "camera_mode", "args": {"mode": "barcode"}}],
            "source": "compound",
        }

    if _CAMERA_PHOTO_MODE.search(t):
        return {
            "intent": "camera_photo_mode",
            "confidence": 0.92,
            "steps": [{"tool": "camera_mode", "args": {"mode": "photo"}}],
            "source": "compound",
        }

    if _CAMERA_VIDEO_MODE.search(t):
        return {
            "intent": "camera_video",
            "confidence": 0.92,
            "steps": [{"tool": "camera_mode", "args": {"mode": "video"}}],
            "source": "compound",
        }

    if _CAMERA_STOP.search(t):
        return {
            "intent": "camera_stop",
            "confidence": 0.92,
            "steps": [{"tool": "camera_stop", "args": {}}],
            "source": "compound",
        }

    if _CAMERA_RECORD.search(t):
        return {
            "intent": "camera_record",
            "confidence": 0.92,
            "steps": [{"tool": "camera_record", "args": {}}],
            "source": "compound",
        }

    # next / previous YouTube video
    m = _NEXT_PREV_VIDEO.match(t)
    if m:
        low = t.lower()
        action = "prev" if re.search(r"\b(previous|prev)\b", low) else "next"
        return {
            "intent": "youtube_media",
            "confidence": 0.95,
            "steps": [{"tool": "youtube_media", "args": {"action": action}}],
            "source": "compound",
            "reply": f"{'Previous' if action == 'prev' else 'Next'} video.",
        }

    # Mail summarize / compose
    if _MAIL_SUMMARIZE.search(t):
        max_n = 1 if re.search(r"\blast\b|\blatest\b|\brecent\b", t, re.I) else 5
        q = "in:inbox" if max_n == 1 else "is:unread"
        return {
            "intent": "mail_summarize",
            "confidence": 0.95,
            "steps": [{"tool": "mail_summarize", "args": {"query": q, "max": max_n}}],
            "source": "compound",
            "reply": "Checking your last email." if max_n == 1 else "Summarizing your unread mail.",
        }

    if _CALENDAR_LIST.match(t):
        return {
            "intent": "calendar_list",
            "confidence": 0.93,
            "steps": [{"tool": "calendar_list", "args": {"days": 7}}],
            "source": "compound",
            "reply": "Checking your calendar.",
        }

    m = _CALENDAR_CREATE.match(t)
    if m:
        title = next((g for g in m.groups() if g), "").strip(" .,\"'")
        if title:
            return {
                "intent": "calendar_create",
                "confidence": 0.9,
                "steps": [{"tool": "calendar_create", "args": {"title": title, "when": title}}],
                "source": "compound",
                "reply": f"Scheduling: {title[:60]}",
            }

    m = _DRIVE_SEARCH.match(t)
    if m:
        q = next((g for g in m.groups() if g), "") or ""
        q = q.strip(" .,\"'")
        return {
            "intent": "drive_search",
            "confidence": 0.92,
            "steps": [{"tool": "drive_search", "args": {"query": q}}],
            "source": "compound",
            "reply": f"Searching Drive for {q or 'files'}.",
        }

    m = _MAPS_DIR.match(t)
    if m:
        dest = next((g for g in m.groups() if g), "").strip(" .,\"'")
        if dest:
            return {
                "intent": "maps_directions",
                "confidence": 0.93,
                "steps": [{"tool": "maps_directions", "args": {"destination": dest}}],
                "source": "compound",
                "reply": f"Getting directions to {dest[:60]}.",
            }

    m = _MAPS_SEARCH.match(t)
    if m:
        q = next((g for g in m.groups() if g), "").strip(" .,\"'")
        if q and q.lower() not in ("maps", "map", "google maps"):
            return {
                "intent": "maps_search",
                "confidence": 0.92,
                "steps": [{"tool": "maps_search", "args": {"query": q}}],
                "source": "compound",
                "reply": f"Searching Maps for {q[:60]}.",
            }

    m = _REMIND.match(t)
    if m:
        text = next((g for g in m.groups() if g), "").strip()
        if text:
            return {
                "intent": "set_reminder",
                "confidence": 0.95,
                "steps": [{"tool": "set_reminder", "args": {"text": text}}],
                "source": "compound",
                "reply": f"Setting reminder: {text[:60]}",
            }

    m = _MAIL_COMPOSE.match(t)
    if m:
        to = (m.group(1) or "").strip(" .,\"'")
        body = (m.group(2) or "").strip(" .,\"'")
        try:
            from tools.contacts import email_address, is_placeholder_email

            addr, disp = email_address(to)
            if not addr or is_placeholder_email(addr):
                return {
                    "intent": "clarify",
                    "confidence": 0.95,
                    "steps": [],
                    "source": "compound",
                    "reply": f"Add a real email for {disp or to} in config/contacts.json.",
                }
            to = addr
        except Exception:  # noqa: BLE001
            pass
        subject = ""
        if re.match(r"^.+?\s+about\s+", t, re.I):
            subject = body[:60]
        if to and body:
            return {
                "intent": "mail_compose",
                "confidence": 0.95,
                "steps": [
                    {
                        "tool": "mail_compose",
                        "args": {"to": to, "subject": subject, "body": body},
                        "confirm": True,
                    }
                ],
                "source": "compound",
                "reply": f"Send email to {to}? Confirm to proceed.",
            }

    # Bare "email Name" — hold body slot, never WhatsApp
    m = _MAIL_TO_ONLY.match(t)
    if m:
        raw_to = (m.group(1) or "").strip(" .,\"'")
        # Don't steal "email" alone or "email search..."
        if raw_to and not re.match(
            r"^(?:search|inbox|unread|summarize|me)\b", raw_to, re.I
        ):
            try:
                from tools.contacts import email_address, is_placeholder_email

                addr, disp = email_address(raw_to)
            except Exception:  # noqa: BLE001
                addr, disp = "", raw_to
            if not addr or is_placeholder_email(addr):
                return {
                    "intent": "clarify",
                    "confidence": 0.95,
                    "steps": [],
                    "source": "compound",
                    "reply": f"Add a real email for {disp or raw_to} in config/contacts.json.",
                }
            return {
                "intent": "hold_slot",
                "confidence": 0.94,
                "steps": [],
                "source": "compound",
                "awaiting": "slot:continue",
                "pending_prefix": f"email {disp or raw_to} saying",
                "reply": f"What should I say to {disp or raw_to}?",
            }

    # WhatsApp message / copy-to-whatsapp
    m = _WHATSAPP_MSG.match(t)
    if m:
        groups = [g for g in m.groups() if g]
        contact = (groups[0] if groups else "").strip(" .,\"'")
        message = (groups[1] if len(groups) > 1 else "").strip(" .,\"'")
        try:
            from tools.contacts import whatsapp_name

            contact = whatsapp_name(contact)
        except Exception:  # noqa: BLE001
            pass
        if contact and message:
            return {
                "intent": "whatsapp_send",
                "confidence": 0.95,
                "steps": [
                    {
                        "tool": "whatsapp_send",
                        "args": {"contact": contact, "message": message},
                        "confirm": True,
                    }
                ],
                "source": "compound",
                "reply": f"Send WhatsApp to {contact}: “{message[:60]}”? Confirm to proceed.",
            }

    m = _WHATSAPP_COPY.match(t)
    if m:
        contact = (m.group(1) or m.group(2) or "").strip(" .,\"'")
        if contact:
            return {
                "intent": "whatsapp_send",
                "confidence": 0.95,
                "steps": [
                    {
                        "tool": "whatsapp_send",
                        "args": {"contact": contact, "from_clipboard": True},
                        "confirm": True,
                    }
                ],
                "source": "compound",
                "reply": f"Send clipboard to {contact} on WhatsApp? Confirm to proceed.",
            }

    # click then type
    m = _CLICK_THEN_TYPE.match(t)
    if m:
        text = (m.group(1) or m.group(2) or "").strip(" .,\"'")
        if text:
            return {
                "intent": "type_text",
                "confidence": 0.95,
                "steps": [
                    {
                        "tool": "click_then_type",
                        "args": {"text": text, "delay": 3.0},
                        "confirm": False,
                    }
                ],
                "source": "compound",
                "auto_type": True,
                "reply": "Click where to type.",
            }

    # close A and B
    m = _CLOSE_AND.match(t)
    if m:
        a1 = _app_token(m.group(1))
        a2 = _app_token(m.group(2))
        return {
            "intent": "close_app",
            "confidence": 0.95,
            "steps": [
                {
                    "tool": "close_apps",
                    "args": {"apps": [a1, a2]},
                    "confirm": False,
                }
            ],
            "source": "compound",
            "reply": f"Closing {a1} and {a2}.",
        }

    # stop/close the music → media pause (before stop-app)
    if re.match(
        r"^\s*(?:please\s+)?(?:stop|pause)\s+(?:the\s+)?(?:music|song|songs|media|playback)\s*$|"
        r"^\s*(?:please\s+)?stop\s+(?:playing|it)\s*$",
        t,
        re.I,
    ):
        return {
            "intent": "volume_media",
            "confidence": 0.96,
            "steps": [{"tool": "volume_media", "args": {"action": "pause"}}],
            "source": "compound",
            "reply": "Paused.",
        }

    # close/stop/quit <app> → close_app (incl. "close music" → spotify)
    m = re.match(
        r"^\s*(?:please\s+)?(?:close|quit|kill|exit|stop)\s+(?:the\s+|my\s+|this\s+)?"
        r"(.+?)\s*$",
        t,
        re.I,
    )
    if m:
        raw = m.group(1).strip()
        # "stop music" already handled above; bare media words → pause not kill
        if re.match(r"^(?:music|song|songs|media|playback|it|playing)$", raw, re.I):
            # "close music" means quit Spotify (not pause)
            if re.match(r"^\s*(?:please\s+)?close\b", t, re.I):
                return {
                    "intent": "close_app",
                    "confidence": 0.95,
                    "steps": [{"tool": "close_app", "args": {"app": "spotify"}}],
                    "source": "compound",
                    "reply": "Closed spotify.",
                }
            return {
                "intent": "volume_media",
                "confidence": 0.96,
                "steps": [{"tool": "volume_media", "args": {"action": "pause"}}],
                "source": "compound",
                "reply": "Paused.",
            }
        app = _app_token(raw)
        return {
            "intent": "close_app",
            "confidence": 0.95,
            "steps": [{"tool": "close_app", "args": {"app": app}}],
            "source": "compound",
            "reply": f"Closed {app}.",
        }

    # Incomplete: "open" / "search" alone → ask for the missing slot
    m = _BARE_VERB.match(t)
    if m:
        verb = m.group(1).lower()
        slot = {
            "open": "slot:open_app",
            "launch": "slot:open_app",
            "start": "slot:open_app",
            "search": "slot:web_search",
            "find": "slot:web_search",
            "type": "slot:type_text",
            "write": "slot:type_text",
            "close": "slot:close_app",
            "focus": "slot:focus_window",
        }.get(verb, "slot:open_app")
        prompts = {
            "slot:open_app": "Open what?",
            "slot:web_search": "Search for what?",
            "slot:type_text": "Type what?",
            "slot:close_app": "Close what?",
            "slot:focus_window": "Focus which app?",
        }
        return {
            "intent": "hold_slot",
            "confidence": 0.99,
            "steps": [],
            "source": "compound",
            "awaiting": slot,
            "reply": prompts.get(slot, "What next?"),
        }

    # Trailing "and"/"then" with nothing after — hold and wait for the rest
    m = _INCOMPLETE_AND.match(t)
    if m and not re.search(r"\b(fullscreen|full\s*screen|maximize|minimize|new\s+tab)\b", t, re.I):
        prefix = m.group(1).strip()
        if prefix:
            return {
                "intent": "hold_slot",
                "confidence": 0.98,
                "steps": [],
                "source": "compound",
                "awaiting": "slot:continue",
                "pending_prefix": prefix + " and",
                "reply": "And then?",
            }

    # "open browser and open" — incomplete second clause
    m = _INCOMPLETE_AND_VERB.match(t)
    if m:
        prefix = m.group(1).strip()
        verb = m.group(2).strip().lower()
        return {
            "intent": "hold_slot",
            "confidence": 0.98,
            "steps": [],
            "source": "compound",
            "awaiting": "slot:continue",
            "pending_prefix": f"{prefix} and {verb}",
            "reply": f"{verb.capitalize()} what?",
        }

    # open browser and fullscreen → open_app + hotkey (before open-and-open app pair)
    m = _OPEN_AND_ACTION.match(t)
    if m:
        app = _app_token(m.group(1))
        action_raw = re.sub(r"[\s-]+", " ", m.group(2).strip().lower())
        action = _ACTION_HOTKEY.get(action_raw, action_raw)
        if action_raw.replace("-", " ") in _ACTION_HOTKEY:
            action = _ACTION_HOTKEY[action_raw.replace("-", " ")]
        # unmute is volume_media, not a missing hotkey
        if action_raw in ("unmute",):
            return {
                "intent": "open_app",
                "confidence": 0.95,
                "steps": [
                    {"tool": "open_app", "args": {"app": app}},
                    {
                        "tool": "volume_media",
                        "args": {"action": "unmute"},
                        "delay": 1.0,
                    },
                ],
                "source": "compound",
                "reply": f"Opening {app} and unmuting.",
            }
        return {
            "intent": "open_app",
            "confidence": 0.95,
            "steps": [
                {"tool": "open_app", "args": {"app": app}},
                {"tool": "hotkey", "args": {"action": action}, "delay": 1.0},
            ],
            "source": "compound",
            "reply": f"Opening {app} and going {action}.",
        }

    if _FULLSCREEN.search(t):
        return {
            "intent": "hotkey",
            "confidence": 0.95,
            "steps": [{"tool": "hotkey", "args": {"action": "fullscreen"}}],
            "source": "compound",
            "reply": "Fullscreen.",
        }

    # "open the first/second" without session — clarify (followup handles when results exist)
    if _OPEN_FIRST_RESULT.match(t):
        return {
            "intent": "clarify",
            "confidence": 0.9,
            "steps": [],
            "source": "compound",
            "reply": "Search YouTube or Google first, then say open the first.",
        }

    m = _WINDOW_SNAP.match(t)
    if m:
        g = next((x for x in m.groups() if x), "").lower()
        action_map = {
            "left": "snap left",
            "right": "snap right",
            "maximize": "maximize",
            "minimize": "minimize",
            "task view": "task view",
            "desktop": "desktop",
        }
        action = action_map.get(g, g)
        if "task view" in t.lower():
            action = "task view"
        if re.search(r"\bdesktop\b", t, re.I) and "snap" not in t.lower():
            action = "desktop"
        return {
            "intent": "hotkey",
            "confidence": 0.93,
            "steps": [{"tool": "hotkey", "args": {"action": action}}],
            "source": "compound",
        }

    m = _SETTINGS_PAGE.match(t)
    if m:
        page = next((x for x in m.groups() if x), "home").lower().replace("wi-fi", "wifi")
        return {
            "intent": "settings",
            "confidence": 0.95,
            "steps": [{"tool": "settings", "args": {"page": page}}],
            "source": "compound",
            "reply": f"Opening {page} settings.",
        }

    if _CLIPBOARD_READ.search(t):
        return {
            "intent": "clipboard",
            "confidence": 0.95,
            "steps": [{"tool": "clipboard", "args": {"action": "read"}}],
            "source": "compound",
        }

    if _CAMERA_OPEN.search(t):
        return {
            "intent": "open_app",
            "confidence": 0.95,
            "steps": [{"tool": "open_app", "args": {"app": "camera"}}],
            "source": "compound",
        }

    # Prefer browser + YouTube patterns before plain "open brave"
    m = _YT_SEARCH_ON_BROWSER.match(t)
    if m:
        groups = [g for g in m.groups() if g]
        browser = "chrome"
        query = ""
        for g in groups:
            gl = g.lower().strip()
            if gl in ("brave", "chrome", "edge"):
                browser = gl
            else:
                query = g.strip()
        steps: List[Dict[str, Any]] = [
            {"tool": "set_preferred_browser", "args": {"browser": browser}},
        ]
        if query:
            steps.append({"tool": "youtube_search", "args": {"query": query}})
            return {
                "intent": "youtube_search",
                "confidence": 0.96,
                "steps": steps,
                "source": "compound",
            }
        steps.append({"tool": "youtube_home", "args": {}})
        return {
            "intent": "youtube_home",
            "confidence": 0.95,
            "steps": steps,
            "source": "compound",
        }

    m = _YT_ON_BROWSER.match(t)
    if m:
        browser = next(
            (g.lower() for g in m.groups() if g and g.lower() in ("brave", "chrome", "edge")),
            "chrome",
        )
        return {
            "intent": "youtube_home",
            "confidence": 0.96,
            "steps": [
                {"tool": "set_preferred_browser", "args": {"browser": browser}},
                {"tool": "youtube_home", "args": {}, "delay": 0.3},
            ],
            "source": "compound",
            "reply": f"Opening YouTube on {browser}.",
        }

    if _OPEN_MAIL.search(t):
        return {
            "intent": "open_app",
            "confidence": 0.95,
            "steps": [{"tool": "open_app", "args": {"app": "gmail"}}],
            "source": "compound",
        }

    # "open browser then search email and open it" / similar → chrome + gmail
    if _OPEN_THEN_MAIL.search(t):
        return {
            "intent": "open_app",
            "confidence": 0.95,
            "steps": [
                {"tool": "open_app", "args": {"app": "chrome"}},
                {"tool": "open_app", "args": {"app": "gmail"}, "delay": 0.8},
            ],
            "source": "compound",
            "reply": "Opening chrome and gmail.",
        }

    m = _OPEN_YT_SEARCH.match(t)
    if m:
        query = m.group(1).strip()
        query = re.sub(r"\s+and\s+play.*$", "", query, flags=re.I).strip()
        return {
            "intent": "youtube_search",
            "confidence": 0.95,
            "steps": [{"tool": "youtube_search", "args": {"query": query}}],
            "source": "compound",
        }

    m = _OPEN_YT.match(t)
    if m:
        query = (m.group(1) or "").strip()
        if query:
            return {
                "intent": "youtube_search",
                "confidence": 0.95,
                "steps": [{"tool": "youtube_search", "args": {"query": query}}],
                "source": "compound",
            }
        return {
            "intent": "youtube_home",
            "confidence": 0.95,
            "steps": [{"tool": "youtube_home", "args": {}}],
            "source": "compound",
        }

    for pat in (_YT_SEARCH,):
        m = pat.match(t)
        if m:
            query = next((g for g in m.groups() if g), "").strip()
            if query:
                return {
                    "intent": "youtube_search",
                    "confidence": 0.95,
                    "steps": [{"tool": "youtube_search", "args": {"query": query}}],
                    "source": "compound",
                }

    m = _OPEN_AND_TYPE.match(t)
    if m:
        app = _app_token(m.group(1))
        text = m.group(2).strip(" .,\"'")
        return {
            "intent": "type_text",
            "confidence": 0.92,
            "steps": [
                {"tool": "open_app", "args": {"app": app}},
                {"tool": "type_text", "args": {"text": text}, "delay": 1.0, "confirm": False},
            ],
            "source": "compound",
            "reply": f"Opening {app} and typing.",
            "auto_type": True,
        }

    m = _OPEN_AND_SEARCH.match(t) or _OPEN_SEARCH_BAR.match(t)
    if m:
        app = _app_token(m.group(1))
        query = m.group(2).strip(" .,\"'")
        # If target is youtube, search there; else open browser then google search
        if "youtube" in app.lower() or "youtube" in m.group(1).lower():
            return {
                "intent": "youtube_search",
                "confidence": 0.95,
                "steps": [{"tool": "youtube_search", "args": {"query": query}}],
                "source": "compound",
            }
        # Don't treat "open notepad and type X" as search (handled above); if app is not a browser, use type
        non_browser = {"notepad", "camera", "calculator", "paint", "settings", "terminal", "explorer"}
        if app.lower() in non_browser:
            return {
                "intent": "type_text",
                "confidence": 0.9,
                "steps": [
                    {"tool": "open_app", "args": {"app": app}},
                    {"tool": "type_text", "args": {"text": query}, "delay": 1.0, "confirm": False},
                ],
                "source": "compound",
                "auto_type": True,
            }
        steps: List[Dict[str, Any]] = [
            {"tool": "open_app", "args": {"app": app}},
            {"tool": "google_search", "args": {"query": query}, "delay": 1.2},
        ]
        return {
            "intent": "web_search",
            "confidence": 0.95,
            "steps": steps,
            "source": "compound",
            "reply": f"Opening {app} and searching for {query}.",
        }

    # open Spotify and play (music) — before open-and-open (which wrongly opens "play music")
    m = re.match(
        r"^\s*(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?"
        r"(spotify|music(?:\s+app)?)\s+and\s+(?:then\s+)?"
        r"(?:play|start|resume)(?:\s+(?:some\s+)?(?:music|songs?|a\s+song|media))?\s*$",
        t,
        re.I,
    )
    if m:
        gap = _step_gap(0.8)
        return {
            "intent": "open_app",
            "confidence": 0.96,
            "steps": [
                {"tool": "open_app", "args": {"app": "spotify"}},
                {"tool": "volume_media", "args": {"action": "play"}, "delay": gap},
            ],
            "source": "compound",
            "reply": "Opening Spotify and playing.",
        }

    m = _OPEN_AND_OPEN.match(t) or _OPEN_PLUS.match(t)
    if m:
        raw2 = m.group(2).strip()
        # Second clause is media — never open_app("play music") → Spotify alias
        media_m = re.match(
            r"^(?:then\s+)?(play|pause|resume|stop)"
            r"(?:\s+(?:the\s+)?(?:music|songs?|media|it))?\s*$",
            raw2,
            re.I,
        )
        if media_m:
            app = _app_token(m.group(1))
            action = media_m.group(1).lower()
            if action == "resume":
                action = "play"
            if action == "stop":
                action = "pause"
            if app.lower() in ("music", "play music"):
                app = "spotify"
            gap = _step_gap(0.8)
            return {
                "intent": "open_app",
                "confidence": 0.95,
                "steps": [
                    {"tool": "open_app", "args": {"app": app}},
                    {"tool": "volume_media", "args": {"action": action}, "delay": gap},
                ],
                "source": "compound",
                "reply": f"Opening {app} and {action}.",
            }
        # Second clause is a window action, not an app
        act_m = re.match(
            r"^(?:open\s+(?:the\s+)?|make\s+(?:it\s+)?|go\s+)?(?:the\s+)?"
            r"(full[\s-]*screen|fullscreen|maximize|minimize|new\s+tab|mute|unmute)\s*$",
            raw2,
            re.I,
        )
        if act_m:
            app = _app_token(m.group(1))
            action_raw = re.sub(r"[\s-]+", " ", act_m.group(1).strip().lower())
            action = _ACTION_HOTKEY.get(action_raw, action_raw)
            return {
                "intent": "open_app",
                "confidence": 0.95,
                "steps": [
                    {"tool": "open_app", "args": {"app": app}},
                    {
                        "tool": "hotkey",
                        "args": {"action": action},
                        "delay": _step_gap(1.0),
                    },
                ],
                "source": "compound",
                "reply": f"Opening {app} and going {action}.",
            }
        a1, a2 = _app_token(m.group(1)), _app_token(m.group(2))
        # "play music" aliasing to Spotify must not become a second open_app
        if re.search(r"\b(play|pause|resume|music|song)\b", raw2, re.I) and a2.lower() in (
            "spotify",
            "music",
            "vlc",
        ):
            gap = _step_gap(0.8)
            app = a1 if a1.lower() not in ("music",) else "spotify"
            return {
                "intent": "open_app",
                "confidence": 0.95,
                "steps": [
                    {"tool": "open_app", "args": {"app": app}},
                    {"tool": "volume_media", "args": {"action": "play"}, "delay": gap},
                ],
                "source": "compound",
                "reply": f"Opening {app} and playing.",
            }
        # "search email" / "email" as second → gmail
        if re.search(r"\b(mail|email|gmail|inbox)\b", m.group(2), re.I):
            a2 = "gmail"
        if a1 == a2 == "gmail":
            a1 = "chrome"
        return {
            "intent": "open_app",
            "confidence": 0.92,
            "steps": [
                {"tool": "open_app", "args": {"app": a1}},
                {
                    "tool": "open_app",
                    "args": {"app": a2},
                    "delay": _step_gap(0.8),
                },
            ],
            "source": "compound",
            "reply": f"Opening {a1} and {a2}.",
        }

    m = _TYPE_CLEAN.match(t)
    if m:
        text = m.group(1).strip(" .,\"'")
        # strip leading "now " leftovers
        text = re.sub(r"^(?:now\s+)+", "", text, flags=re.I)
        if not text:
            return {
                "intent": "hold_slot",
                "confidence": 0.99,
                "steps": [],
                "source": "compound",
                "awaiting": "slot:type_text",
                "reply": "Type what? Speak freely — say done when finished.",
            }
        return {
            "intent": "type_text",
            "confidence": 0.9,
            "steps": [{"tool": "type_text", "args": {"text": text}, "confirm": False}],
            "source": "compound",
            "auto_type": True,
            "keep_type_slot": True,
        }

    if _NEW_FILE_NOTEPAD.search(t):
        return {
            "intent": "open_app",
            "confidence": 0.9,
            "steps": [
                {"tool": "open_app", "args": {"app": "notepad"}},
                {"tool": "hotkey", "args": {"action": "new window"}, "delay": 0.5},
            ],
            "source": "compound",
        }

    m = _NEW_TAB.match(t)
    if m:
        app = _app_token(m.group(1)) if m.group(1) else None
        steps = []
        if app:
            steps.append({"tool": "open_app", "args": {"app": app}})
            steps.append({"tool": "hotkey", "args": {"action": "new tab"}, "delay": 0.8})
        else:
            steps.append({"tool": "hotkey", "args": {"action": "new tab"}})
        return {"intent": "hotkey", "confidence": 0.9, "steps": steps, "source": "compound"}

    # Plain "open youtube" / "open gmail" / "open brave" / "open chrome"
    m = re.match(r"^\s*(?:please\s+)?(?:open|launch|start|go to)\s+(.+?)\s*$", t, re.I)
    if m:
        raw_app = (m.group(1) or "").strip()
        # "start music" / "start playing music" must PLAY — not open_app(music→spotify)
        if re.match(
            r"^(?:playing\s+)?(?:the\s+|some\s+)?(?:music|songs?|media|playback)(?:\s+now)?$",
            raw_app,
            re.I,
        ):
            gap = _step_gap(0.8)
            return {
                "intent": "open_app",
                "confidence": 0.96,
                "steps": [
                    {"tool": "open_app", "args": {"app": "spotify"}},
                    {"tool": "volume_media", "args": {"action": "play"}, "delay": gap},
                ],
                "source": "compound",
                "reply": "Playing on Spotify.",
            }
        app = _app_token(raw_app)
        # strip trailing "and ..." leftovers
        app = re.split(r"\s+and\s+", app, maxsplit=1)[0]
        app = _app_token(app)
        if app == "youtube":
            return {
                "intent": "youtube_home",
                "confidence": 0.95,
                "steps": [{"tool": "youtube_home", "args": {}}],
                "source": "compound",
            }
        if app == "google":
            return {
                "intent": "open_app",
                "confidence": 0.95,
                "steps": [{"tool": "open_app", "args": {"app": "google"}}],
                "source": "compound",
            }
        # Allow any app registered in config/apps.json (+ synonyms)
        try:
            from laya_router.synonyms import _apps_from_config

            known = set(_apps_from_config().values()) | set(_apps_from_config().keys())
        except Exception:  # noqa: BLE001
            known = set()
        known |= {
            "gmail",
            "brave",
            "camera",
            "chrome",
            "notepad",
            "edge",
            "firefox",
            "spotify",
            "cursor",
            "vscode",
            "calculator",
            "explorer",
            "settings",
            "terminal",
            "paint",
            "whatsapp",
            "photos",
            "vlc",
            "store",
            "clock",
            "maps",
            "weather",
            "onedrive",
            "snip",
            "task manager",
        }
        if app.lower() in {k.lower() for k in known}:
            return {
                "intent": "open_app",
                "confidence": 0.95,
                "steps": [{"tool": "open_app", "args": {"app": app}}],
                "source": "compound",
            }
        # "open browser"
        if "browser" in m.group(1).lower():
            return {
                "intent": "open_app",
                "confidence": 0.95,
                "steps": [{"tool": "open_app", "args": {"app": "chrome"}}],
                "source": "compound",
            }

    m = _GOOGLE_SEARCH.match(t)
    if m:
        q = next((g for g in m.groups() if g), "").strip()
        if q:
            return {
                "intent": "web_search",
                "confidence": 0.95,
                "steps": [{"tool": "google_search", "args": {"query": q}}],
                "source": "compound",
            }

    # Bare "play music on Spotify" / "play on Spotify" / "start music" — never YouTube / bare open
    m = re.match(
        r"^\s*(?:please\s+)?(?:play|start|resume)\s+(?:(?:some\s+)?(?:music|songs?|a\s+song)\s+)?"
        r"(?:on\s+|in\s+)?spotify\s*$|"
        r"^\s*(?:please\s+)?(?:play|start)\s+spotify\s*$|"
        r"^\s*(?:please\s+)?spotify\s+(?:play|music)\s*$|"
        r"^\s*(?:please\s+)?(?:start|play|resume)(?:\s+playing)?\s+(?:the\s+|some\s+)?"
        r"(?:music|songs?|media)(?:\s+now)?\s*$|"
        r"^\s*(?:please\s+)?(?:start|resume)\s+(?:the\s+)?playback\s*$",
        t,
        re.I,
    )
    if m:
        gap = _step_gap(0.8)
        return {
            "intent": "open_app",
            "confidence": 0.96,
            "steps": [
                {"tool": "open_app", "args": {"app": "spotify"}},
                {"tool": "volume_media", "args": {"action": "play"}, "delay": gap},
            ],
            "source": "compound",
            "reply": "Playing on Spotify.",
        }

    # "play music" / "play music now" / "resume music" — media keys, not YouTube
    m = re.match(
        r"^\s*(?:please\s+)?(?:play|start|resume)\s+(?:the\s+|some\s+)?"
        r"(?:music|songs?|media)(?:\s+now)?\s*$",
        t,
        re.I,
    )
    if m:
        return {
            "intent": "volume_media",
            "confidence": 0.95,
            "steps": [{"tool": "volume_media", "args": {"action": "play"}}],
            "source": "compound",
            "reply": "Playing.",
        }

    # Bare "play <title>" → YouTube search (never Windows media keys)
    m = re.match(r"^\s*(?:please\s+)?play\s+(.+)$", t, re.I)
    if m:
        q = m.group(1).strip(" .,\"'")
        # Never treat Spotify/media-on-app as YouTube
        if re.search(r"\bon\s+spotify\b|\bin\s+spotify\b", q, re.I):
            gap = _step_gap(0.8)
            return {
                "intent": "open_app",
                "confidence": 0.95,
                "steps": [
                    {"tool": "open_app", "args": {"app": "spotify"}},
                    {"tool": "volume_media", "args": {"action": "play"}, "delay": gap},
                ],
                "source": "compound",
                "reply": "Playing on Spotify.",
            }
        # Generic music phrases already handled above; skip YouTube for them
        if re.match(
            r"^(?:the\s+|some\s+)?(?:music|songs?|media)(?:\s+now)?$",
            q,
            re.I,
        ):
            return {
                "intent": "volume_media",
                "confidence": 0.95,
                "steps": [{"tool": "volume_media", "args": {"action": "play"}}],
                "source": "compound",
            }
        if q and q.lower() not in ("it", "this", "that", "music", "media", "video"):
            # skip pure ordinals — followup handles those
            if not re.match(
                r"^(?:the\s+)?(?:first|second|third|fourth|fifth|\d+)(?:\s|$)",
                q,
                re.I,
            ):
                return {
                    "intent": "youtube_search",
                    "confidence": 0.88,
                    "steps": [{"tool": "youtube_search", "args": {"query": q}}],
                    "source": "compound",
                }

    # search for email
    if re.match(
        r"^\s*(?:please\s+)?(?:now\s+)?(?:search|find|look up)(?:\s+for)?\s+"
        r"(?:my\s+)?(?:email|mail|gmail|inbox)\s*$",
        t,
        re.I,
    ):
        return {
            "intent": "open_app",
            "confidence": 0.95,
            "steps": [{"tool": "open_app", "args": {"app": "gmail"}}],
            "source": "compound",
        }

    return None
