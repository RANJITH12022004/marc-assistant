#!/usr/bin/env python3
"""Marc coordinator. Hermes agent plans leftovers; Needle/Meta are LLMs. Laptop and phone execute."""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cognee_bridge
import hermes_client
import mind_store
import muse_client

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "marc")
AGENT_MODEL = os.environ.get("MARC_AGENT_MODEL", "") or OLLAMA_MODEL
AGENT_MAX_HOPS = 5
LAYA_URL = os.environ.get("LAYA_URL", "http://127.0.0.1:8091/score")
LAPTOP_URL = os.environ.get("MARC_LAPTOP_URL", "").rstrip("/")
TOKEN_PATH = os.environ.get("MARC_TOKEN_FILE", "/home/rox/marc/secret")
MEMORY_PATH = os.environ.get("MARC_MEMORY_FILE", "/home/rox/marc/memory.json")
CURSOR_URL = os.environ.get("MARC_CURSOR_URL", "http://127.0.0.1:8093").rstrip("/")
BIND = os.environ.get("MARC_BIND", "127.0.0.1")
PORT = int(os.environ.get("MARC_PORT", "8090"))
CONFIRM_TTL = int(os.environ.get("MARC_CONFIRM_TTL", "300"))
MARC_EMAIL = os.environ.get("MARC_EMAIL", "").strip()
NEEDLE_BIN = os.environ.get("NEEDLE_BIN", "/home/rox/marc/needle-runtime/needle")
NEEDLE_MODEL = os.environ.get("NEEDLE_MODEL", "/home/rox/marc/needle-runtime/needle3.cact")
NEEDLE_DIR = os.environ.get("NEEDLE_DIR", "/home/rox/marc")
NEEDLE_TOOLS_PATH = os.environ.get("NEEDLE_TOOLS", os.path.join(NEEDLE_DIR, "needle_tools.json"))
NEEDLE_INDEX_PATH = os.environ.get("NEEDLE_INDEX", os.path.join(NEEDLE_DIR, "needle_tools.idx"))
NEEDLE_URL = os.environ.get("NEEDLE_URL", "http://127.0.0.1:8094").rstrip("/")
NEEDLE_SYSTEM_PATH = os.environ.get("NEEDLE_SYSTEM", os.path.join(NEEDLE_DIR, "needle_system.txt"))
NEEDLE_ACT = float(os.environ.get("NEEDLE_ACT", "0.45"))
PLANNER = os.environ.get("MARC_PLANNER", "hermes").strip().lower()
_needle_lock = threading.Lock()
_ACTIVITY_LOCK = threading.Lock()
_ACTIVITY_RUNS: list[dict] = []
_ACTIVITY_MAX = 60
_ACTION_RE = re.compile(
    r"(?i)\b(?:open|launch|start|close|quit|exit|play|pause|resume|next|previous|stop|"
    r"send|call|dial|text|whatsapp|instagram|search|volume|mute|restart|docker|"
    r"containers|ollama|n8n|ls|files|journal|install|shell|bash|directory|folder|"
    r"status|check|temp|cpu)\b|"
    r"\bon\s+(?:my\s+|the\s+)?(?:laptop|computer|pc|phone|mobile|server|linux)\b"
)

CONFIRM_TOOLS = {"mail_send", "mail_compose", "dial", "open_food_search"}
PHONE_TOOLS = {
    "play_music", "dial", "whatsapp_prefill", "whatsapp_send", "sms_send", "instagram_send",
    "open_food_search", "media_key", "ui_tap", "type_into", "open_app", "close_app",
}
LAPTOP_TOOLS = {
    "open_app", "close_app", "focus_window", "google_search", "youtube_search", "youtube_home",
    "youtube_media", "play_nth", "type_text", "hotkey", "volume_media", "mail_search",
    "mail_summarize", "mail_compose", "mail_send", "calendar_list", "calendar_create",
    "drive_search", "system_status", "web_search", "open_url",
    "desktop_status", "desktop_snapshot", "desktop_click", "desktop_type", "desktop_press",
}
SERVER_TOOLS = {
    "server_status", "service_status", "service_restart", "docker_list", "docker_restart",
    "server_shell",
}
MIND_TOOLS = {"mind_now", "mind_note", "mind_recall", "brain_recall"}
SERVER_UNITS = {
    "api": "marc-api",
    "marc-api": "marc-api",
    "desk": "marc-desk",
    "marc-desk": "marc-desk",
    "site": "marc-desk",
    "web": "marc-desk",
    "bridge": "marc-bridge",
    "marc-bridge": "marc-bridge",
    "ollama": "ollama",
    "model": "ollama",
    "qwen": "ollama",
}
SERVER_CONTAINERS = {
    "n8n": "marc-n8n",
    "marc-n8n": "marc-n8n",
}

PLANNER_SYSTEM = """You are Marc's planner. Return ONLY JSON.
{"reply":"short spoken line","steps":[{"device":"laptop","tool":"tool_name","args":{}}]}
Example:
User: email Sam about the lease
{"reply":"Email Sam about the lease.","steps":[{"device":"laptop","tool":"mail_compose","args":{"to":"Sam","subject":"Lease","body":"Hi Sam, about the lease."}}]}
User: play the song on my phone
{"reply":"Playing it on your phone.","steps":[{"device":"phone","tool":"play_music","args":{"query":"the song"}}]}
Rules:
- One step per action, in the order the user said them. Max 6 steps. Every slot goes inside args.
- device is laptop, phone, or server. Default from the session or chosen target. "on my laptop/computer/PC", "on my phone/mobile", and "on the server/linux" override.
- Phone tools: play_music {query}, media_key {action: play|pause|next|previous|stop}, open_app {name}, close_app {name}, whatsapp_send {contact,text,send}, sms_send {contact,text,send}, instagram_send {contact,text,send}, dial {number}, open_food_search {app,query}, ui_tap {text}.
- send is true only when the user explicitly says send. Next, pause, and close stay on the phone app already open.
- open_app and close_app on the phone use args.name. Laptop open_app still uses args.app.
- Laptop tools: open_app, close_app, focus_window, google_search, youtube_search, youtube_home, youtube_media, play_nth, type_text, hotkey, volume_media, mail_search, mail_summarize, mail_compose, mail_send, calendar_list, calendar_create, drive_search, system_status, web_search, open_url.
- Server tools: server_status {}, service_status {name}, service_restart {name}, docker_list {}, docker_restart {name}. Names are api, desk, bridge, ollama, n8n.
- Copy the person's name into args.to. Put the topic in subject and a short body.
- No sudo, no rm -rf /, no reboot, no shutdown.
- If the user named an action or device, steps must not be empty.
- Chat only (no action verbs): steps=[]. Missing slot: steps=[] and ask one question in reply.
"""

PENDING: dict[str, dict] = {}
_inbox_lock = threading.Lock()
_inbox: list[dict] = []
_LAST_RUN: dict = {}
_CHAT: dict[str, list] = {}
_memory_lock = threading.Lock()
_MEMORY: dict = {}
CHAT_SYSTEM = (
    "You are Marc, Ranjith's personal assistant. Answer in a few short sentences. "
    "You cannot run apps or tools in this chat."
)
ACTION_RE = (
    r"\b(?:open|launch|start|close|quit|exit|play|pause|resume|next|previous|stop|"
    r"send|call|dial|text|whatsapp|instagram|search|volume|mute|restart|docker|"
    r"containers|ollama|n8n|ls|files|journal|install|shell|bash|directory|folder)\b|"
    r"\bon\s+(?:my\s+|the\s+)?(?:laptop|computer|pc|phone|mobile|server|linux)\b|"
    r"/home/rox"
)
AGENT_HINT_RE = (
    r"\b(?:ls|list\s+files|journalctl|journal|install|apt-get|pip3?|bash|shell|"
    r"directory|folder|df\b|free\s+-|ps\s+aux|cat\s+|head\s+|tail\s+|find\s+|grep\s+|"
    r"is\s+ollama|ollama\s+(?:up|status|running|active))\b|"
    r"/home/rox"
)
SHELL_DENY_RE = (
    r"rm\s+-rf\s+/($|\s)|rm\s+-rf\s+/\*|rm\s+-rf\s+--no-preserve-root|"
    r"\b(shutdown|reboot|halt|poweroff|mkfs)\b|dd\s+.*of=/dev|"
    r"chmod\s+777\s+/|\bpasswd\b|\bsudo\b|pkill\s+-9|: \(\)|fork\s*bomb"
)
AGENT_SYSTEM = """You are Marc on the home server. Return ONLY one JSON object.
{"think":"short","tool":"tool_name","args":{},"done":false}
or {"done":true,"reply":"spoken line"}
Tools: server_status {}, service_status {name}, service_restart {name}, docker_list {}, docker_restart {name}, server_shell {cmd}, open_app, close_app.
name is api, desk, bridge, ollama, or n8n. cmd runs as user rox in /home/rox/marc.
One tool per turn. After Observation, call another tool or done true.
No sudo, no rm -rf /, no reboot, no shutdown.
"""


def _token() -> str:
    try:
        return open(TOKEN_PATH, encoding="utf-8").read().strip()
    except OSError:
        return ""


