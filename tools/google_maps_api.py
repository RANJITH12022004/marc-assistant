"""Google Maps Platform helpers (Geocoding / Directions / Places) via API key.

Uses GOOGLE_MAPS_API_KEY, else GOOGLE_API_KEY, else GEMINI_API_KEY.
Falls back to opening maps.google.com in the browser if the API fails.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Any, Dict, List, Optional

from tools.os_tools import ToolResult


def _api_key() -> str:
    import os

    for name in ("GOOGLE_MAPS_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        v = (os.getenv(name) or "").strip()
        if v:
            return v
    try:
        from settings import settings

        return (
            getattr(settings, "google_maps_api_key", None)
            or settings.gemini_api_key
            or ""
        ).strip()
    except Exception:  # noqa: BLE001
        return ""


def _get(url: str, params: Dict[str, str]) -> Dict[str, Any]:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "Marc/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def maps_search(query: str = "", open_browser: bool = True) -> ToolResult:
    """Find places near the query text; optionally open the first result in Maps."""
    q = (query or "").strip()
    if not q:
        return ToolResult(False, "Where should I search on Maps?")
    key = _api_key()
    results: List[Dict[str, str]] = []
    if key:
        try:
            data = _get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                {"query": q, "key": key},
            )
            status = data.get("status") or ""
            if status == "OK":
                for p in (data.get("results") or [])[:5]:
                    loc = (p.get("geometry") or {}).get("location") or {}
                    results.append(
                        {
                            "title": p.get("name") or q,
                            "address": p.get("formatted_address") or "",
                            "lat": str(loc.get("lat", "")),
                            "lng": str(loc.get("lng", "")),
                            "url": (
                                f"https://www.google.com/maps/search/?api=1"
                                f"&query={urllib.parse.quote_plus(p.get('name') or q)}"
                            ),
                        }
                    )
            elif status not in ("ZERO_RESULTS",):
                # Likely key/API not enabled — fall through to browser
                pass
        except Exception:  # noqa: BLE001
            pass

    if results:
        lines = [
            f"{i+1}. {r['title']}" + (f" — {r['address']}" if r["address"] else "")
            for i, r in enumerate(results)
        ]
        if open_browser:
            webbrowser.open(results[0]["url"])
        return ToolResult(
            True,
            "Maps:\n" + "\n".join(lines),
            {"query": q, "results": results},
        )

    # Browser fallback (always works)
    url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(q)}"
    webbrowser.open(url)
    hint = ""
    if not key:
        hint = " (set GOOGLE_MAPS_API_KEY for spoken place results)"
    else:
        hint = " (enable Places API for richer results)"
    return ToolResult(
        True,
        f"Opened Maps for {q}.{hint}",
        {"query": q, "results": [], "fallback": True, "url": url},
    )


def maps_directions(
    destination: str = "",
    origin: str = "",
    mode: str = "driving",
) -> ToolResult:
    """Get directions; opens Maps and returns a short spoken summary when API works."""
    dest = (destination or "").strip()
    if not dest:
        return ToolResult(False, "Where do you want directions to?")
    origin = (origin or "").strip() or "My Location"
    mode = (mode or "driving").lower()
    if mode not in ("driving", "walking", "transit", "bicycling"):
        mode = "driving"

    key = _api_key()
    summary = ""
    if key and origin.lower() not in ("my location", "here", ""):
        try:
            data = _get(
                "https://maps.googleapis.com/maps/api/directions/json",
                {"origin": origin, "destination": dest, "mode": mode, "key": key},
            )
            if (data.get("status") or "") == "OK":
                routes = data.get("routes") or []
                if routes:
                    leg = (routes[0].get("legs") or [{}])[0]
                    dist = (leg.get("distance") or {}).get("text") or ""
                    dur = (leg.get("duration") or {}).get("text") or ""
                    summary = f"{dist}, about {dur}." if dist or dur else ""
        except Exception:  # noqa: BLE001
            pass

    # Open Google Maps directions URL
    params = {
        "api": "1",
        "destination": dest,
        "travelmode": mode,
    }
    if origin.lower() not in ("my location", "here"):
        params["origin"] = origin
    url = "https://www.google.com/maps/dir/?api=1&" + urllib.parse.urlencode(params)
    webbrowser.open(url)
    spoken = f"Directions to {dest}"
    if summary:
        spoken += f": {summary}"
    else:
        spoken += "."
    return ToolResult(
        True,
        spoken,
        {"origin": origin, "destination": dest, "mode": mode, "url": url, "summary": summary},
    )
