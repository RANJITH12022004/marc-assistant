"""N-step clause planner: split spoken chains into ordered tool steps.

Handles phrases like:
  \"open browser and search for youtube and on youtube search for samsung\"
→ open_app(chrome) → youtube_home → youtube_search(samsung)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

MAX_STEPS = 6

# Conjunctive / sequence signals (Jarvis-style compound detect)
_COMPOUND_SIGNAL = re.compile(
    r"\b(?:and(?:\s+then)?|then|after\s+that|plus|,)\b|"
    r"\bon\s+(?:youtube|google|gmail|mail)\b|"
    r"\bin\s+(?:chrome|brave|edge|browser)\b",
    re.I,
)

# Splitters between clauses (keep "on youtube search X" together)
_SPLIT = re.compile(
    r"\s*(?:,\s*|\s+and(?:\s+then)?\s+|\s+then\s+|\s+after\s+that\s+|\s+plus\s+)\s*",
    re.I,
)

_SITE_NAMES = {
    "youtube": "youtube",
    "yt": "youtube",
    "google": "google",
    "gmail": "gmail",
    "mail": "gmail",
    "email": "gmail",
    "inbox": "gmail",
}

_BROWSER_APPS = {"browser", "chrome", "brave", "edge", "firefox"}


def looks_compound(transcript: str) -> bool:
    t = (transcript or "").strip()
    if not t:
        return False
    # Multiple action verbs or conjunctive signals
    if _COMPOUND_SIGNAL.search(t):
        return True
    verbs = len(
        re.findall(
            r"\b(?:open|launch|search|find|play|go\s+to|type|close|send|message)\b",
            t,
            re.I,
        )
    )
    return verbs >= 2


def _app_from(token: str) -> str:
    low = (token or "").strip().lower()
    low = re.sub(r"^(?:the\s+|a\s+|an\s+)", "", low)
    if low in ("browser", "the browser", "web browser"):
        return "chrome"
    if "youtube" in low or low == "yt":
        return "youtube"
    if low in ("mail", "email", "gmail", "inbox"):
        return "gmail"
    if "brave" in low:
        return "brave"
    if "edge" in low:
        return "edge"
    if "chrome" in low:
        return "chrome"
    if "notepad" in low:
        return "notepad"
    if "spotify" in low:
        return "spotify"
    if "whatsapp" in low or low == "wa":
        return "whatsapp"
    if "camera" in low:
        return "camera"
    # strip trailing junk
    low = re.sub(r"\s+(?:and|then|please).*$", "", low).strip()
    return low or "chrome"


def _split_clauses(transcript: str) -> List[str]:
    t = (transcript or "").strip()
    if not t:
        return []
    # Protect "on youtube/google …" so splitter doesn't tear site binding
    protected: List[str] = []

    def _protect(m: re.Match) -> str:
        protected.append(m.group(0))
        return f" __PROT{len(protected) - 1}__ "

    t2 = re.sub(
        r"\bon\s+(?:youtube|google|gmail|mail)\s+(?:search(?:\s+for)?|find|look\s+up)\s+.+",
        _protect,
        t,
        flags=re.I,
    )
    parts = [p.strip(" .,") for p in _SPLIT.split(t2) if p and p.strip(" .,")]
    out: List[str] = []
    for p in parts:
        for i, orig in enumerate(protected):
            p = p.replace(f"__PROT{i}__", orig)
        p = re.sub(r"\s+", " ", p).strip()
        if p:
            out.append(p)
    return out or [t]


def _parse_clause(clause: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse one clause into an IR action. Mutates ctx (last_site, opened_browser)."""
    c = clause.strip()
    low = c.lower()

    # play the first / second / …
    m = re.match(
        r"^(?:please\s+)?(?:play|open)\s+(?:the\s+)?(first|second|third|1st|2nd|3rd|1|2|3)\b",
        low,
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
        return {"op": "play_nth", "index": idx_map.get(m.group(1), 0)}

    # on youtube/google search X
    m = re.match(
        r"^(?:please\s+)?on\s+(youtube|google|gmail|mail)\s+"
        r"(?:(?:then\s+)?(?:search(?:\s+for)?|find|look\s+up)\s+)?(.+)$",
        low,
    )
    if m:
        site = _SITE_NAMES.get(m.group(1), m.group(1))
        q = m.group(2).strip()
        ctx["last_site"] = site
        if site == "youtube":
            return {"op": "site_search", "site": "youtube", "query": q}
        if site == "gmail":
            return {"op": "mail_search", "query": q}
        return {"op": "site_search", "site": "google", "query": q}

    # search youtube for X / youtube search X
    m = re.match(
        r"^(?:please\s+)?(?:search|find)\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)$|"
        r"^(?:please\s+)?youtube\s+(?:search\s+(?:for\s+)?)?(.+)$",
        low,
    )
    if m:
        q = (m.group(1) or m.group(2) or "").strip()
        ctx["last_site"] = "youtube"
        return {"op": "site_search", "site": "youtube", "query": q}

    # open / launch / go to X
    m = re.match(
        r"^(?:please\s+)?(?:open|launch|start|go\s+to)\s+(.+)$",
        low,
    )
    if m:
        target = m.group(1).strip()
        # "open the full screen" / maximize → hotkey, not an app
        act = None
        if re.search(r"full[\s-]*screen|fullscreen", target):
            act = "fullscreen"
        elif re.search(r"\bmaximize\b", target):
            act = "maximize"
        elif re.search(r"\bminimize\b", target):
            act = "minimize"
        elif re.search(r"new\s+tab", target):
            act = "new tab"
        if act:
            return {"op": "hotkey", "action": act}
        app = _app_from(target)
        if app == "youtube":
            ctx["last_site"] = "youtube"
            ctx["opened_browser"] = True
            return {"op": "navigate_site", "site": "youtube"}
        if app == "gmail":
            ctx["last_site"] = "gmail"
            return {"op": "open_app", "app": "gmail"}
        if app in _BROWSER_APPS or app == "chrome":
            ctx["opened_browser"] = True
            return {"op": "open_app", "app": "chrome" if app == "browser" else app}
        return {"op": "open_app", "app": app}

    # search for X  (may be navigate if X is a site name after browser open)
    m = re.match(
        r"^(?:please\s+)?(?:search(?:\s+for)?|find|look\s+up|google)\s+(.+)$",
        low,
    )
    if m:
        q = m.group(1).strip()
        q_low = q.lower()
        # "search for youtube" → navigate, not google query
        site_hit = None
        for name, site in _SITE_NAMES.items():
            if q_low == name or q_low.startswith(name + " "):
                site_hit = site
                rest = q_low[len(name) :].strip()
                break
        if site_hit == "youtube" and (not rest or rest.startswith("and")):
            ctx["last_site"] = "youtube"
            return {"op": "navigate_site", "site": "youtube"}
        if site_hit == "youtube" and rest:
            # search for youtube samsung → youtube search samsung? Prefer navigate+search
            ctx["last_site"] = "youtube"
            return {"op": "site_search", "site": "youtube", "query": rest}
        if site_hit == "gmail":
            return {"op": "mail_search", "query": rest or "in:inbox"}
        if ctx.get("last_site") == "youtube":
            return {"op": "site_search", "site": "youtube", "query": q}
        return {"op": "site_search", "site": "google", "query": q}

    # type / write
    m = re.match(r"^(?:please\s+)?(?:type|write|dictate)\s+(.+)$", low)
    if m:
        return {"op": "type_text", "text": m.group(1).strip()}

    # next / previous video
    if re.match(r"^(?:please\s+)?(?:next|previous|prev)\s+(?:video|one)?\s*$", low):
        action = "prev" if "prev" in low else "next"
        return {"op": "youtube_media", "action": action}

    return None


def _ir_to_steps(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compile IR actions into orchestrator tool steps."""
    steps: List[Dict[str, Any]] = []
    opened_yt = False
    for i, a in enumerate(actions):
        op = a.get("op")
        delay = 1.0 if i > 0 else 0.0
        if op == "open_app":
            steps.append(
                {"tool": "open_app", "args": {"app": a["app"]}, "delay": delay}
            )
        elif op == "navigate_site":
            site = a.get("site")
            if site == "youtube":
                steps.append({"tool": "youtube_home", "args": {}, "delay": delay or 0.8})
                opened_yt = True
            elif site == "gmail":
                steps.append(
                    {"tool": "open_app", "args": {"app": "gmail"}, "delay": delay}
                )
            else:
                steps.append(
                    {
                        "tool": "google_search",
                        "args": {"query": site or ""},
                        "delay": delay,
                    }
                )
        elif op == "site_search":
            site = a.get("site")
            q = a.get("query") or ""
            if site == "youtube":
                # If we already navigated home, still use youtube_search (opens+searches)
                steps.append(
                    {
                        "tool": "youtube_search",
                        "args": {"query": q},
                        "delay": 0.5 if opened_yt else (delay or 0.8),
                    }
                )
                opened_yt = True
            else:
                steps.append(
                    {
                        "tool": "google_search",
                        "args": {"query": q},
                        "delay": delay or 1.0,
                    }
                )
        elif op == "play_nth":
            steps.append(
                {
                    "tool": "play_nth",
                    "args": {"index": int(a.get("index") or 0)},
                    "delay": delay or 0.5,
                }
            )
        elif op == "type_text":
            steps.append(
                {
                    "tool": "type_text",
                    "args": {"text": a.get("text", "")},
                    "confirm": False,
                    "delay": delay,
                }
            )
        elif op == "youtube_media":
            steps.append(
                {
                    "tool": "youtube_media",
                    "args": {"action": a.get("action", "play")},
                    "delay": delay,
                }
            )
        elif op == "mail_search":
            steps.append(
                {
                    "tool": "mail_search",
                    "args": {"query": a.get("query", "")},
                    "delay": delay,
                }
            )
        elif op == "mail_summarize":
            steps.append({"tool": "mail_summarize", "args": {}, "delay": delay})
        elif op == "mail_compose":
            steps.append(
                {
                    "tool": "mail_compose",
                    "args": {
                        "to": a.get("to", ""),
                        "subject": a.get("subject", ""),
                        "body": a.get("body", ""),
                    },
                    "confirm": True,
                    "delay": delay,
                }
            )
        elif op == "hotkey":
            steps.append(
                {
                    "tool": "hotkey",
                    "args": {"action": a.get("action", "")},
                    "delay": delay or 0.5,
                }
            )
    return steps


def _optimize_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop redundant youtube_home only when it is the sole prep before search."""
    has_browser_open = any(
        a.get("op") == "open_app" and a.get("app") in ("chrome", "brave", "edge", "browser")
        for a in actions
    )
    out: List[Dict[str, Any]] = []
    i = 0
    while i < len(actions):
        a = actions[i]
        nxt = actions[i + 1] if i + 1 < len(actions) else None
        # Only collapse home→search when user did NOT also ask to open a browser
        if (
            not has_browser_open
            and a.get("op") == "navigate_site"
            and a.get("site") == "youtube"
            and nxt
            and nxt.get("op") == "site_search"
            and nxt.get("site") == "youtube"
        ):
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def parse_clause_plan(transcript: str) -> Optional[Dict[str, Any]]:
    """Return an orchestrator plan if transcript is a multi-clause chain (≥2 actions)."""
    t = (transcript or "").strip()
    if not t or not looks_compound(t):
        return None

    clauses = _split_clauses(t)
    if len(clauses) < 2:
        # Single clause but multiple verbs — try soft split on "search for" after open
        if re.search(r"\bopen\b.+\bsearch\b", t, re.I):
            clauses = _split_clauses(
                re.sub(r"\s+search\s+", " and search ", t, count=1, flags=re.I)
            )
        else:
            return None

    ctx: Dict[str, Any] = {"last_site": "", "opened_browser": False}
    actions: List[Dict[str, Any]] = []
    leftover: List[str] = []

    for clause in clauses:
        act = _parse_clause(clause, ctx)
        if act:
            actions.append(act)
        else:
            leftover.append(clause)

    actions = _optimize_actions(actions)
    if len(actions) < 2:
        return None

    truncated = False
    if len(actions) > MAX_STEPS:
        leftover = [str(a) for a in actions[MAX_STEPS:]] + leftover
        actions = actions[:MAX_STEPS]
        truncated = True

    steps = _ir_to_steps(actions)
    if len(steps) < 2:
        return None

    # Intent label for persona / audit
    intent = "multi_step"
    if any(s["tool"].startswith("youtube") for s in steps):
        intent = "youtube_search"
    elif any(s["tool"].startswith("mail") for s in steps):
        intent = "mail_search"

    reply_bits = []
    for s in steps:
        tool = s["tool"]
        args = s.get("args") or {}
        if tool == "open_app":
            reply_bits.append(f"open {args.get('app')}")
        elif tool == "youtube_home":
            reply_bits.append("open YouTube")
        elif tool == "youtube_search":
            reply_bits.append(f"search YouTube for {args.get('query')}")
        elif tool == "google_search":
            reply_bits.append(f"search Google for {args.get('query')}")
        elif tool == "play_nth":
            reply_bits.append(f"play result {int(args.get('index', 0)) + 1}")
        else:
            reply_bits.append(tool.replace("_", " "))

    reply = ". ".join(reply_bits[:4]).capitalize()
    if len(reply_bits) > 4:
        reply += f" (+{len(reply_bits) - 4} more)"
    if not reply.endswith("."):
        reply += "."
    if truncated or leftover:
        reply += " Say continue if there's more."

    plan: Dict[str, Any] = {
        "intent": intent,
        "confidence": 0.94,
        "steps": steps,
        "source": "clause_plan",
        "reply": reply,
        "auto_type": True,
    }
    if leftover and truncated:
        plan["awaiting"] = "slot:continue"
        plan["pending_prefix"] = " and ".join(leftover[:2])
    return plan


__all__ = ["parse_clause_plan", "looks_compound", "MAX_STEPS"]