def _post(url: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _relax_json(blob: str) -> str:
    """Repair the small JSON mistakes Qwen 0.5B actually makes."""
    out: list[str] = []
    i = 0
    n = len(blob)
    in_str = False
    while i < n:
        c = blob[i]
        if in_str:
            if c == "\\":
                out.append(c)
                if i + 1 < n:
                    out.append(blob[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if c == '"':
                in_str = False
                out.append(c)
                i += 1
                continue
            if c == "\n":
                out.append("\\n")
                i += 1
                continue
            if c == "\r":
                i += 1
                continue
            out.append(c)
            i += 1
            continue
        if c == "'":
            out.append('"')
            i += 1
            while i < n:
                ch = blob[i]
                if ch == "\\":
                    out.append(ch)
                    if i + 1 < n:
                        out.append(blob[i + 1])
                        i += 2
                    else:
                        i += 1
                    continue
                if ch == "'":
                    out.append('"')
                    i += 1
                    break
                if ch == '"':
                    out.append('\\"')
                elif ch == "\n":
                    out.append("\\n")
                elif ch != "\r":
                    out.append(ch)
                i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == ":":
            out.append(c)
            i += 1
            while i < n and blob[i] in " \t":
                out.append(blob[i])
                i += 1
            if i < n and blob[i] not in '{["\'tfn0123456789-':
                out.append('"')
                while i < n and blob[i] not in ",}\n\r":
                    ch = blob[i]
                    out.append('\\"' if ch == '"' else ch)
                    i += 1
                out.append('"')
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("planner did not return JSON")
    blob = raw[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return json.loads(_relax_json(blob))


def _needle_prop(type_name: str, description: str, **extra) -> dict:
    prop = {"type": type_name, "description": description}
    prop.update(extra)
    return prop


def _needle_tool(
    name: str,
    description: str,
    properties: dict,
    required: list | None = None,
    triggers: list | None = None,
) -> dict:
    schema = {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
        },
    }
    if required:
        schema["parameters"]["required"] = required
    if triggers:
        schema["triggers"] = triggers
    return schema


def _needle_tool_schemas() -> list[dict]:
    """Keep this small. Needle 3 reads every tool each turn; extras tank confidence."""
    return [
        _needle_tool(
            "open_app",
            "Open an app by name.",
            {"name": _needle_prop("string", "App name such as Terminal, Google, YouTube, Spotify")},
            ["name"],
            [r"\b(?:open|launch)\b"],
        ),
        _needle_tool(
            "type_into",
            "Type into the open app. send true means press enter after typing.",
            {
                "text": _needle_prop("string", "Exact text to type"),
                "send": _needle_prop("boolean", "True when the user said enter or send it"),
            },
            ["text"],
            [r"\b(?:type|enter|ipconfig|ssh)\b"],
        ),
        _needle_tool(
            "play_music",
            "Play a song on Spotify. Not for YouTube.",
            {"query": _needle_prop("string", "Song or artist")},
            None,
            [r"\bspotify\b", r"\bplay\b(?![\s\S]*\byoutube\b)"],
        ),
        _needle_tool(
            "youtube_search",
            "Search YouTube for a video.",
            {"query": _needle_prop("string", "Video query after youtube or search")},
            ["query"],
            [r"\byoutube\b"],
        ),
        _needle_tool(
            "google_search",
            "Search Google for a query.",
            {"query": _needle_prop("string", "Search query after google or search for")},
            ["query"],
            [r"\bgoogle\b"],
        ),
        _needle_tool(
            "whatsapp_send",
            "WhatsApp a named contact.",
            {
                "contact": _needle_prop("string", "Person to message"),
                "text": _needle_prop("string", "Message body"),
                "send": _needle_prop("boolean", "True only when the user said send"),
            },
            ["contact", "text"],
            [r"\bwhatsapp\b"],
        ),
        _needle_tool(
            "server_status",
            "Home server CPU, temperature, RAM, and service health.",
            {},
            None,
            [r"\bserver\b"],
        ),
    ]


def _ensure_needle_files() -> None:
    os.makedirs(NEEDLE_DIR, exist_ok=True)
    payload = json.dumps(_needle_tool_schemas(), separators=(",", ":"))
    current = ""
    try:
        with open(NEEDLE_TOOLS_PATH, encoding="utf-8") as handle:
            current = handle.read()
    except OSError:
        current = ""
    if current != payload:
        with open(NEEDLE_TOOLS_PATH, "w", encoding="utf-8") as handle:
            handle.write(payload)
        try:
            os.remove(NEEDLE_INDEX_PATH)
        except OSError:
            pass
    facts = _needle_system("phone")
    try:
        with open(NEEDLE_SYSTEM_PATH, encoding="utf-8") as handle:
            old = handle.read()
    except OSError:
        old = ""
    if old != facts:
        with open(NEEDLE_SYSTEM_PATH, "w", encoding="utf-8") as handle:
            handle.write(facts)


def _needle_system(session: str) -> str:
    now = time.strftime("%Y-%m-%d %a %H:%M")
    device = "phone" if session == "phone" else "laptop"
    return f"date: {now}; locale: en-IN; device: {device}; user: Ranjith; assistant: Marc"


def _parse_needle_out(raw: str) -> dict:
    blob = (raw or "").strip()
    start = blob.find("{")
    end = blob.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        parsed = json.loads(blob[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _needle_calls(parsed: dict) -> list:
    calls = parsed.get("function_calls") or []
    if not isinstance(calls, list):
        return []
    return [call for call in calls if isinstance(call, dict)]


def _heuristic_plan(text: str, session: str = "") -> dict | None:
    scripted = _scripted_plan(text, session)
    if scripted:
        return scripted
    steps = _obvious_steps(text, _coerce_steps(text, _fill_slots(text, _normalize_steps(_fallback_steps(text)))))
    if not steps:
        return None
    print("[marc-api] needle-fallback", [step.get("tool") for step in steps], flush=True)
    return {"reply": _brief_reply(steps, ""), "steps": steps}


def _steps_from_needle_calls(text: str, parsed: dict, session: str = "") -> dict:
    try:
        confidence = float(parsed.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    steps = []
    if confidence >= NEEDLE_ACT:
        for call in _needle_calls(parsed):
            name = str(call.get("name") or "").strip()
            args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            if name:
                steps.append({"tool": name, "args": dict(args)})
        steps = _coerce_steps(text, _fill_slots(text, _normalize_steps(steps)))
        steps = _obvious_steps(text, steps)
    print(
        "[marc-api] needle",
        [step.get("tool") for step in steps],
        "confidence", parsed.get("confidence"),
        "held", [call.get("name") for call in (parsed.get("suppressed_calls") or []) if isinstance(call, dict)],
        flush=True,
    )
    if not steps:
        return _heuristic_plan(text, session) or {"reply": "I don't have a tool for that.", "steps": []}
    return {"reply": _brief_reply(steps, ""), "steps": steps}


def _needle_reset() -> None:
    try:
        _post(NEEDLE_URL + "/reset", {}, timeout=4)
    except Exception:  # noqa: BLE001
        pass


def plan_with_needle(text: str, note: str = "", context: str = "", session: str = "") -> dict:
    """Ask the local Needle server which Marc tools to run. Empty calls means no action."""
    prompt = text.strip()
    if note:
        prompt = f"{prompt}\n{note}"
    parsed = {}
    with _needle_lock:
        _needle_reset()
        try:
            parsed = _post(NEEDLE_URL + "/complete", {"input": prompt}, timeout=55)
        except Exception as exc:  # noqa: BLE001
            print("[marc-api] needle fail", exc, flush=True)
            _needle_reset()
            fallback = _heuristic_plan(text, session)
            if fallback:
                return fallback
            kind = str(exc).lower()
            if "timed out" in kind or "timeout" in kind:
                return {"reply": "Needle is still thinking.", "steps": []}
            return {"reply": "Needle isn't running.", "steps": []}
        _needle_reset()
    if not isinstance(parsed, dict):
        parsed = _parse_needle_out(str(parsed))
    if "function_calls" not in parsed and isinstance(parsed.get("output"), str):
        parsed = _parse_needle_out(parsed.get("output") or "")
    return _steps_from_needle_calls(text, parsed, session)


def _looks_like_action(text: str) -> bool:
    return bool(_ACTION_RE.search(text or ""))


def plan_with_hermes(text: str, note: str = "", context: str = "", session: str = "") -> dict:
    """Hermes agent (Meta AI ± marc-muse). Falls back to Needle LLM, then heuristics."""
    planned = hermes_client.plan_command(text, note=note, context=context, session=session)
    steps = planned.get("steps") if isinstance(planned, dict) else None
    reply = str((planned or {}).get("reply") or "").strip()
    source = str((planned or {}).get("source") or "hermes")
    if isinstance(steps, list) and steps:
        return {"reply": reply or "On it.", "steps": steps, "source": source}
    # Hermes/Meta returned a spoken-only refusal or empty plan with a clear reply.
    if reply and not steps and source in ("muse", "meta"):
        low = reply.lower()
        if any(token in low for token in ("can't", "cannot", "refuse", "stopping", "paused", "isn't running")):
            return {"reply": reply, "steps": [], "source": source}
    # Action-like utterances must get tools: try heuristics before Needle chat.
    if _looks_like_action(text):
        heuristic = _heuristic_plan(text, session)
        if heuristic and (heuristic.get("steps") or []):
            return {**heuristic, "source": "heuristic"}
    needle = plan_with_needle(text, note=note, context=context, session=session)
    if isinstance(needle, dict) and (needle.get("steps") or []):
        return {**needle, "source": needle.get("source") or "needle"}
    if _looks_like_action(text):
        heuristic = _heuristic_plan(text, session)
        if heuristic:
            return {**heuristic, "source": "heuristic"}
    if reply:
        return {"reply": reply, "steps": [], "source": source}
    if source == "hermes-miss":
        return {"reply": "Hermes isn't running.", "steps": [], "source": source}
    return needle if isinstance(needle, dict) else {"reply": "Hermes isn't running.", "steps": [], "source": source}


def plan_command(text: str, note: str = "", context: str = "", session: str = "") -> dict:
    if PLANNER in ("hermes", "muse", "meta"):
        return plan_with_hermes(text, note=note, context=context, session=session)
    if PLANNER == "qwen":
        return plan_with_qwen(text, note=note, context=context)
    return plan_with_needle(text, note=note, context=context, session=session)


def plan_with_qwen(text: str, note: str = "", context: str = "") -> dict:
    user = text if not note else f"{text}\n\nScorer note: {note}\nReturn corrected JSON only."
    if context:
        user = f"{context}\nUser: {user}"
    data = _post(
        OLLAMA_URL,
        {
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": [
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": user},
            ],
            "format": "json",
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_predict": 160, "num_ctx": 768, "repeat_penalty": 1.15},
        },
        timeout=90,
    )
    content = ((data.get("message") or {}).get("content")) or ""
    try:
        parsed = _extract_json(content)
    except (json.JSONDecodeError, ValueError) as exc:
        print("[marc-api] planner raw:", content[:400], flush=True)
        print("[marc-api] planner JSON:", exc, flush=True)
        parsed = {}
    reply = str(parsed.get("reply") or "").strip()
    if len(reply) > 240:
        reply = ""
    steps = _coerce_steps(text, _fill_slots(text, _normalize_steps(parsed.get("steps") or [])))
    if not steps:
        steps = _fallback_steps(text)
    before = len(steps)
    steps = _obvious_steps(text, steps)
    if steps and (not reply or len(steps) > before):
        reply = _summary(steps[-1] if len(steps) > before else steps[0])
    reply = _brief_reply(steps, reply)
    return {"reply": reply, "steps": steps}


def _brief_reply(steps: list, reply: str) -> str:
    """Keep the island line short. The action itself is the icon and the phone step."""
    if not steps:
        return reply
    tool = steps[0].get("tool")
    args = steps[0].get("args") or {}
    if tool == "play_music":
        return "Playing on Spotify."
    if tool == "open_app":
        names = [str((step.get("args") or {}).get("name") or (step.get("args") or {}).get("app") or "").strip() for step in steps]
        names = [name for name in names if name]
        if len(names) > 1:
            return "Opening " + ", then ".join(names) + "."
        return f"Opening {names[0]}." if names else "Opening it."
    if tool == "close_app":
        name = str(args.get("name") or "it").strip()
        return f"Closing {name}."
    if tool == "type_into":
        return "Typed."
    if tool == "media_key":
        action = str(args.get("action") or "play")
        return {"next": "Next.", "previous": "Previous.", "pause": "Paused.", "stop": "Stopped.", "play": "Playing."}.get(action, "Done.")
    if tool == "whatsapp_send":
        who = str(args.get("contact") or args.get("phone") or "them")
        return f"Sent to {who} on WhatsApp." if args.get("send") else f"WhatsApp to {who}."
    if tool == "sms_send":
        who = str(args.get("contact") or "them")
        return f"Sent to {who}." if args.get("send") else f"Text to {who}."
    if tool == "instagram_send":
        who = str(args.get("contact") or "them")
        return f"Sent to {who} on Instagram." if args.get("send") else f"Instagram to {who}."
    if tool in ("mail_compose", "mail_send"):
        who = str(args.get("to") or "").strip()
        return f"Mail to {who}." if who else "Mail."
    if tool == "mind_now":
        return "Checking the mind."
    if tool == "mind_note":
        return "Saving a note."
    if tool == "mind_recall":
        return "Looking that up."
    if len(reply) > 32:
        return reply[:30].rstrip() + "…"
    return reply


SLOT_KEYS = ("to", "subject", "body", "query", "app", "name", "number", "phone", "text", "url", "action", "contact")


def _normalize_steps(raw_steps: list) -> list:
    steps = []
    for step in raw_steps:
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool") or "")
        args = dict(step.get("args") or {}) if isinstance(step.get("args"), dict) else {}
        lifted = {key: step[key] for key in SLOT_KEYS if key in step and key not in args}
        if not tool and steps and (lifted or isinstance(step.get("args"), dict)):
            if lifted:
                steps[-1]["args"].update(lifted)
            if isinstance(step.get("args"), dict):
                steps[-1]["args"].update(step["args"])
            continue
        if not tool:
            continue
        args.update(lifted)
        device = "phone" if tool in PHONE_TOOLS else "laptop"
        steps.append({"device": device, "tool": tool, "args": args})
        if len(steps) >= 6:
            break
    return steps


def _fill_slots(text: str, steps: list) -> list:
    """Fill slots Qwen left blank, using words already in the utterance."""
    import re

    low = text.lower()
    about = re.search(r"\babout\s+(.+?)(?:\s+and\b|\s+then\b|$)", text, re.I)
    topic = about.group(1).strip(" .") if about else ""
    for step in steps:
        args = step["args"]
        tool = step["tool"]
        if tool in ("mail_compose", "mail_send"):
            to = str(args.get("to") or "").strip()
            if to and to.lower() not in low and len(to) > 2 and to[:-1].lower() in low:
                args["to"] = to[:-1]
            if not str(args.get("subject") or "").strip() and topic:
                args["subject"] = topic[:1].upper() + topic[1:]
            if not str(args.get("body") or "").strip():
                who = args.get("to") or "there"
                args["body"] = f"Hi {who}, about {args.get('subject') or topic or 'this'}."
        if tool == "play_music":
            named = _music_query(text)
            if named:
                args["query"] = named
            elif _generic_music(str(args.get("query") or "")):
                args["query"] = ""
        if tool == "open_food_search" and not str(args.get("query") or "").strip():
            args["query"] = topic or text
        if tool in ("whatsapp_prefill", "whatsapp_send", "sms_send", "instagram_send"):
            contact, body = _contact_and_body(text, "phone")
            if not str(args.get("contact") or args.get("phone") or args.get("to") or "").strip() and contact:
                args["contact"] = contact
            if not str(args.get("text") or "").strip():
                if body:
                    args["text"] = body
                elif topic:
                    args["text"] = topic
    return steps


def _generic_music(query: str) -> bool:
    import re

    return bool(re.fullmatch(r"(?:(?:some|a|the)\s+)?(?:music|songs?|spotify)?", (query or "").strip(), re.I))


def _music_query(text: str) -> str:
    """Empty means resume Spotify. A named song is the search that should start playing."""
    import re

    played = re.search(r"\bplay\s+(.+?)(?:\s+on\s+(?:my\s+)?(?:phone|spotify))?$", text, re.I)
    query = played.group(1).strip(" .") if played else ""
    query = re.sub(r"\s+on\s+(?:my\s+)?(?:phone|spotify)$", "", query, flags=re.I).strip(" .")
    return "" if _generic_music(query) else query


def _fallback_steps(text: str) -> list:
    """When Qwen emits no allowlisted step, use the phrase the user actually said."""
    import re

    low = text.lower()
    steps = []
    email = re.search(r"\bemail\s+(.+?)\s+about\s+(.+?)(?:\s+and\b|\s+then\b|$)", text, re.I)
    if email:
        who = email.group(1).strip()
        topic = email.group(2).strip(" .")
        steps.append({
            "device": "laptop",
            "tool": "mail_compose",
            "args": {"to": who, "subject": topic[:1].upper() + topic[1:], "body": f"Hi {who}, about {topic}."},
        })
    if "whatsapp" in low:
        who = re.search(r"\bwhatsapp\s+(.+?)\s+that\s+", text, re.I)
        said = re.search(r"\bthat\s+(.+)$", text, re.I)
        steps.append({
            "device": "phone",
            "tool": "whatsapp_prefill",
            "args": {
                "phone": who.group(1).strip() if who else "",
                "text": said.group(1).strip(" .") if said else "",
            },
        })
    if "swiggy" in low or "zomato" in low:
        dish = re.search(r"\bfor\s+(.+)$", text, re.I) or re.search(
            r"\b(?:order|get|find)\s+(.+?)(?:\s+on\s+(?:zomato|swiggy))?$", text, re.I
        )
        steps.append({
            "device": "phone",
            "tool": "open_food_search",
            "args": {
                "app": "zomato" if "zomato" in low else "swiggy",
                "query": dish.group(1).strip(" .") if dish else "",
            },
        })
    if re.search(r"\b(call|dial)\b", low):
        who = re.search(r"\b(?:call|dial)\s+(.+)$", text, re.I)
        steps.append({
            "device": "phone",
            "tool": "dial",
            "args": {"number": who.group(1).strip(" .") if who else ""},
        })
    if re.search(r"\bplay\b", low) and "youtube" not in low and ("phone" in low or "song" in low or "music" in low or "spotify" in low):
        steps.append({
            "device": "phone",
            "tool": "play_music",
            "args": {"query": _music_query(text)},
        })
    youtube = re.search(r"\byoutube\b", low) and re.search(r"\b(?:search|play|find|for)\b", low)
    if youtube:
        query = re.search(r"\b(?:youtube(?:\s+for)?|for)\s+(.+)$", text, re.I)
        steps.append({
            "device": "laptop",
            "tool": "youtube_search",
            "args": {"query": query.group(1).strip(" .") if query else ""},
        })
    google = re.search(r"\bgoogle\b", low) and re.search(r"\bsearch\b", low)
    if google and "youtube" not in low:
        query = re.search(r"\b(?:search(?:\s+for)?|google(?:\s+and\s+search(?:\s+for)?)?)\s+(.+)$", text, re.I)
        steps.append({
            "device": "laptop",
            "tool": "google_search",
            "args": {"query": query.group(1).strip(" .") if query else ""},
        })
    return steps[:6]


def _obvious_steps(text: str, steps: list) -> list:
    """If the utterance names mail or Spotify and the plan missed it, add that step."""
    import re

    low = text.lower()
    have = {step.get("tool") for step in steps}
    added = list(steps)
    wants_mail = bool(re.search(r"\b(e-?mail|gmail|write\s+an?\s+mail|write\s+an?\s+email)\b", low)) or bool(
        re.search(r"\bmail\b", low)
    )
    if wants_mail and "mail_compose" not in have and "mail_send" not in have:
        addressed = re.search(r"\bto\s+(.+?)\s+about\s+(.+)$", text, re.I)
        about = re.search(r"\babout\s+(.+)$", text, re.I)
        who = addressed.group(1).strip() if addressed else ""
        topic = (addressed.group(2) if addressed else about.group(1) if about else "Hello").strip(" .")
        added.append({
            "device": "laptop",
            "tool": "mail_compose",
            "args": {
                "to": who,
                "subject": topic[:1].upper() + topic[1:] if topic else "Hello",
                "body": f"Hi {who or 'there'}, about {topic}." if topic else "Hi.",
            },
        })
    wants_music = "youtube" not in low and (
        "spotify" in low or bool(re.search(r"\bplay\b", low) and re.search(r"\b(music|song|songs|spotify)\b", low))
    )
    if wants_music and "play_music" not in have:
        added.append({
            "device": "phone",
            "tool": "play_music",
            "args": {"query": _music_query(text)},
        })
    for step in added:
        if step.get("tool") == "play_music":
            args = dict(step.get("args") or {})
            current = str(args.get("query") or "").strip()
            if _generic_music(current):
                args["query"] = _music_query(text)
                step["args"] = args
    return added[:6]


def _coerce_steps(text: str, steps: list) -> list:
    """Map invented tool names onto the phone and laptop allowlist."""
    import re

    low = text.lower()
    coerced = []
    for step in steps:
        tool = step["tool"]
        args = step["args"]
        if tool in {"whatsapp_send", "whatsapp_prefill", "send_message", "send_message_to_friend"} or (
            "whatsapp" in low and tool not in LAPTOP_TOOLS and tool not in {"sms_send", "instagram_send"}
        ):
            explicit = bool(re.search(r"\bsend\b", low)) and not bool(re.search(r"\b(?:don't|do not)\s+send\b", low))
            tool = "whatsapp_send"
            args["contact"] = str(args.get("contact") or args.get("phone") or args.get("to") or "")
            args["send"] = bool(args.get("send")) or explicit
            if not args.get("text"):
                match = re.search(r"\bthat\s+(.+)$", text, re.I)
                args["text"] = match.group(1).strip(" .") if match else ""
        elif tool == "open_food_search" or (
            ("swiggy" in low or "zomato" in low) and tool in {"google_search", "web_search", "open_url"}
        ):
            tool = "open_food_search"
            args["app"] = "zomato" if "zomato" in low else str(args.get("app") or "swiggy")
            if not args.get("query") or "swiggy" in str(args.get("query")).lower() or "zomato" in str(args.get("query")).lower():
                match = re.search(r"\bfor\s+(.+)$", text, re.I)
                args["query"] = match.group(1).strip(" .") if match else str(args.get("query") or text)
        elif tool in {"tel_call", "phone_call", "call", "dial"}:
            tool = "dial"
            args["number"] = str(args.get("number") or args.get("to") or "")
        elif "youtube" in low and tool in {"play_music", "play_nth", "youtube_media", "play_video"}:
            tool = "youtube_search"
            if not args.get("query"):
                match = re.search(r"\b(?:youtube|for)\s+(.+)$", text, re.I)
                args["query"] = match.group(1).strip(" .") if match else str(args.get("query") or args.get("title") or "")
        elif tool == "sms_send" and re.search(r"\b(?:type|open)\b", low) and re.search(r"\bsend it\b", low) and not re.search(r"\b(?:sms|text|message)\b", low):
            continue
        elif "on my phone" in low and tool in {"play_nth", "youtube_media", "play_video"}:
            tool = "play_music"
            if not args.get("query"):
                match = re.search(r"\bplay\s+(.+?)(?:\s+on\s+(?:my\s+)?phone)?$", text, re.I)
                args["query"] = match.group(1).strip(" .") if match else str(args.get("title") or "the song")
        if tool not in PHONE_TOOLS and tool not in LAPTOP_TOOLS and tool not in SERVER_TOOLS and tool not in MIND_TOOLS:
            continue
        step["tool"] = tool
        if tool in SERVER_TOOLS or tool in MIND_TOOLS:
            step["device"] = "server"
        elif tool in PHONE_TOOLS:
            step["device"] = "phone"
        else:
            step["device"] = "laptop"
        coerced.append(step)
    return coerced


def score_step(transcript: str, step: dict) -> dict:
    scored = _post(LAYA_URL, {"transcript": transcript, "proposed_step": step}, timeout=180)
    print(
        "[marc-api] score",
        step.get("tool"),
        "choice", scored.get("intent"),
        "confidence", scored.get("confidence"),
        "needs_planner", scored.get("needs_planner"),
        "needs_confirm", scored.get("needs_confirm"),
        "is_multi_step", scored.get("is_multi_step"),
        "destructive", scored.get("destructive"),
        flush=True,
    )
    return scored


def laptop_call(path: str, payload: dict) -> dict:
    if not LAPTOP_URL:
        return {"ok": False, "message": "Laptop isn't connected.", "owned": False}
    headers = {}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = 0.6 if path == "/rule" else 8
    return _post(LAPTOP_URL + path, payload, timeout=timeout, headers=headers)


def _laptop_health() -> dict:
    if not LAPTOP_URL:
        return {"ok": False, "message": "Laptop isn't connected."}
    headers = {}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(LAPTOP_URL + "/health", headers=headers)
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
        if isinstance(data, dict):
            return {"ok": bool(data.get("ok")), "message": "Laptop is up." if data.get("ok") else "Laptop isn't connected."}
    except Exception:  # noqa: BLE001
        pass
    return {"ok": False, "message": "Laptop isn't connected."}


def _run(cmd: list[str], timeout: float = 12) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)


def _docker(args: list[str], timeout: float = 12) -> subprocess.CompletedProcess:
    done = _run(["docker", *args], timeout=timeout)
    if done.returncode == 0:
        return done
    return _run(["sudo", "-n", "docker", *args], timeout=timeout)


def _unit_name(raw: str) -> str:
    key = str(raw or "").strip().lower().replace("_", "-")
    key = key.replace("the ", "").replace("marc ", "marc-")
    return SERVER_UNITS.get(key, "")


def _container_name(raw: str) -> str:
    key = str(raw or "").strip().lower().replace("_", "-")
    return SERVER_CONTAINERS.get(key, "")


def _server_status_line() -> str:
    live = machine_status()
    cpu = float(live.get("cpu_pct") or 0)
    temp = float(live.get("temp_c") or 0)
    mem = live.get("mem") or {}
    used = int(mem.get("used") or 0)
    total = int(mem.get("total") or 1)
    flags = live.get("services") or {}
    parts = [
        f"CPU {cpu:.0f} percent",
        f"{temp:.0f} degrees" if temp else "",
        f"RAM {int(used / total * 100) if total else 0} percent",
    ]
    down = [name for name, on in (("API", flags.get("api")), ("Bridge", flags.get("bridge")), ("Model", flags.get("ollama"))) if not on]
    if down:
        parts.append("down: " + ", ".join(down))
    else:
        parts.append("API, Bridge, and Model are up.")
    return "Server " + ", ".join(p for p in parts if p)


def server_call(tool: str, args: dict) -> dict:
    """Bounded Linux-host tools. No shell, no deletes, no shutdown."""
    args = args or {}
    try:
        if tool == "server_shell":
            return _server_shell(str(args.get("cmd") or args.get("command") or ""))
        if tool == "server_status":
            return {"ok": True, "message": _server_status_line()}
        if tool == "service_status":
            unit = _unit_name(str(args.get("name") or ""))
            if not unit:
                return {"ok": False, "message": "I can check api, desk, bridge, or ollama."}
            done = _run(["systemctl", "is-active", unit], timeout=4)
            state = (done.stdout or done.stderr or "unknown").strip().splitlines()[0] if (done.stdout or done.stderr) else "unknown"
            return {"ok": state == "active", "message": f"{unit} is {state}."}
        if tool == "service_restart":
            unit = _unit_name(str(args.get("name") or ""))
            if not unit:
                return {"ok": False, "message": "I can restart api, desk, bridge, or ollama."}
            def _restart() -> None:
                _run(["sudo", "-n", "systemctl", "restart", unit], timeout=20)
            if unit == "marc-api":
                threading.Thread(target=_restart, daemon=True).start()
                return {"ok": True, "message": f"Restarting {unit}."}
            done = _run(["sudo", "-n", "systemctl", "restart", unit], timeout=20)
            if done.returncode != 0:
                err = (done.stderr or done.stdout or "failed").strip()[:180]
                return {"ok": False, "message": f"Couldn't restart {unit}. {err}"}
            state = _run(["systemctl", "is-active", unit], timeout=4)
            live = (state.stdout or "").strip()
            return {"ok": live == "active", "message": f"Restarted {unit}." if live == "active" else f"{unit} is {live or 'unknown'}."}
        if tool == "docker_list":
            done = _docker(["ps", "--format", "{{.Names}} {{.Status}}"], timeout=8)
            if done.returncode != 0:
                err = (done.stderr or done.stdout or "docker failed").strip()[:180]
                return {"ok": False, "message": f"Couldn't list containers. {err}"}
            lines = [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]
            if not lines:
                return {"ok": True, "message": "No containers are running."}
            return {"ok": True, "message": "Containers: " + "; ".join(lines[:8])}
        if tool == "docker_restart":
            name = _container_name(str(args.get("name") or "n8n"))
            if not name:
                return {"ok": False, "message": "I can restart n8n."}
            done = _docker(["restart", name], timeout=30)
            if done.returncode != 0:
                err = (done.stderr or done.stdout or "failed").strip()[:180]
                return {"ok": False, "message": f"Couldn't restart {name}. {err}"}
            return {"ok": True, "message": f"Restarted {name}."}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "message": f"Server tool failed. {exc}"}
    return {"ok": False, "message": f"I don't have {tool} on the server."}


def _server_shell(cmd: str) -> dict:
    import re

    cmd = (cmd or "").strip()
    if not cmd:
        return {"ok": False, "message": "No command."}
    if re.search(SHELL_DENY_RE, cmd, re.I):
        return {"ok": False, "message": "I won't run that."}
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/home/rox",
        "USER": "rox",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    try:
        done = subprocess.run(
            ["bash", "-lc", cmd],
            cwd="/home/rox/marc",
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Command timed out."}
    except OSError as exc:
        return {"ok": False, "message": str(exc)[:180]}
    out = ((done.stdout or "") + ("\n" + done.stderr if done.stderr else "")).strip()
    out = (out[:1500] if out else "(no output)")
    return {"ok": done.returncode == 0, "message": out}


def mind_call(tool: str, args: dict) -> dict:
    args = args or {}
    try:
        mind_store.seed()
        if tool == "mind_now":
            return {"ok": True, "message": mind_store.now_speak()}
        if tool == "mind_note":
            return {"ok": True, "message": mind_store.write_note(str(args.get("title") or ""), str(args.get("body") or ""))}
        if tool == "mind_recall":
            return {"ok": True, "message": mind_store.recall(str(args.get("query") or args.get("q") or ""))}
        if tool == "brain_recall":
            return {"ok": True, "message": cognee_bridge.brain_speak(str(args.get("query") or args.get("q") or ""))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)[:180]}
    return {"ok": False, "message": "Unknown mind tool."}


def exec_step(step: dict) -> dict:
    """Run one tool on the server, laptop, or phone queue."""
    tool = str(step.get("tool") or "")
    args = dict(step.get("args") or {})
    if tool in MIND_TOOLS:
        result = mind_call(tool, args)
        return {
            "ok": bool(result.get("ok")),
            "message": result.get("message") or "",
            "device": "server",
            "phone_step": None,
        }
    device = str(step.get("device") or "").strip().lower()
    if tool == "server_shell" or tool in SERVER_TOOLS or device == "server":
        result = server_call(tool, args)
        return {
            "ok": bool(result.get("ok")),
            "message": result.get("message") or "",
            "device": "server",
            "phone_step": None,
        }
    if device == "laptop":
        try:
            result = laptop_call("/tool", {"tool": tool, "args": args, "confirmed": True})
        except Exception:  # noqa: BLE001
            result = {"ok": False, "message": "Laptop isn't connected."}
        ok = bool(result.get("ok"))
        return {
            "ok": ok,
            "message": result.get("message") or ("Laptop isn't connected." if not ok else ""),
            "device": "laptop",
            "phone_step": None,
        }
    if device == "phone" or tool in PHONE_TOOLS:
        queued = {**step, "device": "phone", "tool": tool, "args": args}
        return {
            "ok": True,
            "message": "Queued for the phone.",
            "device": "phone",
            "phone_step": queued,
        }
    try:
        result = laptop_call("/tool", {"tool": tool, "args": args, "confirmed": True})
    except Exception:  # noqa: BLE001
        result = {"ok": False, "message": "Laptop isn't connected."}
    ok = bool(result.get("ok"))
    return {
        "ok": ok,
        "message": result.get("message") or ("Laptop isn't connected." if not ok else ""),
        "device": "laptop",
        "phone_step": None,
    }


def _summary(step: dict) -> str:
    tool = step.get("tool")
    args = step.get("args") or {}
    if tool in ("mail_compose", "mail_send"):
        sender = f" from {MARC_EMAIL}" if MARC_EMAIL else ""
        return f"Send email{sender} to {args.get('to') or 'unknown'}: {args.get('subject') or ''}".strip()
    if tool in ("whatsapp_prefill", "whatsapp_send"):
        return f"WhatsApp {args.get('phone') or args.get('to') or ''}: {args.get('text') or ''}".strip()
    if tool == "dial":
        return f"Call {args.get('number') or ''}".strip()
    if tool == "open_food_search":
        return f"Open {args.get('app') or 'food app'} search for {args.get('query') or ''}".strip()
    return f"{step.get('device')} {tool}"


def gate_steps(transcript: str, plan: dict, allow_retry: bool) -> dict:
    spoken = plan.get("reply") or ""
    accepted_laptop = []
    accepted_server = []
    phone_steps = []
    for step in plan.get("steps") or []:
        scored = _local_score(step)
        step = {**step, "score": scored}
        tool = step.get("tool") or ""
        device = str(step.get("device") or "").strip().lower()
        if MARC_EMAIL and tool in ("mail_compose", "mail_send"):
            args = dict(step.get("args") or {})
            args["from"] = MARC_EMAIL
            step = {**step, "args": args}
        # Explicit device wins for dual tools like open_app (phone + laptop).
        if device == "server" or tool in SERVER_TOOLS or tool in MIND_TOOLS:
            accepted_server.append(step)
        elif device == "laptop":
            accepted_laptop.append(step)
        elif device == "phone" or tool in PHONE_TOOLS:
            phone_steps.append(step)
        else:
            accepted_laptop.append(step)
    messages = []
    steps_run = []
    for step in accepted_server + accepted_laptop:
        result = exec_step(step)
        ok = bool(result.get("ok"))
        message = result.get("message") or ""
        messages.append(message)
        steps_run.append({
            "device": result.get("device") or step.get("device"),
            "tool": step.get("tool"),
            "ok": ok,
            "message": message,
        })
    if messages:
        spoken = " ".join(m for m in messages if m) or spoken
    for step in phone_steps:
        steps_run.append({
            "device": "phone",
            "tool": step.get("tool"),
            "ok": True,
            "message": "Queued for the phone.",
        })
    machines = []
    if accepted_server:
        machines.append("server")
    if accepted_laptop:
        machines.append("laptop")
    if phone_steps:
        machines.append("phone")
    result = {
        "spoken": spoken or "Done.",
        "confirm": None,
        "phone_steps": phone_steps,
        "machines": machines,
        "steps_run": steps_run,
        "planner": plan.get("planner") or PLANNER,
        "source": plan.get("source") or "",
    }
    _remember_run(result)
    return result


def _local_score(step: dict) -> dict:
    """Confirm list is local. A Laya forward on this Pi is about a minute, so known tools do not wait for it."""
    tool = step.get("tool") or ""
    return {
        "intent": tool or "chat",
        "confidence": 1.0,
        "needs_confirm": 0.0,
        "needs_planner": 0.0,
        "is_multi_step": 0.0,
        "destructive": 0.0,
    }


def _classify_laya(text: str) -> dict | None:
    """One forward pass of the fine-tuned checkpoint. It stays on this Pi."""
    try:
        started = time.perf_counter()
        scored = _post(LAYA_URL, {"transcript": text}, timeout=90)
        print(
            "[marc-api] laya",
            scored.get("intent"),
            "confidence", scored.get("confidence"),
            "ms", int((time.perf_counter() - started) * 1000),
            flush=True,
        )
        return scored
    except Exception as exc:  # noqa: BLE001
        print("[marc-api] laya skipped", exc, flush=True)
        return None


def _steps_from_laya(text: str, scored: dict) -> list | None:
    """Turn a high-confidence Laya label into the same tool step the laptop router would."""
    import re

    intent = str(scored.get("intent") or "")
    confidence = float(scored.get("confidence") or 0)
    if intent in {"clarify", "chat", "multi_step"} or confidence < 0.45:
        return None
    if float(scored.get("is_multi_step") or 0) >= 0.5 or float(scored.get("needs_planner") or 0) >= 0.65:
        return None
    if intent == "refuse" or float(scored.get("destructive") or 0) >= 0.6:
        return None

    def after(pattern: str) -> str:
        match = re.search(pattern, text, re.I)
        return match.group(1).strip(" .") if match else ""

    laptop = {
        "open_app": {"app": after(r"\b(?:open|launch|start)\s+(.+)$") or text},
        "close_app": {"app": after(r"\b(?:close|quit|exit|stop)\s+(.+)$") or text},
        "focus_window": {"app": after(r"\b(?:focus|switch to|show)\s+(.+)$") or text},
        "web_search": {"query": after(r"\b(?:search|google|look up)\s+(.+)$") or text},
        "youtube_search": {"query": after(r"\b(?:search|find|play)\s+(.+?)(?:\s+on\s+youtube)?$") or text},
        "youtube_home": {},
        "youtube_media": {"action": after(r"\b(play|pause|next|previous)\b") or "play"},
        "play_video": {"query": after(r"\bplay\s+(.+)$") or text},
        "type_text": {"text": after(r"\b(?:type|write|dictate)\s+(.+)$") or text},
        "hotkey": {"key": after(r"\b(?:press|hit)\s+(.+)$") or text},
        "system_status": {},
        "volume_media": {"action": "play"},
        "mail_search": {"query": after(r"\b(?:search|find)\s+(.+)$") or text},
        "mail_summarize": {},
        "calendar_list": {},
        "drive_search": {"query": after(r"\b(?:search|find)\s+(.+)$") or text},
        "google_search": {"query": after(r"\b(?:search|google)\s+(.+)$") or text},
        "open_url": {"url": after(r"\b(?:open|go to)\s+(.+)$") or text},
    }
    if intent == "mail_compose":
        who = after(r"\b(?:email|mail)\s+(.+?)\s+about\b")
        topic = after(r"\babout\s+(.+)$") or "Hello"
        return [{
            "device": "laptop",
            "tool": "mail_compose",
            "args": {"to": who, "subject": topic[:1].upper() + topic[1:], "body": f"Hi {who or 'there'}, about {topic}."},
        }]
    if intent == "whatsapp_send":
        return [{
            "device": "phone",
            "tool": "whatsapp_prefill",
            "args": {
                "phone": after(r"\bwhatsapp\s+(.+?)\s+that\b"),
                "text": after(r"\bthat\s+(.+)$"),
            },
        }]
    if intent == "volume_media" and re.search(r"\b(music|song|spotify)\b", text, re.I):
        return [{"device": "phone", "tool": "play_music", "args": {"query": _music_query(text)}}]
    if intent not in laptop and intent not in LAPTOP_TOOLS:
        return None
    tool = "google_search" if intent == "web_search" else "youtube_search" if intent == "play_video" else intent
    if tool not in LAPTOP_TOOLS and tool not in PHONE_TOOLS:
        return None
    return [{"device": "phone" if tool in PHONE_TOOLS else "laptop", "tool": tool, "args": laptop.get(intent, {})}]


def _multi_phrase(text: str) -> bool:
    """True when the utterance chains more than one action/clause."""
    raw = text or ""
    if re.search(
        r"\b(?:and(?:\s+then)?|then|also|after\s+that|plus|first|next|afterwards)\b|,|;",
        raw,
        re.I,
    ):
        return True
    # Two device targets in one breath → continuous multi-device plan.
    devices = re.findall(
        r"\bon\s+(?:my\s+|the\s+)?(?:phone|mobile|laptop|computer|pc|server|linux)\b",
        raw,
        re.I,
    )
    return len(devices) >= 2


def _rag_context(text: str, session: str = "") -> str:
    """Pull Cognee + mind vault snippets into Hermes planning context."""
    bits: list[str] = []
    try:
        mind_store.seed()
        now = str(mind_store.now_speak() or "").strip()
        if now and "nothing" not in now.lower():
            bits.append(now[:220])
        recalled = str(mind_store.recall(text) or "").strip()
        if recalled and "couldn't" not in recalled.lower() and "nothing" not in recalled.lower():
            bits.append(recalled[:220])
    except Exception as exc:  # noqa: BLE001
        print("[marc-api] mind rag skip", exc, flush=True)
    try:
        brain = cognee_bridge.recall(text, datasets=["personal", "actions"], top_k=6)
        hits = brain.get("hits") if isinstance(brain, dict) else None
        if isinstance(hits, list) and hits:
            for hit in hits[:4]:
                line = str((hit or {}).get("text") or "").strip()
                if line:
                    bits.append(line[:180])
        else:
            spoken = str((brain or {}).get("text") or "").strip()
            if spoken and "nothing in the brain" not in spoken.lower():
                bits.append(spoken[:220])
    except Exception as exc:  # noqa: BLE001
        print("[marc-api] cognee rag skip", exc, flush=True)
    # Dedupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for bit in bits:
        key = bit.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(bit)
    return " · ".join(out[:5])


def _plan_context(text: str, session: str) -> str:
    base = _context_line(session)
    rag = _rag_context(text, session)
    if rag:
        return f"{base}\nBrain: {rag}"
    return base


def _split_clauses(text: str) -> list[str]:
    parts = re.split(
        r"\s*(?:,\s*|\s+and(?:\s+then)?\s+|\s+then\s+|\s+after\s+that\s+|\s+also\s+|\s*;\s*)\s*",
        text or "",
        flags=re.I,
    )
    clauses = [part.strip(" .") for part in parts if part and part.strip(" .")]
    return clauses


def _chain_steps_from_text(text: str, session: str = "", target: str = "auto") -> list[dict]:
    """Deterministic continuous-command expansion so Hermes can't drop later clauses."""
    steps: list[dict] = []
    default = _session_target(text, session, target)
    for clause in _split_clauses(text):
        low = clause.lower()
        device = _device_in_clause(clause, default)
        opened = re.search(r"\b(?:open|launch|start)\s+(.+)$", clause, re.I)
        closed = re.search(r"\b(?:close|quit|exit)\s+(.+)$", clause, re.I)
        if opened or closed:
            name = (opened or closed).group(1)
            name = re.sub(
                r"\s+on\s+(?:my\s+|the\s+)?(?:phone|mobile|laptop|computer|pc|server|linux)$",
                "",
                name,
                flags=re.I,
            ).strip(" .")
            if not name:
                continue
            tool = "open_app" if opened else "close_app"
            args = {"name": name} if device == "phone" else {"app": name}
            steps.append({"device": device, "tool": tool, "args": args})
            continue
        typed = re.search(r"\b(?:type|write|dictate|text|message)\s+(.+)$", clause, re.I)
        if typed:
            payload = typed.group(1).strip(" .")
            payload = re.sub(
                r"\s+on\s+(?:my\s+|the\s+)?(?:phone|mobile|laptop|computer|pc)$",
                "",
                payload,
                flags=re.I,
            ).strip(" .")
            # Strip leftover cue words from the typed body.
            payload = re.sub(r"^(?:that\s+|saying\s+)", "", payload, flags=re.I).strip(" .")
            draft = bool(re.search(r"\b(?:don'?t|do not|dont)\s+send\b|\bdraft\b", low, re.I))
            send = (not draft) and bool(re.search(r"\bsend\b", low))
            text_low = (text or "").lower()
            opened_wa = any(
                row.get("tool") == "open_app"
                and "whatsapp" in str((row.get("args") or {}).get("name") or (row.get("args") or {}).get("app") or "").lower()
                for row in steps
            )
            # Messaging clauses must open the contact chat — never type name+body into WhatsApp search.
            if ("whatsapp" in text_low or opened_wa) and re.search(r"\b(?:text|message)\b", low):
                contact, body = _contact_and_body(clause if "text" in low or "message" in low else text, session)
                if not contact:
                    contact, body = _contact_and_body(text, session)
                if not body and payload:
                    # Fallback: first name token + remainder.
                    words = payload.split()
                    contact = contact or (words[0] if words else "")
                    body = body or (" ".join(words[1:]) if len(words) > 1 else "")
                if contact:
                    steps.append({
                        "device": "phone",
                        "tool": "whatsapp_send",
                        "args": {"contact": contact, "text": body, "send": bool(send)},
                    })
                    continue
            # Prefer laptop typing when the utterance/target is laptop — never bounce to phone.
            use_laptop = (
                device == "laptop"
                or default == "laptop"
                or _laptop_named(text)
                or target == "laptop"
            ) and not _phone_named(clause)
            if use_laptop:
                steps.append({"device": "laptop", "tool": "type_text", "args": {"text": payload}})
                if send:
                    steps.append({"device": "laptop", "tool": "hotkey", "args": {"action": "enter"}})
            else:
                steps.append({
                    "device": "phone",
                    "tool": "type_into",
                    "args": {"text": payload, "send": bool(send)},
                })
            continue
        if re.search(r"\b(?:list\s+)?(?:docker|containers)\b", low):
            steps.append({"device": "server", "tool": "docker_list", "args": {}})
            continue
        if (
            re.search(r"\b(?:status|health|how hot|temperature|temp|load|cpu|check)\b", low)
            or _server_named(clause)
            or re.search(r"\b(?:check|status)\s+(?:the\s+)?server\b", low)
        ):
            if device == "server" or _server_named(clause) or re.search(r"\bserver\b", low):
                steps.append({"device": "server", "tool": "server_status", "args": {}})
                continue
        restart = re.search(
            r"\brestart\s+(?:the\s+)?(ollama|model|qwen|n8n|desk|site|web|api|bridge|marc-api|marc-desk|marc-bridge)\b",
            clause,
            re.I,
        )
        if restart:
            name = restart.group(1).lower()
            if name == "n8n":
                steps.append({"device": "server", "tool": "docker_restart", "args": {"name": "n8n"}})
            else:
                steps.append({"device": "server", "tool": "service_restart", "args": {"name": name}})
    return steps


def _hermes_rag_plan(text: str, session: str, target: str = "auto") -> dict:
    """Hermes plans every actionable utterance with Cognee/mind RAG context."""
    context = _plan_context(text, session)
    print(
        "[marc-api] hermes-rag",
        "multi" if _multi_phrase(text) else "single",
        "brain" if "Brain:" in context else "no-brain",
        flush=True,
    )
    planned = plan_command(text, context=context, session=session)
    if not isinstance(planned, dict):
        planned = {"reply": "On it.", "steps": []}
    steps = list(planned.get("steps") or [])
    chain = _chain_steps_from_text(text, session, target)
    messaging_tools = {"whatsapp_send", "whatsapp_prefill", "sms_send", "instagram_send"}
    muse_messaging = any(
        isinstance(s, dict) and str(s.get("tool") or "") in messaging_tools for s in steps
    )
    if _multi_phrase(text):
        hermes_wrong_device = bool(steps) and (
            target == "laptop" or _laptop_named(text)
        ) and not _phone_named(text) and any(
            isinstance(s, dict) and str(s.get("device") or "") == "phone"
            for s in steps
        )
        # Muse owns messaging decomposition — never replace whatsapp/sms/instagram with chain type_into.
        if muse_messaging:
            print("[marc-api] hermes-rag keep-muse-messaging", [s.get("tool") for s in steps if isinstance(s, dict)], flush=True)
        elif chain and (len(chain) > len(steps) or hermes_wrong_device):
            print("[marc-api] hermes-rag fill", [step.get("tool") for step in chain], flush=True)
            planned = {
                **planned,
                "reply": planned.get("reply") or _brief_reply(chain, ""),
                "steps": chain,
                "source": "chain" if hermes_wrong_device else (planned.get("source") or "hermes"),
            }
        elif not steps:
            heuristic = _heuristic_plan(text, session)
            if heuristic and (heuristic.get("steps") or []):
                planned = {**heuristic, "source": "heuristic"}
            elif chain:
                planned = {"reply": _brief_reply(chain, ""), "steps": chain, "source": "chain"}
    elif not steps and chain:
        planned = {"reply": _brief_reply(chain, ""), "steps": chain, "source": "chain"}
    return _finish_plan(text, session, planned, target)


PHONE_STATE: dict[str, dict] = {}
APP_PACKAGES = {
    "spotify": "com.spotify.music",
    "whatsapp": "com.whatsapp",
    "instagram": "com.instagram.android",
    "insta": "com.instagram.android",
    "github": "com.github.android",
    "tailscale": "com.tailscale.ipn",
    "messages": "com.google.android.apps.messaging",
}


def _laptop_named(text: str) -> bool:
    import re

    return bool(re.search(r"\bon\s+(?:my\s+|the\s+)?(?:laptop|computer|pc)\b", text, re.I))


def _server_named(text: str) -> bool:
    import re

    return bool(re.search(r"\bon\s+(?:my\s+|the\s+)?(?:server|linux|home\s+server)\b", text, re.I))


def _requested_target(body: dict | None) -> str:
    value = str((body or {}).get("target") or "auto").strip().lower()
    return value if value in {"phone", "laptop", "server", "auto"} else "auto"


def _session_target(text: str, session: str, requested: str = "auto") -> str:
    if _laptop_named(text):
        return "laptop"
    if _phone_named(text):
        return "phone"
    if _server_named(text):
        return "server"
    if requested in {"phone", "laptop", "server"}:
        return requested
    return "phone" if session == "phone" else "laptop"


def _activity_event(run: dict, event_type: str, text: str = "", device: str = "", message: str = "") -> None:
    events = run.setdefault("events", [])
    events.append({
        "at": int(time.time() * 1000),
        "type": event_type,
        "text": text or "",
        "device": device or "",
        "message": message or "",
    })


def _activity_start(text: str, session: str) -> dict:
    run = {
        "id": secrets.token_hex(4),
        "at": int(time.time() * 1000),
        "session_id": session or "phone",
        "text": text or "",
        "phase": "heard",
        "planner": PLANNER,
        "source": "",
        "spoken": "",
        "steps": [],
        "events": [],
    }
    _activity_event(run, "heard", text or "")
    with _ACTIVITY_LOCK:
        _ACTIVITY_RUNS.insert(0, run)
        del _ACTIVITY_RUNS[_ACTIVITY_MAX:]
    return run


def _activity_attach(result: dict, run: dict | None) -> dict:
    if not isinstance(result, dict):
        return result
    if run is None:
        return result
    run["spoken"] = result.get("spoken") or ""
    run["source"] = result.get("source") or run.get("source") or ""
    run["planner"] = result.get("planner") or PLANNER
    run["phase"] = "done"
    steps = []
    for item in result.get("steps_run") or []:
        if not isinstance(item, dict):
            continue
        ok = bool(item.get("ok", True))
        row = {
            "device": item.get("device") or "",
            "tool": item.get("tool") or "",
            "status": "ok" if ok else "fail",
            "message": item.get("message") or "",
        }
        steps.append(row)
        _activity_event(
            run,
            "step_ok" if ok else "step_fail",
            row["tool"],
            row["device"],
            row["message"],
        )
    if not steps:
        for step in result.get("phone_steps") or []:
            if not isinstance(step, dict):
                continue
            row = {
                "device": "phone",
                "tool": step.get("tool") or "",
                "status": "queued",
                "message": "",
            }
            steps.append(row)
            _activity_event(run, "step_start", row["tool"], "phone", "")
    run["steps"] = steps
    _activity_event(run, "spoken", run["spoken"])
    _activity_event(run, "done")
    result = {
        **result,
        "run_id": run["id"],
        "planner": run["planner"],
        "source": run.get("source") or result.get("source") or "",
    }
    _remember_run(result)
    return result


def activity_snapshot(session_id: str = "", since_ms: int = 0) -> dict:
    with _ACTIVITY_LOCK:
        rows = list(_ACTIVITY_RUNS)
    if session_id:
        rows = [row for row in rows if not row.get("session_id") or row.get("session_id") == session_id]
    if since_ms > 0:
        rows = [row for row in rows if int(row.get("at") or 0) >= since_ms]
    current = rows[0] if rows and rows[0].get("phase") not in {"done", "fail"} else None
    return {"ok": True, "runs": rows[:30], "current": current, "agent": dict(_LAST_RUN)}


def _remember_run(result: dict) -> None:
    global _LAST_RUN
    _LAST_RUN = {
        "spoken": result.get("spoken") or "",
        "machines": list(result.get("machines") or []),
        "steps_run": list(result.get("steps_run") or []),
        "planner": result.get("planner") or PLANNER,
        "source": result.get("source") or "",
        "run_id": result.get("run_id") or "",
        "at": int(time.time() * 1000),
    }
    _memory_save()


def _state(session: str) -> dict:
    return PHONE_STATE.setdefault(session or "phone", {
        "apps": [],
        "front": "",
        "media": "",
        "contact": "",
        "channel": "",
        "last_utterance": "",
    })


def _office_blank() -> dict:
    return {
        "agent_id": "",
        "cwd": "/home/rox/office/work",
        "remote": "",
        "last_summary": "",
    }


def _office_clean(raw) -> dict:
    data = _office_blank()
    if not isinstance(raw, dict):
        return data
    data["agent_id"] = str(raw.get("agent_id") or "")[:160]
    data["cwd"] = str(raw.get("cwd") or data["cwd"])[:400]
    data["remote"] = str(raw.get("remote") or "")[:400]
    data["last_summary"] = str(raw.get("last_summary") or "")[:800]
    return data


def _memory_blank() -> dict:
    return {
        "profile": {"name": "Ranjith", "notes": []},
        "sessions": {},
        "apps": [],
        "front": "",
        "office": _office_blank(),
    }


def _memory_load() -> dict:
    global _MEMORY
    if _MEMORY:
        return _MEMORY
    data = _memory_blank()
    try:
        with open(MEMORY_PATH, encoding="utf-8") as handle:
            loaded = json.loads(handle.read())
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        loaded = {}
    if isinstance(loaded, dict):
        profile = loaded.get("profile") if isinstance(loaded.get("profile"), dict) else {}
        data["profile"]["name"] = str(profile.get("name") or "Ranjith")[:80]
        raw_notes = profile.get("notes") if isinstance(profile.get("notes"), list) else []
        data["profile"]["notes"] = [str(note).strip()[:400] for note in raw_notes if str(note).strip()][:12]
        sessions = loaded.get("sessions") if isinstance(loaded.get("sessions"), dict) else {}
        for sid, lines in sessions.items():
            if not isinstance(lines, list):
                continue
            cleaned = []
            for line in lines[-8:]:
                if isinstance(line, dict) and line.get("role") in {"user", "assistant"}:
                    cleaned.append({"role": line["role"], "content": str(line.get("content") or "")[:400]})
            data["sessions"][str(sid)] = cleaned
            _CHAT.setdefault(str(sid), list(cleaned))
        apps = loaded.get("apps") if isinstance(loaded.get("apps"), list) else []
        data["apps"] = [app for app in apps if isinstance(app, dict)][:4]
        data["front"] = str(loaded.get("front") or "")
        data["office"] = _office_clean(loaded.get("office"))
    _MEMORY = data
    if data["apps"]:
        phone = _state("phone")
        if not phone["apps"]:
            phone["apps"] = list(data["apps"])
            phone["front"] = data.get("front") or (phone["apps"][-1].get("name") if phone["apps"] else "")
    return _MEMORY


def _memory_save() -> None:
    data = _memory_load()
    with _memory_lock:
        data["sessions"] = {sid: list(lines)[-8:] for sid, lines in _CHAT.items()}
        phone = _state("phone")
        if phone.get("apps"):
            data["apps"] = list(phone["apps"])[:4]
            data["front"] = phone.get("front") or data.get("front") or ""
        path = MEMORY_PATH
        tmp = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            disk = {}
            try:
                with open(path, encoding="utf-8") as handle:
                    loaded = json.loads(handle.read())
                if isinstance(loaded, dict):
                    disk = loaded
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                disk = {}
            ours = _office_clean(data.get("office"))
            theirs = _office_clean(disk.get("office"))
            merged = dict(theirs)
            merged.update({key: value for key, value in ours.items() if value})
            data["office"] = merged
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            return


def _memory_notes() -> list:
    notes = mind_store.person_notes()
    if notes:
        return notes
    stored = _memory_load()["profile"].get("notes") or []
    return [str(note) for note in stored if str(note).strip()]


def _memory_add_note(note: str) -> str:
    spoken = mind_store.remember(note)
    data = _memory_load()
    notes = mind_store.person_notes()
    data["profile"]["notes"] = notes[-12:]
    _memory_save()
    return spoken


def _memory_forget(needle: str) -> str:
    spoken = mind_store.forget(needle)
    data = _memory_load()
    data["profile"]["notes"] = mind_store.person_notes()[-12:]
    _memory_save()
    return spoken


def _memory_speak() -> str:
    spoken = mind_store.speak_who()
    if spoken:
        return spoken
    data = _memory_load()
    name = data["profile"].get("name") or "Ranjith"
    notes = _memory_notes()
    if not notes:
        return f"You're {name}. I don't have extra notes yet."
    return f"You're {name}. " + " ".join(notes[:6])


def _mind_record(text: str, session: str, result: dict) -> dict:
    if not isinstance(result, dict):
        return result
    try:
        mind_store.seed()
        spoken = str(result.get("spoken") or "")
        tools = [
            step.get("tool")
            for step in (result.get("steps_run") or [])
            if isinstance(step, dict) and step.get("tool")
        ]
        sid = session or "desk"
        mind_store.chat_append(sid, "user", text)
        mind_store.chat_append(sid, "assistant", spoken)
        mind_store.after_turn(text, spoken, sid, tools)
        snippet = f"User ({sid}): {str(text)[:300]}\nMarc: {spoken[:300]}"
        if str(text).strip() or spoken.strip():
            cognee_bridge.remember_async(snippet, dataset="personal")
        run_steps = [
            step for step in (result.get("steps_run") or [])
            if isinstance(step, dict) and step.get("tool")
        ]
        if run_steps:
            trail = ", ".join(
                f"{step.get('device') or '?'}:{step.get('tool')}"
                + ("" if step.get("ok", True) else "!fail")
                for step in run_steps[:8]
            )
            cognee_bridge.remember_async(
                f"Action ({sid}): {str(text)[:200]} → {trail} → {spoken[:200]}",
                dataset="actions",
            )
        history = _CHAT.setdefault(sid, [])
        if text:
            history.append({"role": "user", "content": str(text)[:400]})
        if spoken:
            history.append({"role": "assistant", "content": spoken[:400]})
        del history[:-8]
        _memory_save()
    except Exception as exc:  # noqa: BLE001
        print("[marc-api] mind skip", exc, flush=True)
    return result


def handle_mind_get(query: dict | None = None) -> dict:
    query = query or {}
    rel = ""
    raw = query.get("path")
    if isinstance(raw, list) and raw:
        rel = str(raw[0] or "")
    elif raw:
        rel = str(raw)
    if rel:
        return mind_store.read_note(rel)
    return mind_store.snapshot()


def handle_mind_post(data: dict | None) -> dict:
    data = data if isinstance(data, dict) else {}
    action = str(data.get("action") or "").strip().lower()
    try:
        mind_store.seed()
        if action == "focus":
            spoken = mind_store.set_focus(str(data.get("text") or data.get("focus") or ""))
            return {"ok": True, "spoken": spoken, **mind_store.snapshot()}
        if action == "note":
            spoken = mind_store.write_note(str(data.get("title") or ""), str(data.get("body") or data.get("text") or ""))
            return {"ok": True, "spoken": spoken, **mind_store.snapshot()}
        if action == "search":
            spoken = mind_store.recall(str(data.get("query") or data.get("text") or ""))
            return {"ok": True, "spoken": spoken, **mind_store.snapshot()}
        return mind_store.snapshot()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:180]}


def _context_line(session: str) -> str:
    data = _memory_load()
    state = _state(session or "phone")
    apps = ", ".join(
        app.get("name") or ""
        for app in (state.get("apps") or data.get("apps") or [])
        if isinstance(app, dict)
    ) or "none"
    front = state.get("front") or data.get("front") or "nothing"
    media = state.get("media") or "idle"
    contact = state.get("contact") or "none"
    channel = state.get("channel") or "none"
    name = (data.get("profile") or {}).get("name") or "Ranjith"
    bits = [f"Owner is {name}."]
    notes = _memory_notes()
    if notes:
        bits.append("Notes: " + "; ".join(notes[-4:]))
    bits.append(f"Now: {front} is {media}. Apps: {apps}. Last contact: {contact} on {channel}.")
    recent = _CHAT.get(session or "desk") or []
    if recent:
        talk = " | ".join(
            f"{line.get('role')}: {str(line.get('content') or '')[:80]}"
            for line in recent[-2:]
        )
        bits.append("Recent: " + talk)
    return " ".join(bits)[:400]


def _pkg_for(name: str) -> str:
    return APP_PACKAGES.get((name or "").strip().lower(), "")


def _add_app(state: dict, name: str, package: str) -> None:
    clean = (name or "").strip()
    if not clean:
        return
    state["apps"] = [app for app in state["apps"] if app["name"].lower() != clean.lower()]
    state["apps"].append({"name": clean[:1].upper() + clean[1:], "package": package or _pkg_for(clean)})
    state["apps"] = state["apps"][-4:]
    state["front"] = state["apps"][-1]["name"]


def _remember(session: str, steps: list) -> list:
    state = _state(session)
    for step in steps:
        tool = step.get("tool") or ""
        args = step.get("args") or {}
        if tool == "play_music":
            _add_app(state, "Spotify", "com.spotify.music")
            state["media"] = "playing"
            state["channel"] = "spotify"
        elif tool == "media_key":
            if not state["front"]:
                _add_app(state, "Spotify", "com.spotify.music")
            action = str(args.get("action") or "")
            state["media"] = "paused" if action in {"pause", "stop"} else "playing"
            state["channel"] = "spotify"
        elif tool == "open_app":
            name = str(args.get("name") or args.get("app") or "")
            _add_app(state, name, _pkg_for(name))
        elif tool == "close_app":
            name = str(args.get("name") or state["front"] or "")
            state["apps"] = [app for app in state["apps"] if app["name"].lower() != name.lower()]
            if state["front"].lower() == name.lower():
                state["front"] = state["apps"][-1]["name"] if state["apps"] else ""
            if "spotify" in name.lower():
                state["media"] = ""
        elif tool in {"whatsapp_send", "whatsapp_prefill"}:
            _add_app(state, "WhatsApp", "com.whatsapp")
            state["contact"] = str(args.get("contact") or args.get("phone") or state["contact"])
            state["channel"] = "whatsapp"
        elif tool == "sms_send":
            _add_app(state, "Messages", "com.google.android.apps.messaging")
            state["contact"] = str(args.get("contact") or state["contact"])
            state["channel"] = "sms"
        elif tool == "instagram_send":
            _add_app(state, "Instagram", "com.instagram.android")
            state["contact"] = str(args.get("contact") or state["contact"])
            state["channel"] = "instagram"
        elif tool == "ui_tap" and "tailscale" in str(args.get("package") or ""):
            _add_app(state, "Tailscale", "com.tailscale.ipn")
    return list(state["apps"])


def _log_miss(text: str, step: dict) -> None:
    try:
        with open("/home/rox/marc/qwen_misses.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"text": text, "step": {"tool": step.get("tool"), "device": step.get("device")}}) + "\n")
    except OSError:
        return


def _clause_for_token(text: str, token: str) -> str:
    """Find the clause that mentions token so per-clause device phrases win."""
    raw = text or ""
    parts = re.split(
        r"\s*(?:,\s*|\s+and(?:\s+then)?\s+|\s+then\s+|\s+after\s+that\s+|\s+also\s+|\s*;\s*)\s*",
        raw,
        flags=re.I,
    )
    parts = [part.strip(" .") for part in parts if part and part.strip(" .")]
    needle = (token or "").strip().lower()
    if needle:
        for part in parts:
            if needle in part.lower():
                return part
    return raw


def _device_in_clause(clause: str, default: str) -> str:
    if _laptop_named(clause):
        return "laptop"
    if _phone_named(clause):
        return "phone"
    if _server_named(clause) or re.search(r"\b(?:server|docker|containers?)\b", clause or "", re.I):
        return "server"
    return default


def _assign_devices(steps: list, text: str, session: str, target: str = "auto") -> list:
    """Per-clause device phrases win. Dual tools (open_app) keep Hermes device when sane."""
    low = text.lower()
    dest = _session_target(text, session, target)
    prefer_phone = dest == "phone"
    multi = _multi_phrase(text)
    routed = []
    for step in steps:
        args = dict(step.get("args") or {})
        tool = step.get("tool") or ""
        planned = str(step.get("device") or "").strip().lower()
        device = planned if planned in {"phone", "laptop", "server"} else ""
        if prefer_phone and not multi and tool in {"youtube_media", "volume_media", "play_video", "play_nth"}:
            action = str(args.get("action") or "play")
            if re.search(r"\bnext\b", low):
                action = "next"
            elif re.search(r"\b(?:previous|prev)\b", low):
                action = "previous"
            elif re.search(r"\bpause\b", low):
                action = "pause"
            elif re.search(r"\bstop\b", low):
                action = "stop"
            tool = "media_key"
            device = "phone"
            args = {"action": action}
        if prefer_phone and not multi and tool in {"youtube_search", "google_search", "web_search"}:
            query = str(args.get("query") or "").strip()
            app = "YouTube" if tool == "youtube_search" or "youtube" in low else "Google"
            already = any(
                row.get("tool") == "open_app"
                and app.lower() in str((row.get("args") or {}).get("name") or "").lower()
                for row in routed
            )
            if not already:
                routed.append({"device": "phone", "tool": "open_app", "args": {"name": app}})
            if query:
                routed.append({"device": "phone", "tool": "type_into", "args": {"text": query, "send": True}})
            continue
        if tool in {"open_app", "close_app"}:
            name = str(args.get("name") or args.get("app") or "").strip()
            name = re.sub(
                r"\s+on\s+(?:my\s+|the\s+)?(?:phone|mobile|laptop|computer|pc|server|linux)$",
                "",
                name,
                flags=re.I,
            ).strip(" .")
            clause = _clause_for_token(text, name)
            device = _device_in_clause(clause, device or dest)
            if device == "phone":
                args = {"name": name}
            else:
                args = {"app": name}
        elif tool in SERVER_TOOLS or tool in MIND_TOOLS:
            device = "server"
        elif tool in {"type_into", "type_text"}:
            # Keep typing on the named/target device. Muse often emits phone type_into for laptop.
            body = str(args.get("text") or "").strip()
            body = re.sub(r"^(?:type|write|dictate)\s+", "", body, flags=re.I).strip()
            # "Open WhatsApp and text Name …" must become whatsapp_send, not type_into into search.
            if (
                tool == "type_into"
                and "whatsapp" in low
                and re.search(r"\b(?:text|message)\b", low)
                and not (_laptop_named(text) or dest == "laptop" or target == "laptop")
            ):
                contact, msg = _contact_and_body(text, session)
                if not contact and body:
                    words = body.split()
                    contact = words[0] if words else ""
                    msg = " ".join(words[1:]) if len(words) > 1 else ""
                if contact:
                    tool = "whatsapp_send"
                    device = "phone"
                    send = bool(args.get("send")) and not re.search(
                        r"\b(?:don'?t|do not|dont)\s+send\b", text, re.I
                    )
                    args = {"contact": contact, "text": msg, "send": send}
                    routed.append({**step, "device": device, "tool": tool, "args": args})
                    continue
            clause = _clause_for_token(text, body.split(" ", 1)[0] if body else "type")
            if _laptop_named(text) or dest == "laptop" or target == "laptop":
                if not _phone_named(clause):
                    device = "laptop"
                    tool = "type_text"
                    args = {"text": body}
            elif _phone_named(clause) or dest == "phone":
                device = "phone"
                tool = "type_into"
                send = bool(args.get("send")) and not re.search(
                    r"\b(?:don'?t|do not|dont)\s+send\b", text, re.I
                )
                args = {"text": body, "send": send}
            else:
                device = device or dest or ("phone" if prefer_phone else "laptop")
                if device == "laptop":
                    tool = "type_text"
                    args = {"text": body}
                else:
                    tool = "type_into"
                    args = {"text": body, "send": bool(args.get("send"))}
        elif tool in {"whatsapp_send", "whatsapp_prefill", "sms_send", "instagram_send"}:
            # Stay on the device the user named for the chat app — don't bounce laptop→phone.
            contact = str(args.get("contact") or args.get("phone") or args.get("to") or "").strip()
            if contact:
                args["contact"] = contact
            clause = _clause_for_token(text, contact or "whatsapp")
            if _laptop_named(text) and not _phone_named(clause):
                device = "laptop"
            elif _phone_named(clause) or _phone_named(text):
                device = "phone"
            elif dest == "laptop":
                device = "laptop"
            else:
                device = "phone"
            # Empty-slot fill only — never overwrite Muse's chosen contact.
            contact_fill, body_fill = _contact_and_body(text, session)
            if not contact and contact_fill:
                args["contact"] = contact_fill
            if not str(args.get("text") or "").strip() and body_fill:
                args["text"] = body_fill
            if "send" not in args:
                args["send"] = bool(re.search(r"\bsend\b", text, re.I)) and not re.search(
                    r"\b(?:don'?t|do not|dont)\s+send\b", text, re.I
                )
        elif tool in PHONE_TOOLS and tool not in LAPTOP_TOOLS:
            device = "phone"
        elif tool in LAPTOP_TOOLS and tool not in PHONE_TOOLS:
            device = "laptop"
        else:
            # Dual tools: honor Hermes device, else clause/default.
            if not device:
                device = dest if dest in {"phone", "laptop", "server"} else ("phone" if prefer_phone else "laptop")
            if multi:
                hint = _clause_for_token(text, str(args.get("name") or args.get("app") or args.get("query") or tool))
                device = _device_in_clause(hint, device)
        routed.append({**step, "device": device, "tool": tool, "args": args})
    return _expand_laptop_messaging(routed, text)


def _expand_laptop_messaging(steps: list, text: str) -> list:
    """Laptop has no whatsapp_send tool — turn it into open + type + enter."""
    out: list[dict] = []
    for step in steps:
        tool = step.get("tool") or ""
        device = step.get("device") or ""
        args = dict(step.get("args") or {})
        if device == "laptop" and tool in {"whatsapp_send", "whatsapp_prefill"}:
            contact = str(args.get("contact") or args.get("phone") or "").strip()
            body = str(args.get("text") or "").strip()
            app = "WhatsApp"
            already = any(
                row.get("device") == "laptop"
                and row.get("tool") == "open_app"
                and "whatsapp" in str((row.get("args") or {}).get("app") or "").lower()
                for row in out
            )
            if not already:
                out.append({"device": "laptop", "tool": "open_app", "args": {"app": app}})
            if contact:
                out.append({"device": "laptop", "tool": "type_text", "args": {"text": contact}})
                out.append({"device": "laptop", "tool": "hotkey", "args": {"action": "enter"}})
            if body:
                out.append({"device": "laptop", "tool": "type_text", "args": {"text": body}})
            continue
        out.append({**step, "args": args})
    return out


def _typed_body(raw: str) -> tuple[str, bool]:
    import re

    send = bool(re.search(r"\b(?:enter|send(?:\s+it)?)\b", raw, re.I))
    body = re.sub(
        r"\s+(?:and\s+)?(?:then\s+)?(?:hit |press )?(?:enter(?:\s+and)?\s*)?(?:send(?:\s+it)?)?$",
        "",
        raw.strip(" ."),
        flags=re.I,
    )
    body = re.sub(r"\s+enter$", "", body, flags=re.I).strip(" .")
    return body, send


def _scripted_plan(text: str, session: str = "", target: str = "auto") -> dict | None:
    """Open / type / search / send on the session device. Do not wait on Needle."""
    import re

    if not text.strip():
        return None
    dest = _session_target(text, session, target)
    phone = dest == "phone"
    low = text.lower()
    if re.search(r"\b(?:whatsapp|instagram|sms)\b", low):
        return None

    youtube = re.search(
        r"\b(?:search\s+(?:on\s+)?youtube\s+(?:for\s+)?|youtube\s+(?:search\s+)?(?:for\s+)?)(.+)$",
        text,
        re.I,
    ) or re.search(r"\b(?:search|play|find)\s+(.+?)\s+on\s+youtube\b", text, re.I)
    if youtube:
        query = youtube.group(1).strip(" .")
        query = re.sub(r"^(?:for|search\s+for)\s+", "", query, flags=re.I).strip(" .")
        if query:
            if phone:
                steps = [
                    {"device": "phone", "tool": "open_app", "args": {"name": "YouTube"}},
                    {"device": "phone", "tool": "type_into", "args": {"text": query, "send": True}},
                ]
            else:
                steps = [{"device": "laptop", "tool": "youtube_search", "args": {"query": query}}]
            print("[marc-api] scripted", [step.get("tool") for step in steps], flush=True)
            return {"reply": _brief_reply(steps, ""), "steps": steps}

    google = re.search(
        r"\b(?:open\s+)?google\s+and\s+search(?:\s+for)?\s+(.+)$",
        text,
        re.I,
    ) or re.search(r"\bsearch(?:\s+on)?\s+google\s+(?:for\s+)?(.+)$", text, re.I)
    if google:
        query = google.group(1).strip(" .")
        if query:
            if phone:
                steps = [
                    {"device": "phone", "tool": "open_app", "args": {"name": "Google"}},
                    {"device": "phone", "tool": "type_into", "args": {"text": query, "send": True}},
                ]
            else:
                steps = [{"device": "laptop", "tool": "google_search", "args": {"query": query}}]
            print("[marc-api] scripted", [step.get("tool") for step in steps], flush=True)
            return {"reply": _brief_reply(steps, ""), "steps": steps}

    typed = re.search(
        r"\b(?:open|launch|start)\s+(.+?)\s+(?:and\s+)?(?:then\s+)?(?:type|enter|write)\s+(?:in\s+)?(.+)$",
        text,
        re.I,
    )
    if typed:
        app = typed.group(1).strip(" .")
        body, send = _typed_body(typed.group(2))
        if app and body:
            if phone:
                steps = [
                    {"device": "phone", "tool": "open_app", "args": {"name": app}},
                    {"device": "phone", "tool": "type_into", "args": {"text": body, "send": send}},
                ]
            else:
                steps = [
                    {"device": "laptop", "tool": "open_app", "args": {"app": app}},
                    {"device": "laptop", "tool": "type_text", "args": {"text": body}},
                ]
                if send:
                    steps.append({"device": "laptop", "tool": "hotkey", "args": {"key": "enter"}})
            print("[marc-api] scripted", [step.get("tool") for step in steps], flush=True)
            return {"reply": _brief_reply(steps, ""), "steps": steps}
    return None


def _open_sequence(text: str) -> list:
    """When a phrase names several apps, keep those opens in spoken order."""
    import re

    steps = []
    for part in re.split(r"\b(?:and|then|also)\b", text, flags=re.I):
        part = part.strip(" .,")
        opened = re.search(r"\b(?:open|launch|start)\s+(.+)$", part, re.I)
        closed = re.search(r"\b(?:close|quit|exit)\s+(.+)$", part, re.I)
        if opened:
            steps.append({"device": "phone", "tool": "open_app", "args": {"name": opened.group(1).strip(" .")}})
        elif closed:
            steps.append({"device": "phone", "tool": "close_app", "args": {"name": closed.group(1).strip(" .")}})
    return steps[:6]


def _ensure_type_target(steps: list) -> list:
    """After laptop open_app, force focus + stamp type_text with that app so keys don't hit the old window."""
    out: list[dict] = []
    last_app = ""
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        row = {**step, "args": dict(step.get("args") or {})}
        tool = row.get("tool") or ""
        device = str(row.get("device") or "").strip().lower()
        args = row["args"]
        if device == "laptop" and tool == "open_app":
            last_app = str(args.get("app") or args.get("name") or "").strip()
            out.append(row)
            continue
        if device == "laptop" and tool == "focus_window":
            last_app = str(args.get("app") or args.get("name") or last_app).strip() or last_app
            out.append(row)
            continue
        if device == "laptop" and tool == "type_text":
            app = str(args.get("app") or args.get("into") or args.get("window") or last_app).strip()
            if app:
                args["app"] = app
                last_app = app
                if not out or out[-1].get("tool") != "focus_window" or str(
                    (out[-1].get("args") or {}).get("app") or ""
                ).lower() != app.lower():
                    out.append({"device": "laptop", "tool": "focus_window", "args": {"app": app}})
            out.append({**row, "args": args})
            continue
        out.append(row)
    return out


def _finish_plan(text: str, session: str, plan: dict, target: str = "auto") -> dict:
    raw_steps = plan.get("steps") or []
    if isinstance(raw_steps, list):
        raw_steps = _fill_slots(text, [dict(step) if isinstance(step, dict) else step for step in raw_steps])
    steps = _ensure_type_target(_assign_devices(raw_steps, text, session, target))
    opened = _assign_devices(_open_sequence(text), text, session, target)
    if len(opened) >= 2:
        planned = [step for step in steps if step.get("tool") in {"open_app", "close_app"}]
        if len(planned) < len(opened):
            other = [step for step in steps if step.get("tool") not in {"open_app", "close_app"}]
            steps = opened + other
            plan = {**plan, "reply": _brief_reply(steps, "")}
    if not steps:
        spoken = plan.get("reply") or "What should I do?"
        apps = _remember(session, []) if session == "phone" else []
        result = {
            "spoken": spoken,
            "confirm": None,
            "phone_steps": [],
            "apps": apps,
            "machines": [],
            "steps_run": [],
            "planner": plan.get("planner") or PLANNER,
            "source": plan.get("source") or "",
        }
        _remember_run(result)
        return result
    print("[marc-api] seq", [step.get("tool") for step in steps], flush=True)
    result = gate_steps(text, {**plan, "steps": steps}, allow_retry=False)
    if session == "phone":
        result = {**result, "apps": _remember(session, result.get("phone_steps") or [])}
    return result


def _instant(text: str) -> str | None:
    import re

    low = text.lower().strip(" ?.!")
    if re.fullmatch(r"(?:hi|hello|hey|yo)(?:\s+there)?(?:\s+marc)?|marc", low):
        return "Here."
    if low in {"time", "what time is it", "what's the time", "whats the time"} or re.search(
        r"\b(what time|current time)\b", low
    ):
        return time.strftime("%-I:%M %p")
    if low in {"date", "what's the date", "whats the date", "what day is it"} or re.search(
        r"\b(today's date|todays date)\b", low
    ):
        return time.strftime("%A, %-d %B")
    if re.search(r"\b(what was i doing|where did we leave off|where we left off|catch me up|what's going on|whats going on)\b", low):
        return mind_store.now_speak()
    remembered = re.match(r"^(?:please\s+)?remember(?:\s+that)?\s+(.+)$", text.strip(), re.I)
    if remembered:
        return _memory_add_note(remembered.group(1))
    forgot = re.match(r"^(?:please\s+)?forget(?:\s+that)?(?:\s+(.+))?$", text.strip(), re.I)
    if forgot:
        return _memory_forget(forgot.group(1) or "")
    if re.search(r"\b(who am i|what do you remember|what do you know about me)\b", low):
        return _memory_speak()
    if re.search(r"\b(?:what'?s|whats|what is)\s+(?:the\s+|my\s+)?ip(?:\s+address)?\b", low) or low in {
        "ip",
        "ip address",
        "whats ip",
        "what's ip",
    }:
        return _ip_speak()
    return None


def _ip_speak() -> str:
    addrs = []
    try:
        addrs.extend(subprocess.check_output(["tailscale", "ip", "-4"], text=True, timeout=2).split())
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        for item in subprocess.check_output(["hostname", "-I"], text=True, timeout=2).split():
            if item not in addrs:
                addrs.append(item)
    except (OSError, subprocess.SubprocessError):
        pass
    shown = [item for item in addrs if item and not item.startswith("127.")][:3]
    if not shown:
        return "I couldn't read the IP."
    return "IP " + ", ".join(shown) + "."


def _media_followup(text: str) -> str | None:
    import re

    low = text.lower().strip(" ?.!")
    if re.search(r"\b(?:open|close|send|text|whatsapp|instagram)\b", low):
        return None
    if re.search(r"\b(?:next|skip)\b", low):
        return "next"
    if re.search(r"\b(?:previous|prev)\b", low):
        return "previous"
    if re.fullmatch(r"(?:please\s+)?(?:pause|stop)(?:\s+(?:the\s+)?(?:music|song|spotify))?", low):
        return "pause" if "pause" in low else "stop"
    if re.fullmatch(r"(?:please\s+)?(?:resume|play|play music|resume music)", low):
        return "play"
    return None


def _contact_and_body(text: str, session: str) -> tuple[str, str]:
    import re

    stop = {
        "hi", "hello", "hey", "this", "that", "please", "regarding", "about", "saying",
        "ill", "i'll", "im", "i'm", "i", "be", "late", "home", "out", "for", "dinner",
        "the", "a", "an", "on", "in", "to", "and", "then",
    }
    said = re.search(r"\b(?:that|saying|regarding|about)\s+(.+)$", text, re.I)
    if said:
        body = said.group(1).strip(" .")
        who = re.search(
            r"\b(?:send|text|message|whatsapp|instagram)\s+(.+?)\s+"
            r"(?:on\s+\w+\s+)?(?:that|saying|regarding|about)\b",
            text,
            re.I,
        )
        contact = who.group(1).strip() if who else ""
    else:
        chunk = re.search(r"\b(?:text|message)\s+(.+)$", text, re.I)
        if not chunk:
            # "Open WhatsApp … and text Ranjith …"
            chunk = re.search(r"\b(?:text|message)\s+([A-Za-z][\w .'-]{0,40})$", text, re.I)
        if not chunk:
            return "", ""
        words = chunk.group(1).strip(" .").split()
        who_words = []
        index = 0
        # One or two name tokens only — never swallow the message body.
        while index < len(words) and index < 2 and words[index].lower().strip(".,") not in stop:
            token = words[index].strip(".,")
            if not token or not re.match(r"^[A-Za-z]", token):
                break
            who_words.append(token)
            index += 1
        contact = " ".join(who_words)
        body = " ".join(words[index:])
    body = re.sub(r"\s+and\s+send(?:\s+(?:it|him|her|them))?$", "", body, flags=re.I).strip(" .")
    named = re.search(r"\b(?:whatsapp|instagram)\s+(?:to\s+)?(.+?)\s+and\s+(?:text|message)\b", text, re.I)
    if contact.lower() in {"", "him", "her", "them", "to"} and named:
        contact = named.group(1).strip()
    if contact.lower() in {"him", "her", "them", "to"}:
        contact = str(_state(session).get("contact") or "")
    contact = re.sub(r"^(?:to|on)\s+", "", contact, flags=re.I).strip()
    contact = re.sub(r"\s+on\s+(?:whatsapp|instagram|messages|laptop|phone)$", "", contact, flags=re.I).strip()
    # Strip trailing device phrases stuck to the name.
    contact = re.sub(
        r"\s+on\s+(?:my\s+|the\s+)?(?:laptop|computer|pc|phone|mobile)$",
        "",
        contact,
        flags=re.I,
    ).strip()
    if body.lower() in {"this", "that", "it"}:
        body = str(_state(session).get("last_utterance") or "").strip()
    return contact, body


def _message_followup(text: str, session: str) -> dict | None:
    import re

    low = re.sub(r"what'?s?\s*app|what s up", "whatsapp", text.lower())
    if "instagram" in low or re.search(r"\binsta\b", low):
        tool = "instagram_send"
    elif "whatsapp" in low:
        tool = "whatsapp_send"
    elif re.search(r"\b(?:text|sms)\b", low):
        tool = "sms_send"
    else:
        return None
    contact, body = _contact_and_body(text, session)
    if not contact or not body:
        return None
    draft = bool(re.search(r"\b(?:draft|don't send|do not send)\b", low))
    send = (not draft) and bool(re.search(r"\bsend\b", low))
    if tool == "sms_send" and re.search(r"\btext\b", low) and not draft:
        send = True
    who_spoken = contact
    if tool == "whatsapp_send":
        reply = f"Sent to {who_spoken} on WhatsApp." if send else f"WhatsApp to {who_spoken}."
    elif tool == "instagram_send":
        reply = f"Sent to {who_spoken} on Instagram." if send else f"Instagram to {who_spoken}."
    else:
        reply = f"Sent to {who_spoken}." if send else f"Text to {who_spoken}."
    return {"reply": reply, "steps": [{"device": "phone", "tool": tool, "args": {"contact": contact, "text": body, "send": send}}]}


def _type_into(text: str) -> dict | None:
    import re

    match = re.match(r"(?:please\s+)?(?:type|enter)\s+(.+)$", text.strip(), re.I)
    if not match:
        return None
    body = match.group(1).strip(" .")
    if not body:
        return None
    return {"reply": "Typed.", "steps": [{"device": "phone", "tool": "type_into", "args": {"text": body}}]}


def _named_song(text: str) -> dict | None:
    import re

    low = text.lower()
    if re.search(r"\b(?:whatsapp|video|youtube|instagram)\b", low):
        return None
    if not re.match(r"(?:please\s+)?play\s+\S", text.strip(), re.I):
        return None
    query = _music_query(text)
    if not query:
        return None
    return {"reply": f"Playing {query}.", "steps": [{"device": "phone", "tool": "play_music", "args": {"query": query}}]}


def _phone_followup(text: str, session: str) -> dict | None:
    import re

    low = text.lower().strip(" ?.!")
    typed = _type_into(text)
    if typed:
        return typed
    song = _named_song(text)
    if song:
        return song
    message = _message_followup(text, session)
    if message:
        return message
    action = _media_followup(text)
    if action:
        spoken = {"next": "Next.", "previous": "Previous.", "pause": "Paused.", "stop": "Stopped.", "play": "Playing."}[action]
        return {"reply": spoken, "steps": [{"device": "phone", "tool": "media_key", "args": {"action": action}}]}
    if re.search(r"\bconnect\b", low) and "tailscale" in low:
        return {
            "reply": "Connecting Tailscale.",
            "steps": [
                {"device": "phone", "tool": "open_app", "args": {"name": "Tailscale"}},
                {"device": "phone", "tool": "ui_tap", "args": {"package": "com.tailscale.ipn", "text": "Connect"}},
            ],
        }
    closed = re.search(r"\b(?:close|quit|exit)\s+(.+)$", text, re.I)
    if closed and not _multi_phrase(text):
        name = closed.group(1).strip(" .")
        name = re.sub(r"\s+on\s+my\s+phone$", "", name, flags=re.I).strip()
        if name.lower() in {"it", "this", "that", "the app"}:
            name = _state(session).get("front") or "Spotify"
        return {"reply": f"Closing {name}.", "steps": [{"device": "phone", "tool": "close_app", "args": {"name": name}}]}
    opened = re.search(r"\b(?:open|launch|start)\s+(.+)$", text, re.I)
    if opened and not _multi_phrase(text) and not re.search(r"\b(?:send|that|saying)\b", low):
        name = opened.group(1).strip(" .")
        return {"reply": f"Opening {name}.", "steps": [{"device": "phone", "tool": "open_app", "args": {"name": name}}]}
    return None


def _handle_phone(text: str, session: str, target: str = "auto") -> dict:
    follow = _phone_followup(text, session)
    if follow is not None:
        print("[marc-api] phone", [step.get("tool") for step in follow["steps"]], flush=True)
        result = _finish_plan(text, session, follow, target)
    elif (scripted := _scripted_plan(text, session, target)) is not None:
        result = _finish_plan(text, session, scripted, target)
    elif _multi_phrase(text):
        print("[marc-api] needle-seq", flush=True)
        result = _finish_plan(text, session, plan_command(text, context=_context_line(session), session=session), target)
    else:
        steps = _assign_devices(_obvious_steps(text, _fallback_steps(text)), text, session, target)
        if len(steps) == 1 and (steps[0].get("device") == "phone" or steps[0].get("tool") in PHONE_TOOLS):
            print("[marc-api] fast", [step.get("tool") for step in steps], flush=True)
            result = _finish_plan(text, session, {"reply": _brief_reply(steps, ""), "steps": steps}, target)
        else:
            print("[marc-api] needle-seq", flush=True)
            result = _finish_plan(text, session, plan_command(text, context=_context_line(session), session=session), target)
    _state(session)["last_utterance"] = text
    return result


INBOX_PATH = os.environ.get("MARC_INBOX_FILE", "/home/rox/marc/phone_inbox.json")


def _save_inbox() -> None:
    path = INBOX_PATH
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_inbox[-8:], handle)
        os.replace(tmp, path)
    except OSError:
        return


def _load_inbox() -> None:
    global _inbox
    try:
        with open(INBOX_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, list):
        _inbox = [item for item in data if isinstance(item, dict)][-8:]


def _enqueue_phone(spoken: str, steps: list) -> None:
    with _inbox_lock:
        _inbox.append({"spoken": spoken, "phone_steps": steps})
        del _inbox[:-8]
        _save_inbox()


def _take_inbox() -> list:
    with _inbox_lock:
        items = list(_inbox)
        _inbox.clear()
        _save_inbox()
        return items


def _desk(session: str, result: dict) -> dict:
    if session != "desk" or not isinstance(result, dict):
        return result
    confirm = result.get("confirm")
    if isinstance(confirm, dict) and confirm.get("token"):
        item = PENDING.get(confirm["token"])
        if item is not None:
            item["session"] = "desk"
    spoken = result.get("spoken") or ""
    if confirm:
        spoken = spoken.replace(
            "Confirm on your phone before I continue.",
            "Press Yes here before I continue.",
        )
    steps = result.get("phone_steps") or []
    if steps:
        _enqueue_phone(spoken, steps)
    machines = list(result.get("machines") or [])
    if steps and "phone" not in machines:
        machines.append("phone")
    if not machines and (steps or confirm or result.get("steps_run")):
        machines.append("laptop")
    return {**result, "spoken": spoken, "machines": machines, "steps_run": result.get("steps_run") or []}


def _phone_named(text: str) -> bool:
    import re

    return bool(re.search(r"\bon\s+(?:my\s+|the\s+)?(?:phone|mobile)\b", text, re.I))


_load_inbox()


def _empty_reply(spoken: str, **extra) -> dict:
    result = {
        "spoken": spoken,
        "confirm": None,
        "phone_steps": [],
        "machines": [],
        "steps_run": [],
        **extra,
    }
    return result


def _direct_command(text: str, session: str, target: str = "auto") -> dict | None:
    """Open and close are decided here, so the desk does not wait on a model."""
    import re

    if _multi_phrase(text):
        return None
    low = text.lower()
    opened = re.search(r"\b(?:open|launch|start)\s+(.+)$", text, re.I)
    closed = re.search(r"\b(?:close|quit|exit)\s+(.+)$", text, re.I)
    if opened and re.search(r"\b(?:send|that|saying)\b", low):
        opened = None
    match = opened or closed
    if not match:
        return None
    name = re.sub(
        r"\s+on\s+(?:my\s+|the\s+)?(?:phone|mobile|laptop|computer|pc)$",
        "",
        match.group(1),
        flags=re.I,
    ).strip(" .")
    if not name or name.lower() in {"it", "this", "that", "the app"}:
        return None
    phone = _session_target(text, session, target) == "phone"
    tool = "open_app" if opened else "close_app"
    args = {"name": name} if phone else {"app": name}
    verb = "Opening" if opened else "Closing"
    where = "on your phone" if phone else "on your laptop"
    plan = {
        "reply": f"{verb} {name} {where}.",
        "steps": [{"device": "phone" if phone else "laptop", "tool": tool, "args": args}],
    }
    print("[marc-api] direct", tool, "phone" if phone else "laptop", flush=True)
    return gate_steps(text, plan, allow_retry=False)


def _direct_server(text: str, session: str, target: str = "auto") -> dict | None:
    """Status, restart, and docker on the home server. No shell."""
    import re

    dest = _session_target(text, session, target)
    low = text.lower()
    restart = re.search(
        r"\brestart\s+(?:the\s+)?(ollama|model|qwen|n8n|desk|site|web|api|bridge|marc-api|marc-desk|marc-bridge)\b",
        text,
        re.I,
    )
    status = re.search(
        r"\b(?:status|health|how hot|temperature|temp|load|cpu)\b",
        low,
    ) and (dest == "server" or _server_named(text) or re.search(r"\bserver\b", low))
    docker_list = re.search(r"\b(?:list\s+)?(?:docker|containers)\b", low)
    docker_restart = re.search(r"\brestart\s+(?:the\s+)?n8n\b", text, re.I)
    if restart:
        name = restart.group(1).lower()
        if name == "n8n" or docker_restart:
            plan = {
                "reply": "Restarting n8n.",
                "steps": [{"device": "server", "tool": "docker_restart", "args": {"name": "n8n"}}],
            }
        else:
            plan = {
                "reply": f"Restarting {name}.",
                "steps": [{"device": "server", "tool": "service_restart", "args": {"name": name}}],
            }
        print("[marc-api] server", plan["steps"][0]["tool"], name, flush=True)
        return gate_steps(text, plan, allow_retry=False)
    if docker_list:
        plan = {"reply": "Listing containers.", "steps": [{"device": "server", "tool": "docker_list", "args": {}}]}
        print("[marc-api] server docker_list", flush=True)
        return gate_steps(text, plan, allow_retry=False)
    if _wants_agent(text):
        return None
    if dest == "server" or _server_named(text) or status:
        if dest == "server" and re.search(r"\b(?:open|launch|start|close|quit|exit)\b", low):
            return _empty_reply("The home server has no desktop. Ask for status, a restart, or docker.")
        if status or dest == "server" or _server_named(text):
            plan = {"reply": "Checking the server.", "steps": [{"device": "server", "tool": "server_status", "args": {}}]}
            print("[marc-api] server status", flush=True)
            return gate_steps(text, plan, allow_retry=False)
    return None


def _wants_agent(text: str, scored: dict | None = None) -> bool:
    import re

    if scored is not None:
        if float(scored.get("is_multi_step") or 0) >= 0.5 or float(scored.get("needs_planner") or 0) >= 0.65:
            return True
    return bool(re.search(AGENT_HINT_RE, text or "", re.I))


def _seed_agent_step(text: str) -> dict | None:
    import re

    listed = re.search(r"\b(?:list|ls|show)\s+(?:the\s+)?files(?:\s+in\s+(\S+))?", text, re.I)
    if listed:
        path = (listed.group(1) or "/home/rox/marc").strip(" .")
        return {"think": "list files", "tool": "server_shell", "args": {"cmd": f"ls -la {path}"}, "done": False}
    if re.search(r"\b(?:is\s+)?ollama\b.*\b(?:up|running|active)\b|\bollama\s+(?:status|up)\b", text, re.I):
        return {"think": "check ollama", "tool": "service_status", "args": {"name": "ollama"}, "done": False}
    return None


def _agent_parse(content: str) -> dict | None:
    try:
        parsed = _extract_json(content)
    except (json.JSONDecodeError, ValueError):
        parsed = {}
    if not isinstance(parsed, dict) or not parsed:
        return None
    return parsed


def _agent_turn(history: list) -> dict | None:
    messages = [{"role": "system", "content": AGENT_SYSTEM}]
    messages.extend(history[-8:])
    try:
        data = _post(
            OLLAMA_URL,
            {
                "model": AGENT_MODEL,
                "stream": False,
                "messages": messages,
                "format": "json",
                "keep_alive": "30m",
                "options": {"temperature": 0, "num_predict": 80, "num_ctx": 768, "repeat_penalty": 1.15},
            },
            timeout=90,
        )
    except Exception as exc:  # noqa: BLE001
        print("[marc-api] agent fail", exc, flush=True)
        return None
    content = ((data.get("message") or {}).get("content")) or ""
    return _agent_parse(content)


def _step_from_agent(parsed: dict, text: str, session: str, target: str) -> dict:
    tool = str(parsed.get("tool") or "").strip()
    args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
    step = {"tool": tool, "args": dict(args), "device": parsed.get("device") or ""}
    routed = _assign_devices([step], text, session, target)
    return routed[0] if routed else step


def run_agent_loop(text: str, session: str, target: str = "auto") -> dict | None:
    """Python owns the loop. 0.5B emits one JSON tool per hop."""
    ctx = _context_line(session)
    history = [{"role": "user", "content": f"{ctx}\nUser: {text}" if ctx else text}]
    steps_run: list[dict] = []
    phone_steps: list[dict] = []
    parse_fails = 0
    spoken = ""
    seeded = False
    for hop in range(1, AGENT_MAX_HOPS + 1):
        parsed = None
        if hop == 1 and not seeded:
            parsed = _seed_agent_step(text)
            seeded = parsed is not None
        if parsed is None:
            parsed = _agent_turn(history)
        if parsed is None:
            parse_fails += 1
            if parse_fails >= 2:
                break
            history.append({"role": "user", "content": "Return one JSON object only."})
            continue
        parse_fails = 0
        think = str(parsed.get("think") or "")[:120]
        if parsed.get("done") or not parsed.get("tool"):
            spoken = str(parsed.get("reply") or spoken or "Done.")
            steps_run.append({
                "hop": hop,
                "think": think,
                "device": "",
                "tool": "done",
                "ok": True,
                "message": spoken,
            })
            break
        step = _step_from_agent(parsed, text, session, target)
        tool = str(step.get("tool") or "")
        if tool not in PHONE_TOOLS and tool not in LAPTOP_TOOLS and tool not in SERVER_TOOLS:
            result = {"ok": False, "message": "Unknown tool.", "device": "", "phone_step": None}
        else:
            result = exec_step(step)
        message = str(result.get("message") or "")
        obs = message[:400]
        steps_run.append({
            "hop": hop,
            "think": think,
            "device": result.get("device") or step.get("device"),
            "tool": tool,
            "ok": bool(result.get("ok")),
            "message": message,
        })
        if result.get("phone_step"):
            phone_steps.append(result["phone_step"])
        spoken = message or spoken
        history.append({"role": "assistant", "content": json.dumps({"think": think, "tool": tool, "done": False})})
        history.append({"role": "user", "content": f"Observation: {obs}"})
    if not steps_run:
        return None
    if not spoken:
        spoken = str(steps_run[-1].get("message") or "Done.")
    machines = []
    for step in steps_run:
        device = step.get("device")
        if device and device not in machines:
            machines.append(device)
    result = {
        "spoken": spoken or "Done.",
        "confirm": None,
        "phone_steps": phone_steps,
        "machines": machines,
        "steps_run": steps_run,
    }
    if session == "phone":
        result = {**result, "apps": _remember(session, phone_steps)}
    _remember_run(result)
    print("[marc-api] agent", [step.get("tool") for step in steps_run], flush=True)
    return result


def handle_utterance(body: dict) -> dict:
    text = (body.get("text") or "").strip()
    session = str(body.get("session_id") or "")
    target = _requested_target(body)
    dest = _session_target(text, session, target)
    if not text:
        return _empty_reply("I didn't catch that.")
    global _LAST_RUN
    run = _activity_start(text, session)
    run["phase"] = "planning"
    _activity_event(run, "planning", PLANNER)
    _LAST_RUN = {
        "spoken": "",
        "machines": [],
        "steps_run": [],
        "planner": PLANNER,
        "source": "",
        "run_id": run["id"],
        "phase": "planning",
        "text": text,
        "at": int(time.time() * 1000),
    }
    try:
        result = _utterance_body(text, session, target, dest, body)
    except Exception:
        run["phase"] = "fail"
        _activity_event(run, "fail", "planner error")
        raise
    return _activity_attach(result, run)


def _utterance_body(text: str, session: str, target: str, dest: str, body: dict) -> dict:
    _memory_load()
    quick = _instant(text)
    if quick:
        print("[marc-api] instant", flush=True)
        apps = list(_state(session)["apps"]) if session == "phone" else []
        return _empty_reply(quick, apps=apps, source="instant", planner="local")
    if re.search(r"\b(reboot|shutdown|halt|poweroff)\b", text, re.I):
        return _empty_reply("I won't reboot or shut down.", source="guard", planner="local")
    if re.search(r"rm\s+-rf\s+/", text, re.I):
        return _empty_reply("I won't run that.", source="guard", planner="local")
    if session == "phone":
        _state(session)["last_utterance"] = text

    # Hermes + Cognee RAG owns phone/laptop/server actions (including continuous chains).
    if PLANNER in ("hermes", "muse", "meta"):
        if _looks_like_action(text) or _multi_phrase(text) or _wants_agent(text) or target in {
            "phone", "laptop", "server",
        } or dest in {"phone", "laptop", "server"}:
            return _hermes_rag_plan(text, session, target)
        # Pure chat still gets brain context through Hermes so mind stays linked.
        return _hermes_rag_plan(text, session, target)

    server = _direct_server(text, session, target)
    if server is not None:
        return {**server, "planner": server.get("planner") or "direct", "source": server.get("source") or "direct"}
    direct = _direct_command(text, session, target)
    if direct is not None:
        return {**direct, "planner": "direct", "source": "direct"}
    scripted = _scripted_plan(text, session, target)
    if scripted is not None:
        return _finish_plan(text, session, {**scripted, "source": scripted.get("source") or "scripted"}, target)
    if dest == "phone" and session == "phone" and not _wants_agent(text):
        return _handle_phone(text, session, target)
    if _multi_phrase(text) and not _wants_agent(text):
        print("[marc-api] needle-seq", flush=True)
        return _finish_plan(text, session, plan_command(text, context=_plan_context(text, session), session=session), target)
    steps = _assign_devices(_obvious_steps(text, _fallback_steps(text)), text, session, target)
    if len(steps) > 1 and not _wants_agent(text):
        print("[marc-api] needle-seq", flush=True)
        return _finish_plan(text, session, plan_command(text, context=_plan_context(text, session), session=session), target)
    if len(steps) == 1 and not _wants_agent(text):
        print("[marc-api] fast", [step.get("tool") for step in steps], flush=True)
        plan = {"reply": _brief_reply(steps, ""), "steps": steps, "source": "heuristic"}
        return gate_steps(text, plan, allow_retry=False)
    if LAPTOP_URL and dest == "laptop" and session != "phone" and not _wants_agent(text):
        try:
            ruled = laptop_call("/rule", {"text": text})
        except Exception as exc:  # noqa: BLE001
            ruled = {"owned": False, "error": str(exc)}
        if ruled.get("owned"):
            result = {
                "spoken": ruled.get("spoken") or ruled.get("message") or "Done.",
                "confirm": None,
                "phone_steps": [],
                "machines": ["laptop"],
                "steps_run": [{
                    "device": "laptop",
                    "tool": ruled.get("intent") or "tool",
                    "ok": bool(ruled.get("ok", True)),
                    "message": ruled.get("message") or ruled.get("spoken") or "",
                }],
                "planner": PLANNER,
                "source": "laptop-rule",
            }
            _remember_run(result)
            return result
    scored = None if PLANNER == "needle" or _wants_agent(text) else _classify_laya(text)
    if scored is not None and not _wants_agent(text, scored):
        laya_steps = _steps_from_laya(text, scored)
        if laya_steps:
            laya_steps = _assign_devices(laya_steps, text, session, target)
            print("[marc-api] laya-step", [step.get("tool") for step in laya_steps], flush=True)
            plan = {"reply": _brief_reply(laya_steps, ""), "steps": laya_steps, "source": "laya"}
            return gate_steps(text, plan, allow_retry=False)
    return _finish_plan(text, session, plan_command(text, context=_plan_context(text, session), session=session), target)


def handle_chat(body: dict) -> dict:
    session = str(body.get("session_id") or "desk")
    print("[marc-api] chat-needle", flush=True)
    return handle_utterance({**body, "session_id": session})


def handle_confirm(body: dict) -> dict:
    token = body.get("token") or ""
    item = PENDING.get(token)
    if not item or item["expires"] < time.time():
        PENDING.pop(token, None)
        return {"spoken": "That confirm expired. Ask again.", "confirm": None, "phone_steps": []}
    if not body.get("yes"):
        PENDING.pop(token, None)
        return {"spoken": "Cancelled.", "confirm": None, "phone_steps": []}
    messages = []
    phone_steps = list(item.get("phone_rest") or [])
    extra_phone = []
    for step in item["steps"]:
        if step.get("device") == "phone" or step.get("tool") in PHONE_TOOLS:
            extra_phone.append(step)
            continue
        try:
            result = laptop_call("/tool", {"tool": step["tool"], "args": step.get("args") or {}, "confirmed": True})
        except Exception:  # noqa: BLE001
            result = {"ok": False, "message": "Laptop isn't connected."}
        if step.get("tool") in ("mail_compose", "mail_send") and not result.get("ok"):
            extra_phone.append({"device": "phone", "tool": "mail_compose", "args": step.get("args") or {}})
            messages.append("Opening the mail on your phone.")
            continue
        messages.append(result.get("message") or "")
    session = str(item.get("session") or "")
    PENDING.pop(token, None)
    spoken = " ".join(m for m in messages if m) or "Confirmed."
    steps = extra_phone + phone_steps
    result = {"spoken": spoken, "confirm": None, "phone_steps": steps, "machines": ["phone"] if steps else ["laptop"]}
    if session == "desk":
        result = _desk(session, result)
    return result


_net_prev: tuple[float, int, int] | None = None


def _read_cpu() -> tuple[int, int]:
    with open("/proc/stat", encoding="utf-8") as handle:
        parts = handle.readline().split()
    nums = [int(part) for part in parts[1:]]
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    return sum(nums), idle


def _cpu_percent() -> float:
    first = _read_cpu()
    time.sleep(0.12)
    second = _read_cpu()
    total = second[0] - first[0]
    idle = second[1] - first[1]
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (total - idle) / total)), 1)


