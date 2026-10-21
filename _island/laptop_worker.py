#!/usr/bin/env python3
"""Windows tool worker. No model weights. Run this from the mark-laptop repo:

    set MARC_TOKEN=<same secret as the Pi>
    set MARC_BIND=<this PC's Tailscale IPv4>
    python laptop_worker.py

Copy this file into the mark-laptop directory, or set MARC_LAPTOP_ROOT.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("MARC_LAPTOP_ROOT") or Path(__file__).resolve().parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BIND = os.environ.get("MARC_BIND", "127.0.0.1")
PORT = int(os.environ.get("MARC_WORKER_PORT", "8092"))
TOKEN = os.environ.get("MARC_TOKEN", "")

OWNED = {
    "open_app",
    "close_app",
    "focus_window",
    "web_search",
    "type_text",
    "hotkey",
    "file_find",
    "system_status",
    "volume_media",
    "settings",
}


def _slots_to_call(intent: str, slots: dict) -> tuple[str, dict]:
    if intent == "open_app":
        return "open_app", {"app": slots.get("app") or ""}
    if intent == "close_app":
        return "close_app", {"app": slots.get("app") or ""}
    if intent == "focus_window":
        return "focus_window", {"app": slots.get("app") or ""}
    if intent == "web_search":
        engine = slots.get("engine") or "google"
        query = slots.get("query") or ""
        if engine == "youtube":
            return "youtube_search", {"query": query}
        return "google_search", {"query": query}
    if intent == "type_text":
        return "type_text", {"text": slots.get("text") or ""}
    if intent == "hotkey":
        return "hotkey", {"action": slots.get("action") or ""}
    if intent == "file_find":
        return "file_find", {"query": slots.get("query") or ""}
    if intent == "system_status":
        return "system_status", {"metric": slots.get("metric") or "time"}
    if intent == "volume_media":
        return "volume_media", {"action": slots.get("action") or "play", "level": slots.get("level")}
    if intent == "settings":
        return "settings", {"page": slots.get("page") or "home"}
    return intent, {}


class Worker:
    def __init__(self) -> None:
        from orchestrator.agent import MarcOrchestrator

        self.orch = MarcOrchestrator(preload_laya=False, confirm_fn=lambda _msg: False, speak_fn=lambda _msg: None)

    def rule(self, text: str) -> dict:
        from laya_router.rules import extract_slots, rule_classify

        intent, conf = rule_classify(text)
        if conf < 0.85 or intent not in OWNED:
            return {"owned": False, "intent": intent, "confidence": conf}
        slots = extract_slots(text, intent)
        tool, args = _slots_to_call(intent, slots)
        result = self.orch._exec_tool(tool, args, confirmed=True)
        return {
            "owned": True,
            "intent": intent,
            "confidence": conf,
            "spoken": result.message,
            "ok": result.ok,
            "message": result.message,
        }

    def tool(self, tool: str, args: dict) -> dict:
        result = self.orch._exec_tool(tool, args or {}, confirmed=True)
        return result.to_dict()


WORKER: Worker | None = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print("[laptop-worker]", self.address_string(), fmt % args, flush=True)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not TOKEN:
            return True
        return (self.headers.get("Authorization") or "") == f"Bearer {TOKEN}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/health":
            self._json(200, {"ok": True, "models": False})
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
        assert WORKER is not None
        try:
            if path == "/rule":
                self._json(200, WORKER.rule(data.get("text") or ""))
            elif path == "/tool":
                self._json(200, WORKER.tool(data.get("tool") or "", data.get("args") or {}))
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "owned": False, "message": str(exc)})


def main() -> None:
    global WORKER
    WORKER = Worker()
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"[laptop-worker] listening on {BIND}:{PORT} root={ROOT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
