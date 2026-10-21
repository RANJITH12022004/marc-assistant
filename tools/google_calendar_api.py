"""Google Calendar API tools for Marc."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from tools.os_tools import ToolResult
from tools.google_oauth import auth_status, build_service


def _local_tz():
    return datetime.now().astimezone().tzinfo or timezone.utc


def list_events(query: str = "", max_results: int = 5, days: int = 7) -> ToolResult:
    """List upcoming calendar events (optionally filtered by text)."""
    if auth_status() != "authorized":
        return ToolResult(
            False,
            "Authorize Google first: python main.py google-auth",
            {"need_auth": True},
        )
    svc = build_service("calendar", "v3")
    if svc is None:
        return ToolResult(
            False,
            "Calendar API unavailable — run: python main.py google-auth",
            {"need_auth": True},
        )
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=max(1, min(days, 30)))
    try:
        kwargs: Dict[str, Any] = {
            "calendarId": "primary",
            "timeMin": now.isoformat(),
            "timeMax": end.isoformat(),
            "maxResults": max(1, min(max_results, 15)),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        q = (query or "").strip()
        if q:
            kwargs["q"] = q
        resp = svc.events().list(**kwargs).execute()
        items = resp.get("items") or []
        results: List[Dict[str, str]] = []
        for ev in items:
            start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date") or ""
            results.append(
                {
                    "id": ev.get("id") or "",
                    "title": ev.get("summary") or "(no title)",
                    "start": start,
                    "location": ev.get("location") or "",
                    "url": ev.get("htmlLink") or "",
                }
            )
        if not results:
            label = f" matching {q!r}" if q else ""
            return ToolResult(True, f"No upcoming events{label}.", {"results": []})
        lines = []
        for i, r in enumerate(results):
            when = r["start"][:16].replace("T", " ")
            loc = f" @ {r['location']}" if r["location"] else ""
            lines.append(f"{i+1}. {r['title']} — {when}{loc}")
        return ToolResult(
            True,
            "Calendar:\n" + "\n".join(lines),
            {"results": results, "query": q},
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "accessNotConfigured" in msg or "has not been used" in msg.lower():
            return ToolResult(
                False,
                "Enable Google Calendar API in Cloud Console, then retry google-auth.",
            )
        if "insufficient" in msg.lower() or "scope" in msg.lower():
            return ToolResult(
                False,
                "Calendar scope missing — run: python main.py google-auth",
                {"need_auth": True},
            )
        return ToolResult(False, f"Calendar list failed: {exc}")


def create_event(
    title: str = "",
    when: str = "",
    duration_minutes: int = 60,
    location: str = "",
    description: str = "",
    confirmed: bool = False,
) -> ToolResult:
    """Create a calendar event. Uses relative times via calendar_tools.parse_when."""
    title = (title or "").strip() or "Marc event"
    if not confirmed:
        return ToolResult(
            False,
            f"Create calendar event “{title}”? Confirm to proceed.",
            {
                "title": title,
                "when": when,
                "duration_minutes": duration_minutes,
                "location": location,
                "description": description,
            },
            needs_confirm=True,
        )
    if auth_status() != "authorized":
        return ToolResult(
            False,
            "Authorize Google first: python main.py google-auth",
            {"need_auth": True},
        )
    svc = build_service("calendar", "v3")
    if svc is None:
        return ToolResult(False, "Calendar API unavailable — run google-auth.", {"need_auth": True})

    start_dt: Optional[datetime] = None
    try:
        from tools.calendar_tools import parse_when

        start_dt = parse_when(text=when, when=when)
    except Exception:  # noqa: BLE001
        start_dt = None
    if start_dt is None:
        start_dt = datetime.now(_local_tz()) + timedelta(hours=1)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=_local_tz())
    end_dt = start_dt + timedelta(minutes=max(15, int(duration_minutes or 60)))

    body = {
        "summary": title,
        "location": location or "",
        "description": description or "Created by Marc",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": str(start_dt.tzinfo)},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": str(end_dt.tzinfo)},
    }
    try:
        ev = svc.events().insert(calendarId="primary", body=body).execute()
        when_s = start_dt.strftime("%a %b %d %I:%M %p")
        return ToolResult(
            True,
            f"Created “{title}” at {when_s}.",
            {"id": ev.get("id"), "url": ev.get("htmlLink"), "title": title},
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(False, f"Calendar create failed: {exc}")
