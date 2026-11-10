#!/usr/bin/env python3
"""Local Cursor agent against the office folder. Bind is loopback only."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BIND = os.environ.get("MARC_CURSOR_BIND", "127.0.0.1")
PORT = int(os.environ.get("MARC_CURSOR_PORT", "8093"))
MOUNT = os.environ.get("MARC_OFFICE_MOUNT", "/home/rox/office/work")
REMOTE_SSH = os.environ.get("MARC_OFFICE_SSH", "").strip()
REMOTE_CWD = os.environ.get("MARC_OFFICE_CWD", "").strip()
KEY_PATH = os.environ.get("MARC_OFFICE_KEY", "/home/rox/.ssh/id_ed25519")
MODEL = os.environ.get("MARC_CURSOR_MODEL", "composer-2.5")
MEMORY_PATH = os.environ.get("MARC_MEMORY_FILE", "/home/rox/marc/memory.json")
TRACE_PATH = os.environ.get("MARC_OFFICE_TRACE", "/home/rox/marc/office_trace.json")
MOUNT_SCRIPT = os.environ.get("MARC_OFFICE_MOUNT_SCRIPT", "/home/rox/marc/office_mount.sh")
UNREACHABLE = "Office machine isn't reachable."
SECRET_RE = re.compile(r"(cursor_|crsr_|sk-)[A-Za-z0-9_-]{8,}", re.I)

_lock = threading.Lock()
_state = "idle"
_agent_id = ""
_cwd = MOUNT
_hops: list[dict] = []
_summary = ""
_spoken = ""
_run = None
_thread: threading.Thread | None = None


def _scrub(text: str) -> str:
    return SECRET_RE.sub("…", str(text or ""))[:800]


def _remote() -> str:
    if REMOTE_SSH and REMOTE_CWD:
        return f"{REMOTE_SSH}:{REMOTE_CWD}"
    return REMOTE_SSH or REMOTE_CWD or MOUNT


def _write_json(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _persist_office(fields: dict) -> None:
    data = _read_json(MEMORY_PATH)
    office = data.get("office") if isinstance(data.get("office"), dict) else {}
    office.update({key: value for key, value in fields.items() if value is not None})
    data["office"] = office
    try:
        _write_json(MEMORY_PATH, data)
    except OSError:
        return


def _snapshot() -> dict:
    reachable = _mount_ok(False)
    return {
        "ok": True,
        "state": _state,
        "agent_id": _agent_id,
        "cwd": _cwd,
        "remote": _remote(),
        "reachable": reachable,
        "summary": _summary,
        "spoken": _spoken or ("" if reachable or _state == "running" else UNREACHABLE),
        "hops": list(_hops),
        "updated": int(time.time()),
    }


def _write_trace() -> None:
    try:
        _write_json(TRACE_PATH, _snapshot())
    except OSError:
        return


def _load_saved() -> None:
    global _agent_id, _cwd, _summary, _hops
    office = _read_json(MEMORY_PATH).get("office")
    if not isinstance(office, dict):
        office = {}
    trace = _read_json(TRACE_PATH)
    _agent_id = str(office.get("agent_id") or trace.get("agent_id") or "")[:160]
    _cwd = str(office.get("cwd") or trace.get("cwd") or MOUNT)[:400]
    _summary = str(office.get("last_summary") or trace.get("summary") or "")[:800]
    hops = trace.get("hops") if isinstance(trace.get("hops"), list) else []
    _hops = [hop for hop in hops if isinstance(hop, dict)][-80:]


def _hop(kind: str, text: str, coalesce: bool = False) -> None:
    global _hops
    line = {"kind": kind, "text": _scrub(text)[:400], "t": int(time.time())}
    if coalesce and _hops and _hops[-1].get("kind") == kind:
        prev = str(_hops[-1].get("text") or "")
        extra = str(line["text"] or "")
        if extra and extra not in prev:
            _hops[-1]["text"] = (prev + extra)[:400]
            _hops[-1]["t"] = line["t"]
        _write_trace()
        return
    _hops = (_hops + [line])[-80:]
    _write_trace()


def _ssh_ok() -> bool:
    if not REMOTE_SSH:
        return False
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    if os.path.isfile(KEY_PATH):
        cmd.extend(["-i", KEY_PATH])
    cmd.extend([REMOTE_SSH, "true"])
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=8, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _listdir_ok(path: str) -> bool:
    try:
        os.listdir(path)
        return True
    except OSError:
        return False


def _remount() -> None:
    if not os.path.isfile(MOUNT_SCRIPT):
        return
    try:
        subprocess.run(["bash", MOUNT_SCRIPT], capture_output=True, timeout=25, check=False)
    except (OSError, subprocess.SubprocessError):
        return


def _mount_ok(repair: bool) -> bool:
    if not REMOTE_SSH or not REMOTE_CWD:
        return False
    if not _ssh_ok():
        return False
    if os.path.ismount(MOUNT) and _listdir_ok(MOUNT):
        return True
    if not repair:
        return False
    _remount()
    return os.path.ismount(MOUNT) and _listdir_ok(MOUNT)


def _attr(obj, *names, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _nested_text(value, keys: tuple[str, ...]) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in keys:
            found = value.get(key)
            if found:
                return _nested_text(found, keys)
        for item in value.values():
            found = _nested_text(item, keys)
            if found:
                return found
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _nested_text(item, keys)
            if found:
                return found
        return ""
    for key in keys:
        if hasattr(value, key):
            found = _nested_text(getattr(value, key), keys)
            if found:
                return found
    return ""


def _tool_hop(name: str, args) -> tuple[str, str]:
    label = (name or "tool").strip() or "tool"
    path = _nested_text(args, ("path", "file", "target", "command", "cmd", "script"))
    low = label.lower()
    if any(token in low for token in ("write", "edit", "apply", "strreplace")):
        return "edit", path or label
    if any(token in low for token in ("read", "cat", "glob", "grep")):
        return "read", path or label
    if any(token in low for token in ("shell", "bash", "terminal")):
        return "shell", path or label
    if path:
        return "shell", f"{label} {path}"
    return "shell", label


def _message_hops(message) -> None:
    kind = str(_attr(message, "type", default="") or "")
    if kind == "thinking":
        _hop("think", str(_attr(message, "text", default="") or ""), coalesce=True)
        return
    if kind == "assistant":
        payload = _attr(message, "message", default=None)
        content = _attr(payload, "content", default=[]) or []
        bits = []
        for block in content if isinstance(content, list) else []:
            if str(_attr(block, "type", default="") or "") == "text":
                bits.append(str(_attr(block, "text", default="") or ""))
        text = "".join(bits).strip()
        if text:
            _hop("think", text, coalesce=True)
        return
    if kind != "tool_call":
        return
    status = str(_attr(message, "status", default="") or "")
    if status and status not in {"running", "started"}:
        return
    name = str(_attr(message, "name", default="") or "")
    kind_name, text = _tool_hop(name, _attr(message, "args", default=None))
    _hop(kind_name, text)


def _sdk():
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    try:
        from cursor_sdk import CursorAgentError
    except ImportError:
        CursorAgentError = Exception  # noqa: N806
    return Agent, AgentOptions, LocalAgentOptions, CursorAgentError


def _run_prompt(prompt: str, resume: bool, cwd: str) -> None:
    global _state, _agent_id, _cwd, _summary, _spoken, _run
    _cwd = cwd
    try:
        Agent, AgentOptions, LocalAgentOptions, CursorAgentError = _sdk()
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _state = "error"
            _spoken = "Office worker isn't ready."
            _hop("error", f"{_spoken} {_scrub(exc)}")
            _write_trace()
        return
    key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    if not key:
        with _lock:
            _state = "error"
            _spoken = "Office worker isn't ready."
            _hop("error", _spoken)
            _write_trace()
        return
    agent = None
    try:
        local = LocalAgentOptions(cwd=cwd)
        if resume and _agent_id and not str(_agent_id).startswith("bc-"):
            try:
                agent = Agent.resume(
                    _agent_id,
                    AgentOptions(api_key=key, model=MODEL, local=local),
                )
            except Exception as exc:  # noqa: BLE001
                with _lock:
                    _hop("think", f"Starting a new office thread. {_scrub(exc)}")
                agent = None
        if agent is None:
            agent = Agent.create(model=MODEL, api_key=key, local=local)
        agent_id = str(_attr(agent, "agent_id", "agentId", default="") or "")
        with _lock:
            _agent_id = agent_id
            _persist_office({
                "agent_id": agent_id,
                "cwd": cwd,
                "remote": _remote(),
            })
            _write_trace()
        run = agent.send(prompt)
        agent_id = str(_attr(agent, "agent_id", "agentId", default=agent_id) or agent_id)
        with _lock:
            _run = run
            _agent_id = agent_id
            _persist_office({
                "agent_id": agent_id,
                "cwd": cwd,
                "remote": _remote(),
            })
            _write_trace()
        for message in run.messages():
            with _lock:
                _message_hops(message)
        result = run.wait() if hasattr(run, "wait") else None
        status = str(_attr(result, "status", default=_attr(run, "status", default="finished")) or "finished")
        summary = str(_attr(result, "result", default="") or _attr(run, "result", default="") or "")
        with _lock:
            _run = None
            _summary = _scrub(summary)[:800]
            _spoken = _summary or ("Stopped." if status == "cancelled" else "Done.")
            _hop("done" if status != "error" else "error", _spoken or status)
            _state = "idle" if status in {"finished", "cancelled"} else "error"
            _persist_office({
                "agent_id": _agent_id,
                "cwd": cwd,
                "remote": _remote(),
                "last_summary": _summary,
            })
            _write_trace()
            try:
                import mind_store
                mind_store.after_office(prompt, _summary, new_task=False)
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        err = _scrub(exc) or "Office run failed."
        with _lock:
            _run = None
            _state = "error"
            _spoken = err
            _hop("error", err)
            _write_trace()
        traceback.print_exc()
    finally:
        closer = getattr(agent, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass


def start_run(prompt: str, resume: bool, cwd: str | None) -> dict:
    global _state, _spoken, _thread, _hops, _summary, _agent_id
    text = (prompt or "").strip()
    if not text:
        return {"ok": False, "spoken": "What should I do in the office folder?", "state": _state}
    target = (cwd or "").strip() or MOUNT
    with _lock:
        if _state == "running":
            return {**_snapshot(), "ok": False, "spoken": "Office is already working.", "state": "running"}
        if not _mount_ok(True):
            _spoken = UNREACHABLE
            _write_trace()
            return {**_snapshot(), "ok": False, "spoken": UNREACHABLE, "reachable": False}
        if not resume:
            _agent_id = ""
            _hops = []
            _summary = ""
        _state = "running"
        _spoken = "Working on the office folder."
        _cwd = target
        _hop("think", "Opening the office folder.")
        _thread = threading.Thread(
            target=_run_prompt,
            args=(text, resume, target),
            daemon=True,
            name="marc-office-run",
        )
        _thread.start()
        snap = _snapshot()
    snap["ok"] = True
    snap["spoken"] = "Working on the office folder."
    return snap


def cancel_run() -> dict:
    global _state, _spoken, _run
    with _lock:
        run = _run
        if run is None:
            _state = "idle"
            _spoken = "Nothing is running."
            _write_trace()
            return {**_snapshot(), "ok": True, "spoken": _spoken}
        try:
            if hasattr(run, "supports") and not run.supports("cancel"):
                raise RuntimeError("cancel unsupported")
            run.cancel()
        except Exception as exc:  # noqa: BLE001
            _spoken = _scrub(exc) or "Could not stop the office run."
            _write_trace()
            return {**_snapshot(), "ok": False, "spoken": _spoken}
        _spoken = "Stopping."
        _write_trace()
        return {**_snapshot(), "ok": True, "spoken": _spoken}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print("[marc-cursor]", self.address_string(), fmt % args, flush=True)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/status":
            with _lock:
                self._json(200, _snapshot())
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if path == "/run":
            prompt = str(data.get("prompt") or data.get("text") or "")
            resume = bool(data.get("resume", True))
            cwd = data.get("cwd")
            self._json(200, start_run(prompt, resume, str(cwd) if cwd else None))
            return
        if path == "/cancel":
            self._json(200, cancel_run())
            return
        self._json(404, {"ok": False, "error": "not found"})


def main() -> None:
    _load_saved()
    _mount_ok(True)
    with _lock:
        _write_trace()
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"[marc-cursor] listening on {BIND}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
