"""App synonym helpers and recovery suggestions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from settings import settings

# Extra colloquial synonyms beyond config/apps.json
EXTRA_SYNONYMS: Dict[str, str] = {
    "browser": "chrome",
    "google": "chrome",
    "web": "chrome",
    "internet": "edge",
    "files": "explorer",
    "folders": "explorer",
    "music app": "spotify",
    "ide": "cursor",
    "editor": "cursor",
    "code editor": "vscode",
    "cmd": "terminal",
    "shell": "terminal",
    "powershell": "terminal",
    "mail": "gmail",
    "email": "gmail",
    "inbox": "gmail",
    "you tube": "youtube",
    "yt": "youtube",
    "webcam": "camera",
    "picture": "photos",
    "pictures": "photos",
    "photos app": "photos",
    "picture gallery": "photos",
    "snipping tool": "snip",
    "screen snip": "snip",
    "microsoft store": "store",
    "app store": "store",
    "alarms": "clock",
    "timer": "clock",
    "taskmgr": "task manager",
    "vlc player": "vlc",
    "media player": "vlc",
    "one drive": "onedrive",
    "whats app": "whatsapp",
    "whatsapp desktop": "whatsapp",
    "whatsup": "whatsapp",
    "what's up": "whatsapp",
    "whatssapp": "whatsapp",
    "wa": "whatsapp",
}


def _apps_from_config() -> Dict[str, str]:
    path = settings.apps_config
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, str] = {}
    for key, cfg in data.items():
        out[key.lower()] = key
        for alias in cfg.get("aliases") or []:
            out[str(alias).lower()] = key
    return out


_CONFIG_SYNONYMS = _apps_from_config()


def expand_app_query(name: str) -> str:
    key = name.strip().lower()
    if key in EXTRA_SYNONYMS:
        return EXTRA_SYNONYMS[key]
    if key in _CONFIG_SYNONYMS:
        return _CONFIG_SYNONYMS[key]
    return name


def all_app_names() -> List[str]:
    """Canonical keys + aliases for dataset generation."""
    names: List[str] = []
    path = settings.apps_config
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, cfg in data.items():
            names.append(key)
            names.extend(cfg.get("aliases") or [])
    return list(dict.fromkeys(names))


def recovery_message(failed_app: str, suggestion: Optional[str]) -> str:
    if suggestion:
        return f"I couldn't open '{failed_app}'. Open {suggestion} instead? Say yes."
    return (
        f"I couldn't open '{failed_app}'. "
        "Try a known app (chrome, edge, notepad, cursor) or add it to config/apps.json."
    )


def capability_blurb() -> str:
    try:
        from pathlib import Path

        man = Path(__file__).resolve().parents[1] / "config" / "skills_manifest.json"
        if man.exists():
            data = json.loads(man.read_text(encoding="utf-8"))
            skills = data.get("skills") or []
            titles = [s.get("title") or s.get("id") for s in skills if s]
            cannot = data.get("cannot") or []
            line = "I am Marc. I can: " + "; ".join(titles[:8]) + "."
            if cannot:
                line += " I won't: " + "; ".join(cannot[:3]) + "."
            return line
    except Exception:  # noqa: BLE001
        pass
    return (
        "I am Marc. Say things like: open Chrome, search YouTube for lo-fi, "
        "open browser and on YouTube search for samsung, summarize my email, "
        "message someone on WhatsApp, or what can you do."
    )