def _vcgen(*args: str) -> str:
    try:
        return subprocess.check_output(["vcgencmd", *args], text=True, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _first_float(raw: str) -> float:
    digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in raw).split()
    return float(digits[0]) if digits else 0.0


def _throttled() -> int:
    raw = _vcgen("get_throttled")
    if "=" not in raw:
        return 0
    try:
        return int(raw.split("=", 1)[1], 16)
    except ValueError:
        return 0


def _mem() -> dict:
    info: dict[str, int] = {}
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            info[key] = int(rest.strip().split()[0]) * 1024
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    return {"total": total, "used": max(0, total - avail), "avail": avail}


def _disk() -> dict:
    stat = os.statvfs("/")
    total = stat.f_frsize * stat.f_blocks
    free = stat.f_frsize * stat.f_bavail
    return {"total": total, "used": max(0, total - free), "free": free}


_volume_lock = threading.Lock()
_folder_of: dict[str, str] = {}
_FS = {"ext4", "ext3", "ext2", "vfat", "exfat", "ntfs", "fuseblk", "btrfs", "xfs", "f2fs"}


def _disk_of(node: str) -> str:
    name = node.rsplit("/", 1)[-1]
    if name.startswith("mmcblk"):
        head, sep, _tail = name.partition("p")
        return head if sep else name
    return name.rstrip("0123456789")


