"""Append-only JSONL audit + misroute logging for Marc."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from settings import settings


def audit(event: str, payload: Dict[str, Any]) -> None:
    path = settings.audit_log
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **payload,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def log_turn(
    transcript: str,
    *,
    intent: str = "",
    confidence: float = 0.0,
    source: str = "",
    awaiting: str = "",
    pending: bool = False,
    steps: Optional[list] = None,
    tool_ok: bool = True,
) -> None:
    """Structured per-turn log for debugging live sessions."""
    path = Path(settings.root) / "data" / "logs" / "turns.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "transcript": transcript,
        "intent": intent,
        "confidence": confidence,
        "source": source,
        "awaiting": awaiting,
        "pending": pending,
        "steps": [
            {"tool": s.get("tool"), "args": s.get("args")} for s in (steps or [])[:8]
        ],
        "tool_ok": tool_ok,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def log_misroute(
    transcript: str,
    intent: str,
    source: str,
    *,
    confidence: float = 0.0,
    note: str = "",
) -> None:
    """Capture unclear / failed routes for the next dataset cycle."""
    path = Path(settings.root) / "data" / "logs" / "misroutes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "transcript": transcript,
        "intent": intent,
        "source": source,
        "confidence": confidence,
        "note": note,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
