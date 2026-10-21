"""Reminders and alarms for Marc (persisted JSON + due checks)."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.os_tools import ToolResult

ROOT = Path(__file__).resolve().parents[1]
REMINDERS_PATH = ROOT / "data" / "reminders.json"


def _load() -> List[Dict[str, Any]]:
    if not REMINDERS_PATH.exists():
        return []
    try:
        data = json.loads(REMINDERS_PATH.read_text(encoding="utf-8"))
        return list(data.get("items") or [])
    except Exception:  # noqa: BLE001
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    REMINDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    REMINDERS_PATH.write_text(
        json.dumps({"items": items}, indent=2),
        encoding="utf-8",
    )


def parse_when(text: str = "", when: str = "", minutes: Any = None) -> Optional[datetime]:
    """Parse relative/absolute times into a local datetime."""
    now = datetime.now()
    if minutes is not None:
        try:
            return now + timedelta(minutes=float(minutes))
        except Exception:  # noqa: BLE001
            pass
    blob = f"{when or ''} {text or ''}".strip().lower()
    if not blob:
        return None

    m = re.search(r"\bin\s+(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b", blob)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("sec"):
            return now + timedelta(seconds=n)
        if unit.startswith("min"):
            return now + timedelta(minutes=n)
        return now + timedelta(hours=n)

    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", blob)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = (m.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        return due

    m = re.search(r"\b(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b", blob)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("sec"):
            return now + timedelta(seconds=n)
        if unit.startswith("min"):
            return now + timedelta(minutes=n)
        return now + timedelta(hours=n)

    return now + timedelta(minutes=10)


def _message_from(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(
        r"^\s*(?:please\s+)?(?:remind\s+me(?:\s+to)?|set\s+(?:a\s+)?(?:reminder|alarm)|alarm)\s*",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"\bin\s+\d+\s*\w+\b", "", t, flags=re.I)
    t = re.sub(r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", "", t, flags=re.I)
    return t.strip(" .,") or "Reminder"


def set_reminder(
    text: str = "",
    when: str = "",
    minutes: Any = None,
) -> ToolResult:
    due = parse_when(text=text, when=when, minutes=minutes)
    if due is None:
        return ToolResult(False, "When should I remind you?")
    msg = _message_from(text) if text else (when or "Reminder")
    if when and not text:
        msg = _message_from(when)
    item = {
        "id": str(uuid.uuid4())[:8],
        "message": msg,
        "due": due.isoformat(timespec="seconds"),
        "fired": False,
    }
    items = _load()
    items.append(item)
    _save(items)
    human = due.strftime("%I:%M %p").lstrip("0")
    return ToolResult(
        True,
        f"Reminder set for {human}: {msg}",
        {"reminder": item},
    )


def list_reminders() -> ToolResult:
    items = [i for i in _load() if not i.get("fired")]
    if not items:
        return ToolResult(True, "No upcoming reminders.", {"items": []})
    lines = [f"- {i.get('due')}: {i.get('message')}" for i in items[:8]]
    return ToolResult(True, "Reminders:\n" + "\n".join(lines), {"items": items})


def due_reminders(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Return due unfired reminders and mark them fired."""
    now = now or datetime.now()
    items = _load()
    due: List[Dict[str, Any]] = []
    changed = False
    for item in items:
        if item.get("fired"):
            continue
        try:
            due_at = datetime.fromisoformat(item["due"])
        except Exception:  # noqa: BLE001
            continue
        if due_at <= now:
            item["fired"] = True
            due.append(dict(item))
            changed = True
    if changed:
        _save(items)
    return due


def windows_toast(title: str, message: str) -> None:
    """Best-effort Windows notification."""
    try:
        from win10toast import ToastNotifier

        ToastNotifier().show_toast(title, message, duration=5, threaded=True)
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        import subprocess

        # PowerShell balloon via BurntToast-free simple message box alternative
        ps = (
            f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; '
            f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            f"[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            f"$text = $template.GetElementsByTagName('text'); "
            f"$text.Item(0).AppendChild($template.CreateTextNode('{title.replace(chr(39), '')}')) | Out-Null; "
            f"$text.Item(1).AppendChild($template.CreateTextNode('{message[:80].replace(chr(39), '')}')) | Out-Null; "
            f"$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
            f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Marc').Show($toast)"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        print(f"[marc] reminder: {title} — {message}", flush=True)
