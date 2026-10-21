"""Follow-up resolution using session memory."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from orchestrator.session import SessionState, VideoResult

_ORDINALS = {
    "first": 0,
    "1st": 0,
    "one": 0,
    "second": 1,
    "2nd": 1,
    "two": 1,
    "third": 2,
    "3rd": 2,
    "three": 2,
    "fourth": 3,
    "4th": 3,
    "fifth": 4,
    "5th": 4,
}

_PLAY_N = re.compile(
    # Allow STT trailing junk: "play the third world" → still third
    # Also "go to (the) second"
    r"^\s*(?:please\s+)?(?:play|open|click|go\s+to)\s+(?:the\s+)?"
    r"(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|\d+)\b",
    re.I,
)

_PLAY_DESC = re.compile(
    r"^\s*(?:please\s+)?(?:play|open)\s+(?:the\s+)?(?:video\s+)?(?:called\s+|named\s+|about\s+|with\s+)(.+)$|"
    r"^\s*(?:please\s+)?(?:play|open)\s+(.+)$",
    re.I,
)
_SEARCH_FOR = re.compile(
    r"^\s*(?:please\s+)?(?:now\s+)?(?:search|find|look up)(?:\s+for)?\s+(.+)$",
    re.I,
)
_YT_SEARCH = re.compile(
    r"^\s*(?:please\s+)?(?:search|find)\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)$|"
    r"^\s*(?:please\s+)?(?:search|find)\s+(.+?)\s+on\s+youtube\s*$|"
    r"^\s*(?:please\s+)?youtube\s+(?:search\s+)?(?:for\s+)?(.+)$",
    re.I,
)
_PAUSE_PLAY = re.compile(
    r"^\s*(?:please\s+)?(pause|resume)(?:\s+(?:video|it|playback|music))?\s*$|"
    r"^\s*(?:please\s+)?play(?:\s+(?:video|it|playback))?\s*$",
    re.I,
)
_SLEEP = re.compile(
    r"^\s*(?:please\s+)?(?:stop(?:\s+listening)?|sleep|go to sleep|goodbye|bye|"
    r"quit listening|stand down)\s*[.!?…]*\s*$",
    re.I,
)
_CANCEL_SOFT = re.compile(
    r"^\s*(?:please\s+)?(?:never mind|nevermind|cancel|forget it)\s*[.!?…]*\s*$",
    re.I,
)
_BARE_ORDINAL = re.compile(
    r"^\s*(?:please\s+)?(?:(?:open|go\s+to)\s+)?(?:the\s+)?"
    r"(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|\d+)"
    r"(?:\s+(?:result|link|one|page|video))?\s*$",
    re.I,
)
_ORDINAL_ONLY = re.compile(
    r"^\s*(?:please\s+)?(?:go\s+to\s+)?(?:the\s+)?"
    r"(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|\d+)"
    r"(?:\s+(?:result|link|one|page|video))?\s*$",
    re.I,
)
_MAIL_SEARCH = re.compile(
    r"^\s*(?:please\s+)?(?:search|find)\s+(?:in\s+)?(?:my\s+)?(?:mail|email|gmail|inbox)\s+(?:for\s+)?(.+)$|"
    r"^\s*(?:please\s+)?(?:search|find)\s+(?:mail|email|gmail)\s+(?:for\s+)?(.+)$",
    re.I,
)
_SUMMARIZE = re.compile(
    r"^\s*(?:please\s+)?(?:summarize|analyse|analyze|read)\s+(?:(?:the|this|that|my|first|last)\s+)?(?:mail|email|inbox|message)|"
    r"^\s*(?:please\s+)?(?:what\s+was|what'?s|whats)\s+(?:the\s+)?(?:last|latest|recent)\s+(?:email|mail|message)\b|"
    r"^\s*(?:please\s+)?(?:last|latest)\s+(?:email|mail)\b",
    re.I,
)
# Bare "search for email" / "now search for email"
_SEARCH_EMAIL = re.compile(
    r"^\s*(?:please\s+)?(?:now\s+)?(?:search|find|look up|open)(?:\s+for)?\s+"
    r"(?:my\s+)?(?:email|mail|gmail|inbox)\s*$",
    re.I,
)


def _index_from_token(tok: str) -> Optional[int]:
    tok = tok.strip().lower()
    if tok in _ORDINALS:
        return _ORDINALS[tok]
    if tok.isdigit():
        n = int(tok)
        return max(0, n - 1) if n >= 1 else 0
    return None


def fuzzy_pick(results: List[VideoResult], phrase: str) -> Optional[VideoResult]:
    phrase = phrase.strip().lower()
    if not phrase or not results:
        return None
    for v in results:
        if phrase in v.title.lower():
            return v
    tokens = [t for t in re.split(r"\W+", phrase) if len(t) > 2]
    best, best_score = None, 0
    for v in results:
        title = v.title.lower()
        score = sum(1 for t in tokens if t in title)
        if score > best_score:
            best, best_score = v, score
    return best if best_score > 0 else None


def _youtube_context(session: SessionState) -> bool:
    """True only while actively picking a YouTube result — not forever after one search."""
    return session.awaiting == "pick_video" and session.last_site == "youtube"


def _youtube_site(session: SessionState) -> bool:
    """True if last site was YouTube (for play-title search, not sticky ordinals)."""
    return session.last_site == "youtube"


def _pick_context(session: SessionState) -> bool:
    return session.awaiting in ("pick_video", "pick_result") and bool(session.last_results)


def resolve_followup(transcript: str, session: SessionState) -> Optional[Dict[str, Any]]:
    """Return a compound-style plan dict or None."""
    t = (transcript or "").strip()
    if not t:
        return None

    # Soft cancel while holding a slot / pick — clear hold, stay awake
    if _CANCEL_SOFT.match(t):
        if session.is_holding():
            session.clear_awaiting()
            return {
                "intent": "clarify",
                "confidence": 1.0,
                "steps": [],
                "source": "followup",
                "reply": "Okay, cancelled. What next?",
                "keep_awaiting": False,
            }
        # Alone, cancel is not sleep
        return {
            "intent": "clarify",
            "confidence": 0.9,
            "steps": [],
            "source": "followup",
            "reply": "Nothing to cancel. What do you need?",
            "keep_awaiting": True,
        }

    if _SLEEP.match(t):
        return {
            "intent": "sleep",
            "confidence": 1.0,
            "steps": [],
            "source": "followup",
            "reply": "sleep",
            "should_continue": False,
        }

    # Never sticky-search while confirming
    if session.awaiting == "confirm":
        return None

    # Ordinal with no pick list → clarify (don't fall through to focus_window)
    m_ord = _ORDINAL_ONLY.match(t) or _PLAY_N.match(t) or _BARE_ORDINAL.match(t)
    if m_ord and not _pick_context(session):
        tok = m_ord.group(1) if m_ord.lastindex else None
        if tok and _index_from_token(tok) is not None:
            # Allow YouTube home recovery path for play/open later; go-to alone clarifies
            if re.match(r"^\s*(?:please\s+)?go\s+to\b", t, re.I) or _ORDINAL_ONLY.match(t):
                if not (_youtube_site(session) and not session.last_results and re.match(
                    r"^\s*(?:please\s+)?(?:play|open)\b", t, re.I
                )):
                    return {
                        "intent": "clarify",
                        "confidence": 0.95,
                        "steps": [],
                        "source": "followup",
                        "reply": "I don't have a result list. Search or open YouTube/Google first, then say first, second, or third.",
                    }

    # Send it / press Enter after type or WhatsApp (never YouTube pick)
    if re.match(
        r"^\s*(?:please\s+)?(?:send(?:\s+it|\s+that|\s+this)?|hit\s+send|"
        r"press\s+enter|hit\s+enter)\s*\.?\s*$",
        t,
        re.I,
    ):
        last = (getattr(session, "last_tool", "") or "").lower()
        app = (session.last_app or "").lower()
        if last in ("type_text", "click_then_type", "whatsapp_send") or app in (
            "whatsapp",
            "notepad",
        ):
            return {
                "intent": "hotkey",
                "confidence": 0.98,
                "steps": [{"tool": "hotkey", "args": {"action": "enter"}}],
                "source": "followup",
                "reply": "Sending.",
                "keep_awaiting": False,
            }
        # Still prefer Enter over YouTube when user just typed something
        if session.last_typed:
            return {
                "intent": "hotkey",
                "confidence": 0.95,
                "steps": [{"tool": "hotkey", "args": {"action": "enter"}}],
                "source": "followup",
                "reply": "Sending.",
                "keep_awaiting": False,
            }

    # Memory: send that / email that (typed → summary → clipboard)
    def _memory_body() -> tuple[str, bool]:
        body = (session.last_typed or session.last_summary or "").strip()
        if body:
            return body, False
        try:
            import pyperclip

            clip = (pyperclip.paste() or "").strip()
            if clip:
                return clip, True
        except Exception:  # noqa: BLE001
            pass
        return "", True

    m = re.match(
        r"^\s*(?:please\s+)?(?:send|message|copy)\s+(?:that|this|it)\s+"
        r"(?:to\s+)?(.+?)\s+on\s+whatsapp\s*$",
        t,
        re.I,
    )
    if m:
        contact = m.group(1).strip()
        try:
            from tools.contacts import whatsapp_name

            contact = whatsapp_name(contact)
        except Exception:  # noqa: BLE001
            pass
        body, from_clip = _memory_body()
        return {
            "intent": "whatsapp_send",
            "confidence": 0.95,
            "steps": [
                {
                    "tool": "whatsapp_send",
                    "args": {
                        "contact": contact,
                        "message": body,
                        "from_clipboard": from_clip and not body,
                    },
                    "confirm": True,
                }
            ],
            "source": "followup",
            "reply": f"Send to {contact} on WhatsApp? Confirm to proceed.",
        }
    m = re.match(
        r"^\s*(?:please\s+)?(?:email|mail|send)\s+(?:that|this|it)\s+to\s+(.+)$",
        t,
        re.I,
    )
    if m:
        to_raw = m.group(1).strip()
        try:
            from tools.contacts import email_address

            to, _ = email_address(to_raw)
        except Exception:  # noqa: BLE001
            to = to_raw
        body, _ = _memory_body()
        if body:
            return {
                "intent": "mail_compose",
                "confidence": 0.95,
                "steps": [
                    {
                        "tool": "mail_compose",
                        "args": {"to": to, "subject": "", "body": body},
                        "confirm": True,
                    }
                ],
                "source": "followup",
                "reply": f"Email that to {to}? Confirm to proceed.",
            }

    # pick_mail: reply / open / summarize the first
    if session.awaiting == "pick_mail" and session.last_results:
        m = re.match(
            r"^\s*(?:please\s+)?(?:reply\s+to|answer)\s+(?:the\s+)?"
            r"(first|second|third|1st|2nd|3rd|1|2|3)\b",
            t,
            re.I,
        )
        if m:
            idx_map = {
                "first": 0,
                "1st": 0,
                "1": 0,
                "second": 1,
                "2nd": 1,
                "2": 1,
                "third": 2,
                "3rd": 2,
                "3": 2,
            }
            idx = idx_map.get(m.group(1).lower(), 0)
            if idx < len(session.last_results):
                v = session.last_results[idx]
                mid = ""
                if idx < len(getattr(session, "last_mail_ids", []) or []):
                    mid = session.last_mail_ids[idx] or ""
                # url often embeds id
                if not mid and "/inbox/" in (v.url or ""):
                    mid = v.url.rstrip("/").split("/")[-1]
                return {
                    "intent": "mail_reply",
                    "confidence": 0.95,
                    "steps": [
                        {
                            "tool": "mail_reply",
                            "args": {
                                "message_id": mid,
                                "body": session.last_typed or "Thanks, got it.",
                            },
                            "confirm": True,
                        }
                    ],
                    "source": "followup",
                    "reply": f"Reply to “{v.title[:40]}”? Confirm to proceed.",
                }
        m = re.match(
            r"^\s*(?:please\s+)?(?:summarize|summary\s+of)\s+(?:the\s+)?"
            r"(first|second|third|1st|2nd|3rd)\b",
            t,
            re.I,
        )
        if m:
            return {
                "intent": "mail_summarize",
                "confidence": 0.9,
                "steps": [
                    {
                        "tool": "mail_summarize",
                        "args": {"query": "is:unread", "max": 1},
                    }
                ],
                "source": "followup",
            }

    # Slot continuation: "open browser and" + "fullscreen" → reparse combined
    if session.awaiting == "slot:continue" and session.pending_prefix:
        combined = f"{session.pending_prefix} {t}".strip()
        session.clear_awaiting()
        return {
            "intent": "reparse",
            "confidence": 1.0,
            "steps": [],
            "source": "followup",
            "reparse": combined,
        }

    # Slot fill: bare app / query after "Open what?"
    if session.awaiting == "slot:open_app":
        app = t
        app = re.sub(r"^(?:please\s+)?(?:open|launch|start)\s+", "", app, flags=re.I).strip()
        session.clear_awaiting()
        return {
            "intent": "open_app",
            "confidence": 0.95,
            "steps": [{"tool": "open_app", "args": {"app": app}}],
            "source": "followup",
        }
    if session.awaiting == "slot:web_search":
        q = re.sub(r"^(?:please\s+)?(?:search|find)(?:\s+for)?\s+", "", t, flags=re.I).strip()
        session.clear_awaiting()
        # Prefer opening a known app over googling its name
        try:
            from tools.os_tools import OSTools

            tools = OSTools()
            canon, meta = tools.resolve_app(q)
            if meta and len(q.split()) <= 3:
                return {
                    "intent": "open_app",
                    "confidence": 0.92,
                    "steps": [{"tool": "open_app", "args": {"app": canon}}],
                    "source": "followup",
                }
        except Exception:  # noqa: BLE001
            pass
        return {
            "intent": "web_search",
            "confidence": 0.92,
            "steps": [{"tool": "google_search", "args": {"query": q}}],
            "source": "followup",
        }
    if session.awaiting == "slot:type_text":
        # End dictation
        if re.match(
            r"^\s*(?:please\s+)?(?:done(?:\s+typing)?|that'?s\s+all|finished|stop\s+typing|"
            r"end\s+dictation|cancel)\s*$",
            t,
            re.I,
        ):
            session.clear_awaiting()
            return {
                "intent": "clarify",
                "confidence": 0.99,
                "steps": [],
                "source": "followup",
                "reply": "Okay, done typing.",
                "keep_awaiting": False,
            }
        # Send / enter while dictating
        if re.match(
            r"^\s*(?:please\s+)?(?:send(?:\s+it)?|hit\s+enter|press\s+enter|enter)\s*$",
            t,
            re.I,
        ):
            session.clear_awaiting()
            return {
                "intent": "hotkey",
                "confidence": 0.98,
                "steps": [{"tool": "hotkey", "args": {"action": "enter"}}],
                "source": "followup",
                "reply": "Sending.",
                "keep_awaiting": False,
            }
        # Another command — leave dictation and reparse
        if re.match(
            r"^\s*(?:please\s+)?(?:open|close|quit|launch|search|play|pause|stop|"
            r"focus|switch|sleep|summarize|message|whatsapp)\b",
            t,
            re.I,
        ):
            session.clear_awaiting()
            return {"intent": "reparse", "reparse": t, "source": "followup"}
        text = re.sub(r"^(?:please\s+)?(?:type|write|dictate)\s+", "", t, flags=re.I).strip()
        # "… and send it" / "… send it" while dictating → type then Enter
        send_m = re.search(
            r"[\s,]+(?:and\s+)?(?:then\s+)?(?:send(?:\s+it)?|hit\s+enter|press\s+enter)\s*$",
            text,
            re.I,
        )
        if send_m:
            body = text[: send_m.start()].rstrip(" .,")
            steps = []
            if body:
                steps.append({"tool": "type_text", "args": {"text": body}, "confirm": False})
            steps.append({"tool": "hotkey", "args": {"action": "enter"}})
            session.clear_awaiting()
            return {
                "intent": "hotkey" if not body else "type_text",
                "confidence": 0.96,
                "steps": steps,
                "source": "followup",
                "auto_type": True,
                "reply": "Sending.",
                "keep_awaiting": False,
            }
        # Keep slot open so the next utterance can continue the paragraph
        return {
            "intent": "type_text",
            "confidence": 0.95,
            "steps": [{"tool": "type_text", "args": {"text": text}, "confirm": False}],
            "source": "followup",
            "auto_type": True,
            "keep_type_slot": True,
        }
    if session.awaiting in ("slot:close_app", "slot:focus_window"):
        app = re.sub(
            r"^(?:please\s+)?(?:close|quit|focus|switch to|bring)\s+",
            "",
            t,
            flags=re.I,
        ).strip()
        tool = "close_app" if session.awaiting == "slot:close_app" else "focus_window"
        session.clear_awaiting()
        return {
            "intent": tool,
            "confidence": 0.95,
            "steps": [{"tool": tool, "args": {"app": app}}],
            "source": "followup",
        }

    # While picking a result, bare "open" means "which one?"
    if session.awaiting in ("pick_result", "pick_video") and re.match(
        r"^\s*(?:please\s+)?open\s*$", t, re.I
    ):
        return {
            "intent": "clarify",
            "confidence": 1.0,
            "steps": [],
            "source": "followup",
            "reply": "Which one — first, second, or third?",
            "keep_awaiting": True,
        }

    # Bare ordinal / "the first" / "open the first" when actively picking
    m = _BARE_ORDINAL.match(t) or _PLAY_N.match(t)
    if m and _pick_context(session):
        idx = _index_from_token(m.group(1))
        if idx is not None and 0 <= idx < len(session.last_results):
            v = session.last_results[idx]
            if session.last_site == "google" or session.awaiting == "pick_result":
                return {
                    "intent": "open_result",
                    "confidence": 0.98,
                    "steps": [
                        {"tool": "open_url", "args": {"url": v.url, "title": v.title}}
                    ],
                    "source": "followup",
                }
            return {
                "intent": "play_video",
                "confidence": 0.98,
                "steps": [
                    {"tool": "youtube_play", "args": {"url": v.url, "title": v.title}}
                ],
                "source": "followup",
            }

    if _SUMMARIZE.search(t):
        return {
            "intent": "mail_summarize",
            "confidence": 1.0,
            "steps": [
                {
                    "tool": "mail_summarize",
                    "args": {"query": "is:unread", "max": 5},
                }
            ],
            "source": "followup",
            "reply": "Summarizing your unread mail.",
        }

    if _SEARCH_EMAIL.match(t):
        return {
            "intent": "open_app",
            "confidence": 0.95,
            "steps": [{"tool": "open_app", "args": {"app": "gmail"}}],
            "source": "followup",
        }

    m = _MAIL_SEARCH.match(t)
    if m:
        q = next((g for g in m.groups() if g), "").strip()
        return {
            "intent": "mail_search",
            "confidence": 0.95,
            "steps": [{"tool": "gmail_search", "args": {"query": q}}],
            "source": "followup",
        }

    m = _PAUSE_PLAY.match(t)
    if m and session.last_site == "youtube":
        action = (m.group(1) or "play").lower()
        if action in ("play", "resume") or action == "":
            action = "play"
        return {
            "intent": "youtube_play",
            "confidence": 0.9,
            "steps": [{"tool": "youtube_media", "args": {"action": action}}],
            "source": "followup",
        }

    # next / previous video while on YouTube
    if session.last_site == "youtube" and re.match(
        r"^\s*(?:please\s+)?(?:switch\s+to\s+(?:the\s+)?)?(?:next|previous|prev)\s+"
        r"(?:video|one|track)?\s*$|"
        r"^\s*(?:please\s+)?(?:skip|next)\s*(?:video)?\s*$",
        t,
        re.I,
    ):
        action = "prev" if re.search(r"\b(previous|prev)\b", t, re.I) else "next"
        return {
            "intent": "youtube_media",
            "confidence": 0.95,
            "steps": [{"tool": "youtube_media", "args": {"action": action}}],
            "source": "followup",
        }

    # play/open the Nth — need active pick list
    m = _PLAY_N.match(t)
    if m:
        idx = _index_from_token(m.group(1))
        if idx is not None and _pick_context(session) and 0 <= idx < len(session.last_results):
            v = session.last_results[idx]
            if session.last_site == "google" or session.awaiting == "pick_result":
                return {
                    "intent": "open_result",
                    "confidence": 0.98,
                    "steps": [
                        {"tool": "open_url", "args": {"url": v.url, "title": v.title}}
                    ],
                    "source": "followup",
                }
            return {
                "intent": "play_video",
                "confidence": 0.98,
                "steps": [
                    {"tool": "youtube_play", "args": {"url": v.url, "title": v.title}}
                ],
                "source": "followup",
            }
        # YouTube site but no list — open home; user says play the first again once scraped
        if idx is not None and _youtube_site(session) and not session.last_results:
            return {
                "intent": "youtube_home",
                "confidence": 0.95,
                "steps": [{"tool": "youtube_home", "args": {}}],
                "source": "followup",
                "reply": "Opening YouTube home. Say play the first when you see results.",
            }
        # Ordinal play with no scraped list → clarify (never media keys)
        if idx is not None and re.match(r"^\s*(?:please\s+)?(?:play|open)\b", t, re.I):
            return {
                "intent": "clarify",
                "confidence": 0.95,
                "steps": [],
                "source": "followup",
                "reply": "I don't have a result list. Search YouTube or Google first, or open YouTube then say play the first.",
            }

    # play <title> when last site is YouTube — search or fuzzy pick, NEVER volume_media
    # (does NOT require sticky pick_video — open Gmail clears that)
    if re.match(r"^\s*(?:please\s+)?play\b", t, re.I) and (
        _youtube_context(session) or _youtube_site(session)
    ):
        # Don't steal "play music on spotify"
        if re.search(r"\bon\s+spotify\b|\bin\s+spotify\b|\bspotify\b", t, re.I):
            pass
        else:
            m = _PLAY_DESC.match(t)
            if m:
                phrase = next((g for g in m.groups() if g), "").strip()
                if phrase and _index_from_token(phrase.split()[0] if phrase.split() else "") is None:
                    phrase = re.sub(r"^(?:the\s+)?(?:video\s+)?", "", phrase, flags=re.I)
                    if phrase.lower() not in ("it", "this", "that", "video", "music"):
                        if session.last_results and _pick_context(session):
                            hit = fuzzy_pick(session.last_results, phrase)
                            if hit:
                                return {
                                    "intent": "play_video",
                                    "confidence": 0.9,
                                    "steps": [
                                        {
                                            "tool": "youtube_play",
                                            "args": {"url": hit.url, "title": hit.title},
                                        }
                                    ],
                                    "source": "followup",
                                }
                        # No active pick list / no match → youtube search for the phrase
                        return {
                            "intent": "youtube_search",
                            "confidence": 0.92,
                            "steps": [{"tool": "youtube_search", "args": {"query": phrase}}],
                            "source": "followup",
                        }

    # play by description when actively picking
    if _pick_context(session) and re.match(r"^\s*(?:please\s+)?play\b", t, re.I):
        m = _PLAY_DESC.match(t)
        if m:
            phrase = next((g for g in m.groups() if g), "").strip()
            if phrase and _index_from_token(phrase.split()[0] if phrase.split() else "") is None:
                phrase = re.sub(r"^(?:the\s+)?(?:video\s+)?", "", phrase, flags=re.I)
                if phrase.lower() not in ("it", "this", "that", "video"):
                    hit = fuzzy_pick(session.last_results, phrase)
                    if hit:
                        return {
                            "intent": "play_video",
                            "confidence": 0.9,
                            "steps": [
                                {
                                    "tool": "youtube_play",
                                    "args": {"url": hit.url, "title": hit.title},
                                }
                            ],
                            "source": "followup",
                        }

    m = _YT_SEARCH.match(t)
    if m:
        q = next((g for g in m.groups() if g), "").strip()
        if q:
            return {
                "intent": "youtube_search",
                "confidence": 0.95,
                "steps": [{"tool": "youtube_search", "args": {"query": q}}],
                "source": "followup",
            }

    # Contextual "search for X" — open known *apps* only; topics go to search
    m = _SEARCH_FOR.match(t)
    if m:
        q = m.group(1).strip()
        q_app = re.sub(r"^(?:for\s+)", "", q, flags=re.I).strip()
        topic_block = {
            "music",
            "songs",
            "song",
            "news",
            "weather",
            "videos",
            "video",
            "movies",
            "recipe",
            "recipes",
            "cats",
            "dogs",
            "memes",
        }
        if re.search(r"\b(mail|email|gmail|inbox)\b", q, re.I) and len(q.split()) <= 3:
            return {
                "intent": "open_app",
                "confidence": 0.9,
                "steps": [{"tool": "open_app", "args": {"app": "gmail"}}],
                "source": "followup",
            }
        # YouTube context / explicit youtube → search there first
        if session.last_site == "youtube" or "youtube" in q.lower():
            q2 = re.sub(r"\bon youtube\b", "", q, flags=re.I).strip()
            return {
                "intent": "youtube_search",
                "confidence": 0.92,
                "steps": [{"tool": "youtube_search", "args": {"query": q2 or q}}],
                "source": "followup",
            }
        # Exact app names only (not topic words like music)
        if q_app.lower() not in topic_block and len(q_app.split()) <= 3:
            try:
                from tools.os_tools import OSTools

                tools = OSTools()
                # Require exact alias/key — resolve_app already tightened
                key = q_app.lower()
                if key in tools._alias_index or key in tools.apps:
                    canon, meta = tools.resolve_app(q_app)
                    if meta and not re.search(
                        r"\b(for|about|how|what|why|near|in)\b", q_app, re.I
                    ):
                        return {
                            "intent": "open_app",
                            "confidence": 0.93,
                            "steps": [{"tool": "open_app", "args": {"app": canon}}],
                            "source": "followup",
                            "reply": f"Opening {canon}.",
                        }
            except Exception:  # noqa: BLE001
                pass
        # Default: Google search
        return {
            "intent": "web_search",
            "confidence": 0.9,
            "steps": [{"tool": "google_search", "args": {"query": q}}],
            "source": "followup",
        }

    # Bare topic after YouTube context (e.g. "music") — not commands
    if session.last_site == "youtube" and len(t.split()) <= 3:
        if not re.match(
            r"^\s*(?:please\s+)?(?:play|open|close|pause|resume|next|previous|"
            r"type|write|dictate|enter|send|mute|volume|search|find|look|"
            r"message|email|mail|summarize|cancel|stop|sleep|help|"
            r"yes|y|yeah|yep|ok|okay|no|n|confirm|go|first|second|third|"
            r"fourth|fifth|1st|2nd|3rd|4th|5th|\d+)\b",
            t,
            re.I,
        ):
            return {
                "intent": "youtube_search",
                "confidence": 0.88,
                "steps": [{"tool": "youtube_search", "args": {"query": t}}],
                "source": "followup",
            }

    return None
