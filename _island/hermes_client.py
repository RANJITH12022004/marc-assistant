"""Hermes agent adapter for Marc leftovers.

Hermes is the agent. Meta AI and Needle are LLMs it may use.
Calls live marc-muse on loopback (:8096) first, then Meta AI tool plans,
then returns empty so marc_api can fall back to Needle LLM / heuristics.

Never executes phone/laptop/server tools itself — only emits
``{reply, steps:[{device, tool, args}]}``.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

MUSE_URL = os.environ.get("MARC_MUSE_URL", "http://127.0.0.1:8096").rstrip("/")
HERMES_URL = os.environ.get("HERMES_URL", "http://127.0.0.1:8732").rstrip("/")
TOKEN_PATH = os.environ.get("MARC_TOKEN_FILE", "/home/rox/marc/secret")
MUSE_ENV_PATH = os.environ.get("MARC_MUSE_ENV", "/home/rox/marc-muse.env")
TIMEOUT = float(os.environ.get("HERMES_PLAN_TIMEOUT", "90"))

PLAN_INSTRUCTIONS = """You are Hermes, Marc's controlling agent for phone, laptop, and server.
Return ONLY JSON:
{"reply":"short spoken line","steps":[{"device":"phone|laptop|server","tool":"tool_name","args":{}}]}
Continuous commands: split on and/then/after that/also/commas into ordered steps. Keep every clause — never drop the second or third action.
Prefer phone for open/type/youtube/google/whatsapp/music. Prefer laptop for mail/calendar/drive/windows apps/Notepad. Prefer server for CPU/temp/services/docker.
Device phrases override per clause: "on my phone", "on my laptop/computer/PC", "on the server/linux".
If the user opens WhatsApp and texts someone on the phone, emit whatsapp_send with args.contact = spoken name and args.text = message body. Never use type_into for WhatsApp messaging — that types into search, not the chat.
If the user opens WhatsApp on the laptop and texts someone, keep messaging on the laptop (open_app + type_text). Never bounce that send to the phone unless they said on my phone.
For whatsapp_send / sms_send put the spoken name in args.contact exactly (e.g. Ranjith) and the rest of the sentence in args.text. Default args.send to false unless they said send. Do not invent other people.
If Brain/context mentions prior prefs or unfinished work, use it. If the user named an action or device, steps MUST NOT be empty.
reply is one short spoken line. Never invent reboot, shutdown, sudo, or rm -rf.
Empty steps only for pure chat with nothing to do.
"""


def _token() -> str:
    """Bearer for marc-muse. Prefer a Muse-specific token; never log it."""
    for env_key in ("MARC_MUSE_TOKEN", "MUSE_TOKEN"):
        raw = (os.environ.get(env_key) or "").strip()
        if raw:
            return raw
    for env_file in ("MARC_MUSE_TOKEN_FILE", "MUSE_TOKEN_FILE"):
        path = (os.environ.get(env_file) or "").strip()
        if path:
            try:
                return open(path, encoding="utf-8").read().strip()
            except OSError:
                pass
    # Read MARC_TOKEN from marc-muse.env (different from marc-api secret).
    try:
        for line in open(MUSE_ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if line.startswith("MARC_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    raw = (os.environ.get("MARC_TOKEN") or "").strip()
    if raw:
        return raw
    try:
        return open(TOKEN_PATH, encoding="utf-8").read().strip()
    except OSError:
        return ""


def _post(url: str, payload: dict, timeout: float = TIMEOUT) -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    parsed = json.loads(body) if body.strip() else {}
    return parsed if isinstance(parsed, dict) else {}


def _get(url: str, timeout: float = 4.0) -> dict | None:
    headers = {}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body.strip() else {}
        return parsed if isinstance(parsed, dict) else {"ok": True}
    except Exception:
        return None


def health() -> dict[str, Any]:
    muse = _get(MUSE_URL + "/health")
    hermes = _get(HERMES_URL + "/health")
    return {
        "ok": bool(muse and muse.get("ok")),
        "muse_url": MUSE_URL,
        "muse": muse or {"ok": False},
        "hermes_url": HERMES_URL,
        "hermes_runner": hermes or {"ok": False},
    }


def _normalize_plan(payload: dict) -> dict:
    """Map marc-muse {reply, plan:[...]} or {reply, steps:[...]} to Marc steps."""
    reply = str(payload.get("reply") or payload.get("spoken") or "").strip()
    rows = payload.get("steps")
    if not isinstance(rows, list):
        rows = payload.get("plan")
    if not isinstance(rows, list):
        rows = []
    steps: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tool = str(row.get("tool") or "").strip()
        if not tool:
            continue
        device = str(row.get("device") or "phone").strip().lower() or "phone"
        args = dict(row.get("args") if isinstance(row.get("args"), dict) else {})
        # Muse often emits to= for WhatsApp — normalize so phone lift always sees contact.
        if tool in {"whatsapp_send", "whatsapp_prefill", "sms_send", "instagram_send"}:
            contact = str(args.get("contact") or args.get("phone") or args.get("to") or "").strip()
            if contact:
                args["contact"] = contact
            if "send" not in args:
                args["send"] = False
        step = {"device": device, "tool": tool, "args": args}
        if row.get("confirm"):
            step["confirm"] = True
        steps.append(step)
    if not reply:
        reply = "On it." if steps else "Got it."
    return {"reply": reply, "steps": steps, "source": payload.get("source") or "hermes"}


def plan_via_muse(text: str, note: str = "", context: str = "", session: str = "") -> dict | None:
    try:
        payload = _post(
            MUSE_URL + "/plan",
            {
                "text": text,
                "note": note,
                "context": context or "marc-api",
                "session_id": session or "phone",
                "target": "auto",
            },
            timeout=TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        print("[hermes] muse fail", type(exc).__name__, flush=True)
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("ignored"):
        return {"reply": "", "steps": [], "source": "muse"}
    out = _normalize_plan(payload)
    out["source"] = "muse"
    return out


def _parse_json_object(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def plan_via_meta(text: str, note: str = "", context: str = "", session: str = "") -> dict | None:
    try:
        import muse_client
    except Exception:
        return None
    key = muse_client.api_key()
    if not key:
        return None
    prompt = text.strip()
    if note:
        prompt = f"{prompt}\n{note}"
    if context:
        prompt = f"Context: {context}\nUser: {prompt}"
    if session:
        prompt = f"Session: {session}\n{prompt}"
    multi = bool(re.search(r"\b(then|after that|and then|;)\b", text, re.I)) or len(text) > 80
    model = muse_client.WONDER if multi else muse_client.SPARK
    try:
        result = muse_client.complete(
            key,
            model,
            PLAN_INSTRUCTIONS,
            [muse_client.user_message(prompt)],
            effort="high" if multi else "low",
            timeout=TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        print("[hermes] meta fail", type(exc).__name__, flush=True)
        return None
    parsed = _parse_json_object(str(result.get("text") or ""))
    if parsed is None and result.get("tool_calls"):
        steps = []
        for call in result["tool_calls"]:
            name = str(call.get("name") or "")
            try:
                args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            device = str(args.pop("device", "") or "phone")
            steps.append({"device": device, "tool": name, "args": args})
        return {"reply": "On it.", "steps": steps, "source": "meta"}
    if parsed is None:
        return None
    out = _normalize_plan(parsed)
    out["source"] = "meta"
    return out


def plan_command(text: str, note: str = "", context: str = "", session: str = "") -> dict:
    """Hermes-owned leftover plan. May return empty steps; caller falls back."""
    for fn in (plan_via_muse, plan_via_meta):
        try:
            planned = fn(text, note=note, context=context, session=session)
        except Exception as exc:  # noqa: BLE001
            print("[hermes]", fn.__name__, type(exc).__name__, flush=True)
            planned = None
        if planned is None:
            continue
        # Muse/Meta said nothing useful — let caller try Needle LLM.
        if not planned.get("steps") and not (planned.get("reply") or "").strip():
            continue
        print("[hermes]", planned.get("source"), [s.get("tool") for s in planned.get("steps") or []], flush=True)
        return planned
    return {"reply": "", "steps": [], "source": "hermes-miss"}
