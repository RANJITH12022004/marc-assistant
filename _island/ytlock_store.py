"""TV Lock state on this laptop. PIN-gated; custom lock-after / unlock-after timers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time

def _marc_dir() -> Path:
    if os.environ.get("YTLOCK_DIR"):
        return Path(os.environ["YTLOCK_DIR"])
    if os.name != "nt" and Path("/home/rox/marc").is_dir():
        return Path("/home/rox/marc")
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    return home / ".marc"


MARC = _marc_dir()
STATE_PATH = Path(os.environ.get("YTLOCK_FILE") or (MARC / "ytlock.json"))
PIN_PATH = Path(os.environ.get("YTLOCK_PIN_FILE") or (MARC / "ytlock_pin"))
MAX_MINUTES = 24 * 60
_lock = threading.Lock()


def _blank() -> dict:
    return {
        "locked": False,
        "until": 0,
        "then": "",
        "updated": int(time.time()),
        "tv": "unknown",
        "schedule": {"enabled": False, "lock_at": "", "unlock_at": ""},
        "sched_mark": "",
    }


def _hm_ok(value: str) -> bool:
    parts = str(value or "").strip().split(":")
    if len(parts) != 2:
        return False
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _norm_hm(value: str) -> str:
    text = str(value or "").strip()
    if not _hm_ok(text):
        return ""
    hour, minute = text.split(":")
    return f"{int(hour):02d}:{int(minute):02d}"


def _schedule_of(loaded: dict) -> dict:
    raw = loaded.get("schedule") if isinstance(loaded, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": bool(raw.get("enabled")),
        "lock_at": _norm_hm(raw.get("lock_at") or ""),
        "unlock_at": _norm_hm(raw.get("unlock_at") or ""),
    }


def _apply_schedule(data: dict) -> bool:
    sched = _schedule_of(data)
    if not sched["enabled"]:
        return False
    until = int(data.get("until") or 0)
    if until and time.time() < until:
        return False
    now_hm = time.strftime("%H:%M")
    today = time.strftime("%Y-%m-%d")
    events = []
    if sched["lock_at"]:
        events.append((sched["lock_at"], "lock"))
    if sched["unlock_at"]:
        events.append((sched["unlock_at"], "unlock"))
    if not events:
        return False
    past = [item for item in events if item[0] <= now_hm]
    chosen = max(past, key=lambda item: item[0]) if past else max(events, key=lambda item: item[0])
    mark = f"{today}{chosen[1][0]}{chosen[0]}"
    if str(data.get("sched_mark") or "") == mark:
        return False
    data["locked"] = chosen[1] == "lock"
    data["until"] = 0
    data["then"] = ""
    data["sched_mark"] = mark
    data["updated"] = int(time.time())
    return True


def _minutes(data: dict | None) -> int:
    try:
        minutes = int((data or {}).get("minutes") or 0)
    except (TypeError, ValueError):
        return 0
    unit = str((data or {}).get("unit") or "min").strip().lower()
    if unit in {"h", "hr", "hour", "hours"}:
        minutes *= 60
    if minutes < 1:
        return 0
    return min(minutes, MAX_MINUTES)


def _span(remain: int) -> str:
    minutes = max(1, (int(remain) + 59) // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"


def load() -> dict:
    data = _blank()
    try:
        loaded = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        loaded = {}
    if not isinstance(loaded, dict):
        return data
    data["locked"] = bool(loaded.get("locked"))
    try:
        data["until"] = int(loaded.get("until") or 0)
    except (TypeError, ValueError):
        data["until"] = 0
    then = str(loaded.get("then") or "").strip().lower()
    data["then"] = then if then in {"lock", "unlock"} else ""
    data["tv"] = str(loaded.get("tv") or "unknown")[:40]
    data["schedule"] = _schedule_of(loaded)
    data["sched_mark"] = str(loaded.get("sched_mark") or "")
    try:
        data["updated"] = int(loaded.get("updated") or 0)
    except (TypeError, ValueError):
        data["updated"] = int(time.time())
    return data


def save(data: dict) -> None:
    MARC.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_PATH)


def pin_hash() -> str:
    try:
        return PIN_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def digest(pin: str) -> str:
    return hashlib.sha256(("ytlock:" + str(pin or "")).encode()).hexdigest()


def pin_ok(pin: str) -> bool:
    stored = pin_hash()
    got = str(pin or "").strip()
    if not stored or not got:
        return False
    if len(stored) == 64 and all(ch in "0123456789abcdef" for ch in stored.lower()):
        return secrets.compare_digest(stored, digest(got))
    return secrets.compare_digest(stored, got)


def expire(data: dict) -> dict:
    changed = False
    until = int(data.get("until") or 0)
    if until and time.time() >= until:
        then = str(data.get("then") or "lock").strip().lower()
        data["locked"] = then != "unlock"
        data["until"] = 0
        data["then"] = ""
        data["updated"] = int(time.time())
        changed = True
    if _apply_schedule(data):
        changed = True
    if changed:
        save(data)
    return data


def public_view() -> dict:
    with _lock:
        state = expire(load())
    until = int(state.get("until") or 0)
    remain = max(0, until - int(time.time())) if until else 0
    locked = bool(state.get("locked"))
    then = str(state.get("then") or "").strip().lower()
    if remain and then == "unlock":
        label = f"Locked for {_span(remain)}, then unlocks"
    elif remain:
        label = f"On for {_span(remain)}, then locks"
    elif locked:
        label = "YouTube is locked on the TV"
    else:
        label = "YouTube is unlocked"
    return {
        "ok": True,
        "locked": locked,
        "until": until,
        "then": then,
        "remain_s": remain,
        "tv": state.get("tv") or "unknown",
        "setup": not bool(pin_hash()),
        "label": label,
        "schedule": _schedule_of(state),
        "helper": bool(state.get("tv") and state.get("tv") != "unknown"),
    }


def handle(data: dict, *, public: bool) -> dict:
    del public
    pin = str((data or {}).get("pin") or "")
    action = str((data or {}).get("action") or "").strip().lower()
    stored = pin_hash()
    if action == "setup":
        if stored:
            return {"ok": False, "error": "already set"}
        if len(pin) < 4:
            return {"ok": False, "error": "pin too short"}
        MARC.mkdir(parents=True, exist_ok=True)
        PIN_PATH.write_text(digest(pin), encoding="utf-8")
        try:
            os.chmod(PIN_PATH, 0o600)
        except OSError:
            pass
        return {**public_view(), "setup": False}
    if action in {"timer", "lock_after", "unlock_after"} and _minutes(data) < 1:
        return {"ok": False, "error": "minutes"}
    with _lock:
        state = expire(load())
        changed = True
        if action == "lock":
            state["locked"] = True
            state["until"] = 0
            state["then"] = ""
        elif action == "unlock":
            state["locked"] = False
            state["until"] = 0
            state["then"] = ""
        elif action in {"timer", "lock_after"}:
            minutes = _minutes(data)
            state["locked"] = False
            state["until"] = int(time.time()) + minutes * 60
            state["then"] = "lock"
        elif action == "unlock_after":
            minutes = _minutes(data)
            state["locked"] = True
            state["until"] = int(time.time()) + minutes * 60
            state["then"] = "unlock"
        elif action == "tv":
            state["tv"] = str((data or {}).get("tv") or state.get("tv") or "unknown")[:40]
        elif action == "schedule":
            lock_at = _norm_hm((data or {}).get("lock_at") or "")
            unlock_at = _norm_hm((data or {}).get("unlock_at") or "")
            enabled = bool((data or {}).get("enabled"))
            if enabled and not lock_at and not unlock_at:
                return {"ok": False, "error": "schedule"}
            state["schedule"] = {"enabled": enabled, "lock_at": lock_at, "unlock_at": unlock_at}
            state["sched_mark"] = ""
        else:
            changed = False
        if changed:
            state["updated"] = int(time.time())
            save(state)
    return public_view()


def get(pin: str, *, public: bool) -> dict:
    del pin, public
    return public_view()