def _root_disk() -> str:
    try:
        lines = open("/proc/mounts", encoding="utf-8").read().splitlines()
    except OSError:
        return ""
    for line in lines:
        parts = line.split()
        if len(parts) > 1 and parts[1] == "/":
            return _disk_of(parts[0])
    return ""


def _mount_table() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    try:
        lines = open("/proc/mounts", encoding="utf-8").read().splitlines()
    except OSError:
        return rows
    for line in lines:
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith("/"):
            continue
        try:
            dev = os.path.realpath(parts[0])
        except OSError:
            dev = parts[0]
        rows.append((dev, parts[1]))
    return rows


def _usage(mount: str) -> tuple[int, int] | None:
    try:
        stat = os.statvfs(mount)
    except OSError:
        return None
    total = stat.f_frsize * stat.f_blocks
    free = stat.f_frsize * stat.f_bavail
    if total <= 0:
        return None
    return max(0, total - free), total


def _part_bytes(part: str) -> int:
    try:
        with open(f"/sys/class/block/{part}/size", encoding="utf-8") as handle:
            return int(handle.read().strip()) * 512
    except (OSError, ValueError):
        return 0


def _stable_disk(disk: str) -> str:
    folder = "/dev/disk/by-id"
    try:
        names = os.listdir(folder)
    except OSError:
        return disk
    real = os.path.realpath(f"/dev/{disk}")
    for name in sorted(names):
        if "-part" in name:
            continue
        try:
            if os.path.realpath(os.path.join(folder, name)) == real:
                return name
        except OSError:
            continue
    return disk


