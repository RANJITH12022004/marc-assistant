#!/usr/bin/env python3
"""Serves the Marc desk on this machine and keeps the bearer token off the page."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
PAGE = (HERE / "desk.html").read_bytes()
TOKEN_PATH = os.environ.get("MARC_TOKEN_FILE", "/home/rox/marc/secret")
GATE_PATH = os.environ.get("MARC_DESK_GATE_FILE", "/home/rox/marc/desk_gate")
API = os.environ.get("MARC_API", "http://127.0.0.1:8090").rstrip("/")
BIND = os.environ.get("MARC_DESK_BIND", "127.0.0.1")
PORT = int(os.environ.get("MARC_DESK_PORT", "8095"))


def _gate() -> str:
    try:
        return Path(GATE_PATH).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _allowed(header: str) -> bool:
    expected = _gate()
    if not expected:
        return False
    for part in (header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == "marc_desk" and value == expected:
            return True
    return False


def _token() -> str:
    try:
        return Path(TOKEN_PATH).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _proxy(path: str, method: str, body: bytes | None) -> tuple[int, bytes]:
    token = _token()
    if not token:
        return 500, json.dumps({"ok": False, "error": "missing token"}).encode()
    req = urllib.request.Request(
        API + path,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=100) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 502, json.dumps({"ok": False, "error": str(exc.reason)}).encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        line = fmt % args
        if "/g/" in line:
            line = line.split("/g/", 1)[0] + "/g/…"
        print("[marc-desk]", self.address_string(), line, flush=True)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        expected = _gate()
        if expected and path == f"/g/{expected}":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"marc_desk={expected}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=31536000",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/phone-inbox":
            token = _token()
            header = self.headers.get("Authorization") or ""
            if not token or header != f"Bearer {token}":
                self._send(404, b'{"ok":false}', "application/json")
                return
            code, body = _proxy("/status?take=1", "GET", None)
            self._send(code, body, "application/json")
            return
        if path == "/api/status":
            token = _token()
            header = self.headers.get("Authorization") or ""
            bearer = bool(token) and header == f"Bearer {token}"
            if not bearer and not _allowed(self.headers.get("Cookie") or ""):
                self._send(404, b'{"ok":false}', "application/json")
                return
            code, body = _proxy("/status", "GET", None)
            self._send(code, body, "application/json")
            return
        if not _allowed(self.headers.get("Cookie") or ""):
            self._send(404, b'{"ok":false}', "application/json")
            return
        if path in {
            "/",
            "/index.html",
            "/chat",
            "/agent",
            "/laptop",
            "/phone",
            "/server",
            "/disks",
            "/system",
            "/settings",
        }:
            self._send(200, PAGE, "text/html; charset=utf-8")
            return
        self._send(404, b'{"ok":false}', "application/json")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if path in {"/api/phone-utterance", "/api/phone-chat"}:
            token = _token()
            header = self.headers.get("Authorization") or ""
            if not token or header != f"Bearer {token}":
                self._send(404, b'{"ok":false}', "application/json")
                return
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data["session_id"] = "phone"
            dest = "/utterance" if path.endswith("utterance") else "/chat"
            code, body = _proxy(dest, "POST", json.dumps(data).encode())
            self._send(code, body, "application/json")
            return
        if not _allowed(self.headers.get("Cookie") or ""):
            self._send(404, b'{"ok":false}', "application/json")
            return
        if path == "/api/utterance":
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data["session_id"] = "desk"
            raw = json.dumps(data).encode()
            code, body = _proxy("/utterance", "POST", raw)
            self._send(code, body, "application/json")
            return
        if path == "/api/chat":
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data["session_id"] = "desk"
            raw = json.dumps(data).encode()
            code, body = _proxy("/chat", "POST", raw)
            self._send(code, body, "application/json")
            return
        if path == "/api/confirm":
            code, body = _proxy("/confirm", "POST", raw)
            self._send(code, body, "application/json")
            return
        self._send(404, b'{"ok":false}', "application/json")


def main() -> None:
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"[marc-desk] listening on {BIND}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
