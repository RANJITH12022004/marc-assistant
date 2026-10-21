#!/usr/bin/env python3
"""Marc coordinator. Qwen writes steps. Local Laya scores them. Laptop and phone execute."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "marc")
AGENT_MODEL = os.environ.get("MARC_AGENT_MODEL", "") or OLLAMA_MODEL
AGENT_MAX_HOPS = 5
LAYA_URL = os.environ.get("LAYA_URL", "http://127.0.0.1:8091/score")
LAPTOP_URL = os.environ.get("MARC_LAPTOP_URL", "").rstrip("/")
TOKEN_PATH = os.environ.get("MARC_TOKEN_FILE", "/home/rox/marc/secret")
MEMORY_PATH = os.environ.get("MARC_MEMORY_FILE", "/home/rox/marc/memory.json")
BIND = os.environ.get("MARC_BIND", "127.0.0.1")
PORT = int(os.environ.get("MARC_PORT", "8090"))
CONFIRM_TTL = int(os.environ.get("MARC_CONFIRM_TTL", "300"))
MARC_EMAIL = os.environ.get("MARC_EMAIL", "").strip()

CONFIRM_TOOLS = {"mail_send", "mail_compose", "dial", "open_food_search"}
PHONE_TOOLS = {
    "play_music", "dial", "whatsapp_prefill", "whatsapp_send", "sms_send", "instagram_send",
    "open_food_search", "media_key", "ui_tap", "type_into",
}
LAPTOP_TOOLS = {
    "open_app", "close_app", "focus_window", "google_search", "youtube_search", "youtube_home",
    "youtube_media", "play_nth", "type_text", "hotkey", "volume_media", "mail_search",
    "mail_summarize", "mail_compose", "mail_send", "calendar_list", "calendar_create",
    "drive_search", "system_status", "web_search", "open_url",
}
SERVER_TOOLS = {
    "server_status", "service_status", "service_restart", "docker_list", "docker_restart",
    "server_shell",
}
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
- Chat only: steps=[]. Missing slot: steps=[] and ask one question in reply.
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
        if tool in ("whatsapp_prefill", "whatsapp_send") and not str(args.get("text") or "").strip() and topic:
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
    if re.search(r"\bplay\b", low) and ("phone" in low or "song" in low or "music" in low or "spotify" in low):
        steps.append({
            "device": "phone",
            "tool": "play_music",
            "args": {"query": _music_query(text)},
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
    wants_music = "spotify" in low or bool(re.search(r"\bplay\b", low) and re.search(r"\b(music|song|songs|spotify)\b", low))
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
        elif "on my phone" in low and tool in {"play_nth", "youtube_media", "play_video"}:
            tool = "play_music"
            if not args.get("query"):
                match = re.search(r"\bplay\s+(.+?)(?:\s+on\s+(?:my\s+)?phone)?$", text, re.I)
                args["query"] = match.group(1).strip(" .") if match else str(args.get("title") or "the song")
        if tool not in PHONE_TOOLS and tool not in LAPTOP_TOOLS and tool not in SERVER_TOOLS:
            continue
        step["tool"] = tool
        if tool in SERVER_TOOLS:
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


def exec_step(step: dict) -> dict:
    """Run one tool on the server, laptop, or phone queue."""
    tool = str(step.get("tool") or "")
    args = dict(step.get("args") or {})
    if tool == "server_shell" or tool in SERVER_TOOLS or step.get("device") == "server":
        result = server_call(tool, args)
        return {
            "ok": bool(result.get("ok")),
            "message": result.get("message") or "",
            "device": "server",
            "phone_step": None,
        }
    if step.get("device") == "phone" or tool in PHONE_TOOLS:
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
        if MARC_EMAIL and tool in ("mail_compose", "mail_send"):
            args = dict(step.get("args") or {})
            args["from"] = MARC_EMAIL
            step = {**step, "args": args}
        if step.get("device") == "server" or tool in SERVER_TOOLS:
            accepted_server.append(step)
        elif step.get("device") == "phone" or tool in PHONE_TOOLS:
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
    import re

    return bool(re.search(r"\b(?:and|then|also)\b", text, re.I))


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


def _remember_run(result: dict) -> None:
    global _LAST_RUN
    _LAST_RUN = {
        "spoken": result.get("spoken") or "",
        "machines": list(result.get("machines") or []),
        "steps_run": list(result.get("steps_run") or []),
        "at": int(time.time()),
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


def _memory_blank() -> dict:
    return {
        "profile": {"name": "Ranjith", "notes": []},
        "sessions": {},
        "apps": [],
        "front": "",
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
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            return


def _memory_notes() -> list:
    notes = _memory_load()["profile"].get("notes") or []
    return [str(note) for note in notes if str(note).strip()]


def _memory_add_note(note: str) -> str:
    note = (note or "").strip(" .")[:400]
    if not note:
        return "What should I remember?"
    data = _memory_load()
    notes = [item for item in (data["profile"].get("notes") or []) if str(item).lower() != note.lower()]
    notes.append(note)
    data["profile"]["notes"] = notes[-12:]
    _memory_save()
    return "I'll remember that."


def _memory_forget(needle: str) -> str:
    data = _memory_load()
    notes = list(data["profile"].get("notes") or [])
    if not notes:
        return "I don't have a note to drop."
    needle = (needle or "").strip(" .").lower()
    if not needle or needle in {"that", "it", "this"}:
        dropped = notes.pop()
        data["profile"]["notes"] = notes
        _memory_save()
        return f"Forgot: {dropped}"
    kept = [item for item in notes if needle not in str(item).lower()]
    if len(kept) == len(notes):
        return "I don't have a matching note."
    data["profile"]["notes"] = kept
    _memory_save()
    return "Forgot it."


def _memory_speak() -> str:
    data = _memory_load()
    name = data["profile"].get("name") or "Ranjith"
    notes = _memory_notes()
    if not notes:
        return f"You're {name}. I don't have extra notes yet."
    return f"You're {name}. " + " ".join(notes[:6])


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


def _assign_devices(steps: list, text: str, session: str, target: str = "auto") -> list:
    """Default to the session device. Named phrases and an explicit target win."""
    import re

    low = text.lower()
    dest = _session_target(text, session, target)
    prefer_phone = dest == "phone"
    routed = []
    for step in steps:
        args = dict(step.get("args") or {})
        tool = step.get("tool") or ""
        device = step.get("device")
        if prefer_phone and tool in {"youtube_media", "volume_media", "play_video", "play_nth"}:
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
        if tool in {"open_app", "close_app"}:
            name = str(args.get("name") or args.get("app") or "").strip()
            name = re.sub(
                r"\s+on\s+(?:my\s+|the\s+)?(?:phone|mobile|laptop|computer|pc)$",
                "",
                name,
                flags=re.I,
            ).strip(" .")
            if prefer_phone:
                device = "phone"
                args["name"] = name
            else:
                device = "laptop"
                args["app"] = name
                args.pop("name", None)
        elif tool in PHONE_TOOLS:
            device = "phone"
        elif tool in SERVER_TOOLS:
            device = "server"
        elif tool in LAPTOP_TOOLS:
            device = "laptop"
        elif dest == "server":
            device = "server"
        elif prefer_phone:
            device = "phone"
        else:
            device = "laptop"
        routed.append({**step, "device": device, "tool": tool, "args": args})
    return routed


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


def _finish_plan(text: str, session: str, plan: dict, target: str = "auto") -> dict:
    steps = _assign_devices(plan.get("steps") or [], text, session, target)
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
    remembered = re.match(r"^(?:please\s+)?remember(?:\s+that)?\s+(.+)$", text.strip(), re.I)
    if remembered:
        return _memory_add_note(remembered.group(1))
    forgot = re.match(r"^(?:please\s+)?forget(?:\s+that)?(?:\s+(.+))?$", text.strip(), re.I)
    if forgot:
        return _memory_forget(forgot.group(1) or "")
    if re.search(r"\b(who am i|what do you remember|what do you know about me)\b", low):
        return _memory_speak()
    return None


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

    said = re.search(r"\b(?:that|saying)\s+(.+)$", text, re.I)
    if said:
        body = said.group(1).strip(" .")
        who = re.search(
            r"\b(?:send|text|message|whatsapp|instagram)\s+(.+?)\s+(?:on\s+\w+\s+)?(?:that|saying)\b",
            text,
            re.I,
        )
        contact = who.group(1).strip() if who else ""
    else:
        chunk = re.search(r"\b(?:text|message)\s+(.+)$", text, re.I)
        if not chunk:
            return "", ""
        words = chunk.group(1).strip(" .").split()
        stop = {"hi", "hello", "hey", "this", "that", "please"}
        who_words = []
        index = 0
        while index < len(words) and index < 3 and words[index].lower().strip(".,") not in stop:
            who_words.append(words[index].strip(".,"))
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
    contact = re.sub(r"\s+on\s+(?:whatsapp|instagram|messages)$", "", contact, flags=re.I).strip()
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
    elif _multi_phrase(text):
        print("[marc-api] qwen-seq", flush=True)
        result = _finish_plan(text, session, plan_with_qwen(text, context=_context_line(session)), target)
    else:
        steps = _assign_devices(_obvious_steps(text, _fallback_steps(text)), text, session, target)
        if len(steps) == 1 and (steps[0].get("device") == "phone" or steps[0].get("tool") in PHONE_TOOLS):
            print("[marc-api] fast", [step.get("tool") for step in steps], flush=True)
            result = _finish_plan(text, session, {"reply": _brief_reply(steps, ""), "steps": steps}, target)
        else:
            print("[marc-api] qwen-seq", flush=True)
            result = _finish_plan(text, session, plan_with_qwen(text, context=_context_line(session)), target)
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
    _memory_load()
    quick = _instant(text)
    if quick:
        print("[marc-api] instant", flush=True)
        apps = list(_state(session)["apps"]) if session == "phone" else []
        return _empty_reply(quick, apps=apps)
    import re as _re
    if _re.search(r"\b(reboot|shutdown|halt|poweroff)\b", text, _re.I):
        return _empty_reply("I won't reboot or shut down.")
    if _re.search(r"rm\s+-rf\s+/", text, _re.I):
        return _empty_reply("I won't run that.")
    server = _direct_server(text, session, target)
    if server is not None:
        return server
    if session == "phone":
        _state(session)["last_utterance"] = text
    direct = _direct_command(text, session, target)
    if direct is not None:
        return direct
    if dest == "phone" and session == "phone" and not _wants_agent(text):
        return _handle_phone(text, session, target)
    if _multi_phrase(text) and not _wants_agent(text):
        print("[marc-api] qwen-seq", flush=True)
        return _finish_plan(text, session, plan_with_qwen(text, context=_context_line(session)), target)
    steps = _assign_devices(_obvious_steps(text, _fallback_steps(text)), text, session, target)
    if len(steps) > 1 and not _wants_agent(text):
        print("[marc-api] qwen-seq", flush=True)
        return _finish_plan(text, session, plan_with_qwen(text, context=_context_line(session)), target)
    if len(steps) == 1 and not _wants_agent(text):
        print("[marc-api] fast", [step.get("tool") for step in steps], flush=True)
        plan = {"reply": _brief_reply(steps, ""), "steps": steps}
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
            }
            _remember_run(result)
            return result
    scored = None if _wants_agent(text) else _classify_laya(text)
    if scored is not None and not _wants_agent(text, scored):
        laya_steps = _steps_from_laya(text, scored)
        if laya_steps:
            laya_steps = _assign_devices(laya_steps, text, session, target)
            print("[marc-api] laya-step", [step.get("tool") for step in laya_steps], flush=True)
            plan = {"reply": _brief_reply(laya_steps, ""), "steps": laya_steps}
            return gate_steps(text, plan, allow_retry=False)
    if _wants_agent(text, scored):
        looped = run_agent_loop(text, session, target)
        if looped is not None:
            return looped
    return _finish_plan(text, session, plan_with_qwen(text, context=_context_line(session)), target)


def handle_chat(body: dict) -> dict:
    import re

    text = (body.get("text") or "").strip()
    session = str(body.get("session_id") or "desk")
    if not text:
        return _empty_reply("I didn't catch that.")
    _memory_load()
    quick = _instant(text)
    if quick:
        print("[marc-api] instant", flush=True)
        return _empty_reply(quick)
    if re.search(ACTION_RE, text, re.I):
        return handle_utterance(body)
    history = _CHAT.setdefault(session or "desk", [])
    messages = [{"role": "system", "content": CHAT_SYSTEM}]
    ctx = _context_line(session)
    if ctx:
        messages.append({"role": "system", "content": ctx})
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": text})
    try:
        data = _post(
            OLLAMA_URL,
            {
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": messages,
                "keep_alive": "30m",
                "options": {"temperature": 0.4, "num_predict": 120, "num_ctx": 1024},
            },
            timeout=90,
        )
        reply = str(((data.get("message") or {}).get("content")) or "").strip()
    except Exception as exc:  # noqa: BLE001
        print("[marc-api] chat fail", exc, flush=True)
        return _empty_reply("I need a connection for that.")
    if not reply:
        reply = "I didn't catch that."
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    del history[:-8]
    _memory_save()
    print("[marc-api] chat", flush=True)
    return _empty_reply(reply)


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
        "laptop": _laptop_health(),
        "agent": dict(_LAST_RUN),
        "phone": {
            "apps": list(_state("phone").get("apps") or []),
            "front": str(_state("phone").get("front") or ""),
            "last_utterance": str(_state("phone").get("last_utterance") or ""),
        },
    }


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
            self._json(200, {"ok": True, "bind": BIND, "laptop": bool(LAPTOP_URL)})
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
                result = handle_utterance(data)
                self._json(200, _desk(str(data.get("session_id") or ""), result))
            elif path == "/chat":
                self._json(200, _desk(str(data.get("session_id") or ""), handle_chat(data)))
            elif path == "/confirm":
                self._json(200, handle_confirm(data))
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except urllib.error.URLError as exc:
            self._json(502, {"spoken": f"A model call failed: {exc.reason}", "confirm": None, "phone_steps": []})
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"spoken": str(exc), "confirm": None, "phone_steps": []})


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[marc-api] listening on 0.0.0.0:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