def _lsblk_tree() -> list:
    try:
        done = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,TYPE,TRAN,FSTYPE,LABEL,MOUNTPOINT"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        data = json.loads(done.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    return data.get("blockdevices") or []


def _mounted_at(part: str) -> str:
    real = os.path.realpath(f"/dev/{part}")
    for dev, mount in _mount_table():
        if dev == real:
            return mount
    return ""


def _mount_mode(part: str) -> str:
    real = os.path.realpath(f"/dev/{part}")
    try:
        lines = open("/proc/mounts", encoding="utf-8").read().splitlines()
    except OSError:
        return ""
    for line in lines:
        parts = line.split()
        if len(parts) < 4 or not parts[0].startswith("/"):
            continue
        try:
            dev = os.path.realpath(parts[0])
        except OSError:
            dev = parts[0]
        if dev != real:
            continue
        return "ro" if "ro" in parts[3].split(",") else "rw"
    return ""


def _folder_for(disk_id: str, kind: str) -> str:
    known = _folder_of.get(disk_id)
    if known:
        return known
    pool = ["/mnt/sdcard"] if kind == "sd" else ["/mnt/pendrive-a", "/mnt/pendrive-b"]
    taken = set(_folder_of.values())
    for folder in pool:
        if folder not in taken:
            _folder_of[disk_id] = folder
            return folder
    folder = "/mnt/" + kind + "-" + str(len(_folder_of) + 1)
    _folder_of[disk_id] = folder
    return folder


