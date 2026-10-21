"""Google Drive API tools for Marc (search / open)."""
from __future__ import annotations

import webbrowser
from typing import Dict, List
from urllib.parse import quote_plus

from tools.os_tools import ToolResult
from tools.google_oauth import auth_status, build_service


def search_files(query: str = "", max_results: int = 5) -> ToolResult:
    """Search Drive files by name/fullText."""
    q = (query or "").strip()
    if auth_status() != "authorized":
        # Browser fallback
        webbrowser.open(f"https://drive.google.com/drive/search?q={quote_plus(q or '')}")
        return ToolResult(
            True,
            f"Opened Drive search for {q or 'files'} (authorize for API: python main.py google-auth).",
            {"query": q, "results": [], "fallback": True, "need_auth": True},
        )
    svc = build_service("drive", "v3")
    if svc is None:
        webbrowser.open(f"https://drive.google.com/drive/search?q={quote_plus(q or '')}")
        return ToolResult(
            True,
            f"Opened Drive search (API unavailable).",
            {"query": q, "results": [], "fallback": True},
        )
    try:
        # Escape single quotes in Drive query
        safe = q.replace("'", "\\'")
        drive_q = (
            f"fullText contains '{safe}' or name contains '{safe}'"
            if safe
            else "trashed = false"
        )
        resp = (
            svc.files()
            .list(
                q=drive_q,
                pageSize=max(1, min(max_results, 15)),
                fields="files(id, name, mimeType, webViewLink, modifiedTime)",
                orderBy="modifiedTime desc",
                spaces="drive",
            )
            .execute()
        )
        files = resp.get("files") or []
        results: List[Dict[str, str]] = []
        for f in files:
            results.append(
                {
                    "id": f.get("id") or "",
                    "title": f.get("name") or "(unnamed)",
                    "mime": f.get("mimeType") or "",
                    "url": f.get("webViewLink") or f"https://drive.google.com/file/d/{f.get('id')}/view",
                    "modified": f.get("modifiedTime") or "",
                }
            )
        if not results:
            return ToolResult(True, f"No Drive files matching {q!r}.", {"query": q, "results": []})
        lines = [f"{i+1}. {r['title']}" for i, r in enumerate(results)]
        return ToolResult(
            True,
            "Drive results:\n" + "\n".join(lines),
            {"query": q, "results": results},
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "accessNotConfigured" in msg or "has not been used" in msg.lower():
            return ToolResult(
                False,
                "Enable Google Drive API in Cloud Console, then retry google-auth.",
            )
        if "insufficient" in msg.lower() or "scope" in msg.lower():
            return ToolResult(
                False,
                "Drive scope missing — run: python main.py google-auth",
                {"need_auth": True},
            )
        return ToolResult(False, f"Drive search failed: {exc}")


def open_file(file_id: str = "", url: str = "") -> ToolResult:
    link = (url or "").strip()
    if not link and file_id:
        link = f"https://drive.google.com/file/d/{file_id}/view"
    if not link:
        return ToolResult(False, "Which Drive file should I open?")
    webbrowser.open(link)
    return ToolResult(True, "Opened Drive file.", {"url": link})
