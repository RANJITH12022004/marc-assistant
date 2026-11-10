#!/usr/bin/env python3
"""Public PIN-gated TV Lock API for the Vercel parent PWA. Funnel this port only."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ytlock_store import get, handle  # noqa: E402

BIND = os.environ.get("YTLOCK_BIND", "127.0.0.1")
PORT = int(os.environ.get("YTLOCK_PORT", "8093"))
DEVICE = ""
try:
    DEVICE = (Path(os.environ.get("USERPROFILE") or "") / ".marc" / "ytlock_device").read_text(encoding="utf-8").strip()
except OSError:
    DEVICE = os.environ.get("YTLOCK_DEVICE", "").strip()


def _cors_ok(origin: str) -> bool:
    origin = (origin or "").strip()
    if not origin:
        return False
    if origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
        return True
    return origin.startswith("https://") and origin.endswith(".vercel.app")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print("[ytlock-host]", self.address_string(), fmt % args, flush=True)

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin") or ""
        if _cors_ok(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Ytlock-Pin, X-Ytlock-Device")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _public(self) -> bool:
        header = (self.headers.get("X-Ytlock-Device") or "").strip()
        if DEVICE and header and header == DEVICE:
            return False
        host = (self.client_address[0] or "")
        if host in {"127.0.0.1", "::1"}:
            return False
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802
        origin = self.headers.get("Origin") or ""
        self.send_response(204 if _cors_ok(origin) else 404)
        if _cors_ok(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Ytlock-Pin, X-Ytlock-Device")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"ok": True})
            return
        if parsed.path not in {"/ytlock", "/api/lock"}:
            self._send(404, {"ok": False, "error": "not found"})
            return
        pin = (self.headers.get("X-Ytlock-Pin") or "").strip()
        if not pin:
            pin = (parse_qs(parsed.query).get("pin") or [""])[0]
        public = self._public()
        data = get(pin, public=public)
        self._send(200 if data.get("ok") else 401, data)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in {"/ytlock", "/api/lock"}:
            self._send(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"ok": False, "error": "invalid json"})
            return
        if not isinstance(body, dict):
            body = {}
        if not body.get("pin"):
            body["pin"] = (self.headers.get("X-Ytlock-Pin") or "").strip()
        data = handle(body, public=self._public())
        code = 200
        if not data.get("ok"):
            code = 401 if data.get("error") == "pin" else 400
        self._send(code, data)


def main() -> None:
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"[ytlock-host] listening on {BIND}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