def _mount_rw(part: str, folder: str) -> bool:
    uid = os.getuid()
    gid = os.getgid()
    attempts = [
        f"rw,nosuid,nodev,uid={uid},gid={gid},umask=022",
        f"rw,uid={uid},gid={gid}",
        "rw",
    ]
    mode = _mount_mode(part)
    if mode == "rw":
        return True
    try:
        if mode == "ro":
            where = _mounted_at(part) or folder
            for opts in attempts:
                done = subprocess.run(
                    ["sudo", "-n", "mount", "-o", "remount," + opts, where],
                    capture_output=True,
                    timeout=12,
                    check=False,
                )
                if done.returncode == 0 and _mount_mode(part) == "rw":
                    return True
        else:
            subprocess.run(["sudo", "-n", "mkdir", "-p", folder], capture_output=True, timeout=8, check=False)
            for opts in attempts:
                done = subprocess.run(
                    ["sudo", "-n", "mount", "-o", opts, f"/dev/{part}", folder],
                    capture_output=True,
                    timeout=12,
                    check=False,
                )
                if done.returncode == 0 and _mount_mode(part) == "rw":
                    return True
        err = (done.stderr or b"").decode(errors="replace").strip()
        print(f"[marc-api] mount {part} failed: {err[-180:]}", flush=True)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[marc-api] mount {part} failed: {exc}", flush=True)
    return _mount_mode(part) == "rw"


def _volume_row(name: str, mount: str, used: int, total: int, kind: str, readable: bool) -> dict:
    return {
        "name": name,
        "mount": mount,
        "used": used,
        "total": total,
        "kind": kind,
        "readable": readable,
        "count": readable and kind in {"system", "sd", "pendrive"},
        "removable": kind == "pendrive",
    }


def _volumes() -> list:
    with _volume_lock:
        return _volumes_locked()


def _volumes_locked() -> list:
    rows = []
    root_disk = _root_disk()
    try:
        lines = open("/proc/mounts", encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    seen: set[str] = set()
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, mount, fstype = parts[0], parts[1], parts[2]
        if fstype not in _FS or mount in seen or _disk_of(dev) != root_disk:
            continue
        if mount not in {"/", "/boot", "/boot/firmware"}:
            continue
        usage = _usage(mount)
        if usage is None:
            continue
        seen.add(mount)
        used, total = usage
        if mount == "/":
            rows.append(_volume_row("System", mount, used, total, "system", True))
        else:
            rows.append(_volume_row("Boot", mount, used, total, "boot", True))

    extras = []
    for dev in _lsblk_tree():
        name = dev.get("name") or ""
        if not name or name.startswith(("loop", "ram", "zram")) or name == root_disk:
            continue
        tran = (dev.get("tran") or "").lower()
        if name.startswith("mmcblk"):
            kind = "sd"
        elif tran == "usb" or name.startswith("sd"):
            kind = "pendrive"
        else:
            continue
        children = dev.get("children") or []
        parts = children if children else [dev]
        disk_id = _stable_disk(name)
        for part in parts:
            fstype = (part.get("fstype") or "").lower()
            part_name = part.get("name") or ""
            if not part_name or fstype not in _FS:
                continue
            mount = _mounted_at(part_name)
            if mount and _mount_mode(part_name) != "rw":
                _mount_rw(part_name, mount)
            elif not mount:
                folder = _folder_for(disk_id, kind)
                real = os.path.realpath(f"/dev/{part_name}")
                busy = any(where == folder and holder != real for holder, where in _mount_table())
                if busy:
                    _folder_of.pop(disk_id, None)
                    folder = _folder_for(disk_id + ":" + part_name, kind)
                if _mount_rw(part_name, folder):
                    mount = _mounted_at(part_name) or folder
            part_total = _part_bytes(part_name)
            gib = round(part_total / 1073741824) if part_total else 0
            title = "SD" if kind == "sd" else (f"Pendrive {gib} GB" if gib else "Pendrive")
            usage = _usage(mount) if mount else None
            if usage is None:
                extras.append(_volume_row(title, mount or "", 0, part_total, kind, False))
            else:
                used, total = usage
                extras.append(_volume_row(title, mount, used, total, kind, True))
    extras.sort(key=lambda row: (0 if row["kind"] == "sd" else 1, row["name"]))
    rows.extend(extras)
    return rows


def _mhz() -> int:
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", encoding="utf-8") as handle:
            return int(handle.read().strip()) // 1000
    except OSError:
        return 0


def _throughput() -> dict:
    global _net_prev
    rx = tx = 0
    try:
        with open("/proc/net/dev", encoding="utf-8") as handle:
            for line in handle:
                if line.strip().startswith("eth0:"):
                    cols = line.split()
                    rx = int(cols[1])
                    tx = int(cols[9])
                    break
    except (OSError, IndexError, ValueError):
        return {"rx_bps": 0, "tx_bps": 0}
    now = time.monotonic()
    prev = _net_prev
    _net_prev = (now, rx, tx)
    if not prev:
        return {"rx_bps": 0, "tx_bps": 0}
    elapsed = now - prev[0]
    if elapsed <= 0:
        return {"rx_bps": 0, "tx_bps": 0}
    return {
        "rx_bps": max(0, int((rx - prev[1]) / elapsed)),
        "tx_bps": max(0, int((tx - prev[2]) / elapsed)),
    }


def _processes() -> list:
    try:
        done = subprocess.run(
            ["ps", "-eo", "comm,pcpu,pmem", "--sort=-pcpu"],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in done.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3 or parts[0] == "ps":
            continue
        try:
            rows.append({"name": parts[0][:24], "cpu": float(parts[1]), "mem": float(parts[2])})
        except ValueError:
            continue
        if len(rows) >= 8:
            break
    return rows


def _services() -> dict:
    names = ["marc-api", "marc-bridge", "ollama"]
    try:
        done = subprocess.run(
            ["systemctl", "is-active", *names],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
        lines = [line.strip() for line in done.stdout.splitlines()]
    except (OSError, subprocess.SubprocessError):
        lines = []
    while len(lines) < 3:
        lines.append("inactive")
    return {"api": lines[0] == "active", "bridge": lines[1] == "active", "ollama": lines[2] == "active"}


def machine_status() -> dict:
    flags = _throttled()
    with open("/proc/loadavg", encoding="utf-8") as handle:
        load_parts = handle.read().split()
    with open("/proc/uptime", encoding="utf-8") as handle:
        uptime = float(handle.read().split()[0])
    hermes = hermes_client.health()
    brain = cognee_bridge.health()
    meta = muse_client.health()
    return {
        "ok": True,
        "uptime_s": int(uptime),
        "load": [float(load_parts[0]), float(load_parts[1]), float(load_parts[2])],
        "cpu_pct": _cpu_percent(),
        "cpu_mhz": _mhz(),
        "temp_c": _first_float(_vcgen("measure_temp")),
        "throttled": flags,
        "supply": "Low" if flags & 0x1 or flags & 0x10000 else "Good",
        "core_v": _first_float(_vcgen("measure_volts")),
        "mem": _mem(),
        "disk": _disk(),
        "volumes": _volumes(),
        "net": _throughput(),
        "procs": _processes(),
        "services": _services(),
        "planner": PLANNER,
        "hermes": hermes,
        "cognee": brain,
        "meta_ai": {"ok": bool(meta.get("keyed")), "base": meta.get("base"), "spark": meta.get("spark")},
        "laptop": _laptop_health(),
        "agent": dict(_LAST_RUN),
        "phone": {
            "apps": list(_state("phone").get("apps") or []),
            "front": str(_state("phone").get("front") or ""),
            "last_utterance": str(_state("phone").get("last_utterance") or ""),
        },
    }


def _office_down(spoken: str) -> dict:
    mem = _memory_load().get("office") or _office_blank()
    return {
        "ok": False,
        "state": "down",
        "agent_id": mem.get("agent_id") or "",
        "cwd": mem.get("cwd") or "/home/rox/office/work",
        "remote": mem.get("remote") or "",
        "reachable": False,
        "summary": mem.get("last_summary") or "",
        "spoken": spoken,
        "hops": [],
    }


def _office_remember(payload: dict) -> None:
    if not isinstance(payload, dict):
        return
    mem = _memory_load()
    office = _office_clean(mem.get("office"))
    if payload.get("agent_id"):
        office["agent_id"] = str(payload.get("agent_id") or "")[:160]
    if payload.get("cwd"):
        office["cwd"] = str(payload.get("cwd") or "")[:400]
    if payload.get("remote"):
        office["remote"] = str(payload.get("remote") or "")[:400]
    summary = payload.get("summary") or payload.get("last_summary")
    if summary:
        office["last_summary"] = str(summary)[:800]
    mem["office"] = office
    _memory_save()


def _cursor_call(path: str, method: str, payload: dict | None = None, timeout: int = 8) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        CURSOR_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode())
        except (json.JSONDecodeError, TypeError, ValueError, UnicodeDecodeError):
            return _office_down("Office isn't running.")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return _office_down("Office isn't running.")
    if not isinstance(data, dict):
        return _office_down("Office isn't running.")
    _office_remember(data)
    return data


def handle_office(data: dict) -> dict:
    text = str((data or {}).get("text") or (data or {}).get("prompt") or "").strip()
    resume = bool((data or {}).get("resume", True))
    cwd = (data or {}).get("cwd")
    payload = {"prompt": text, "text": text, "resume": resume}
    if cwd:
        payload["cwd"] = str(cwd)
    if not resume and text:
        try:
            mind_store.project_from_task(text)
        except Exception as exc:  # noqa: BLE001
            print("[marc-api] mind office skip", exc, flush=True)
    result = _cursor_call("/run", "POST", payload)
    if "spoken" not in result:
        result["spoken"] = result.get("summary") or "Working on the office folder."
    return result


def office_status() -> dict:
    result = _cursor_call("/status", "GET")
    if "spoken" not in result:
        if result.get("reachable") is False:
            result["spoken"] = "Office machine isn't reachable."
        else:
            result["spoken"] = result.get("summary") or ""
    return result


def cancel_office() -> dict:
    result = _cursor_call("/cancel", "POST", {})
    if "spoken" not in result:
        result["spoken"] = "Stopping."
    return result


import ytlock_store


def handle_ytlock(data: dict, *, public: bool) -> dict:
    return ytlock_store.handle(data or {}, public=public)


def ytlock_get(pin: str, *, public: bool) -> dict:
    return ytlock_store.get(pin, public=public)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print("[marc-api]", self.address_string(), fmt % args, flush=True)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = _token()
        if not expected:
            return True
        header = self.headers.get("Authorization") or ""
        return header == f"Bearer {expected}"

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._json(200, {
                "ok": True,
                "bind": BIND,
                "laptop": bool(LAPTOP_URL),
                "planner": PLANNER,
                "hermes": hermes_client.health().get("ok"),
                "cognee": True,
                "meta_ai": muse_client.health().get("keyed"),
            })
            return
        if path == "/status":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                payload = machine_status()
                if "take=1" in (self.path or ""):
                    payload["inbox"] = _take_inbox()
                self._json(200, payload)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/activity":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            query = parse_qs(urlparse(self.path).query)
            session_id = (query.get("session_id") or [""])[0]
            since_raw = (query.get("since") or ["0"])[0]
            try:
                since_ms = int(since_raw or 0)
            except ValueError:
                since_ms = 0
            self._json(200, activity_snapshot(session_id=session_id, since_ms=since_ms))
            return
        if path == "/office":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            self._json(200, office_status())
            return
        if path == "/ytlock":
            public = (self.headers.get("X-Ytlock-Public") or "") == "1"
            if not public and not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            pin = self.headers.get("X-Ytlock-Pin") or ""
            if "?" in (self.path or ""):
                pin = pin or (parse_qs(urlparse(self.path).query).get("pin") or [""])[0]
            self._json(200, ytlock_get(pin, public=public))
            return
        if path == "/mind":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            query = parse_qs(urlparse(self.path).query)
            self._json(200, handle_mind_get(query))
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid json"})
            return
        try:
            if path == "/utterance":
                session = str(data.get("session_id") or "")
                result = _mind_record(str(data.get("text") or ""), session, handle_utterance(data))
                self._json(200, _desk(session, result))
            elif path == "/chat":
                session = str(data.get("session_id") or "desk")
                result = _mind_record(str(data.get("text") or ""), session, handle_chat(data))
                self._json(200, _desk(session, result))
            elif path == "/mind":
                self._json(200, handle_mind_post(data))
            elif path == "/confirm":
                self._json(200, handle_confirm(data))
            elif path == "/office":
                self._json(200, handle_office(data))
            elif path == "/office-cancel":
                self._json(200, cancel_office())
            elif path == "/ytlock":
                public = (self.headers.get("X-Ytlock-Public") or "") == "1"
                self._json(200, handle_ytlock(data, public=public))
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except urllib.error.URLError as exc:
            self._json(502, {"spoken": f"A model call failed: {exc.reason}", "confirm": None, "phone_steps": []})
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"spoken": str(exc), "confirm": None, "phone_steps": []})


def main() -> None:
    try:
        mind_store.seed()
    except Exception as extra:  # noqa: BLE001
        print("[marc-api] mind seed", extra, flush=True)
    try:
        _ensure_needle_files()
    except Exception as extra:  # noqa: BLE001
        print("[marc-api] needle files", extra, flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[marc-api] listening on 0.0.0.0:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
