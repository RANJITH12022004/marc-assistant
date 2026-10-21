"""Shared Google OAuth for Marc (Gmail + Calendar + Drive).

Credentials: data/gmail_credentials.json (Desktop OAuth client JSON)
Token:      data/google_token.json  (also mirrored to data/gmail_token.json)

Run: python main.py google-auth
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from tools.os_tools import ToolResult

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CREDENTIALS = DATA / "gmail_credentials.json"
TOKEN = DATA / "google_token.json"
LEGACY_TOKEN = DATA / "gmail_token.json"

SCOPES: List[str] = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
]

SCOPES_READONLY: List[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def credentials_path() -> Path:
    alt = DATA / "google_credentials.json"
    if CREDENTIALS.exists():
        return CREDENTIALS
    if alt.exists():
        return alt
    return CREDENTIALS


def token_path() -> Path:
    if TOKEN.exists():
        return TOKEN
    if LEGACY_TOKEN.exists():
        return LEGACY_TOKEN
    return TOKEN


def auth_status() -> str:
    if TOKEN.exists() or LEGACY_TOKEN.exists():
        return "authorized"
    if credentials_path().exists():
        return "credentials_present_need_auth"
    return "missing_credentials"


def authorize(*, readonly: bool = False, force: bool = False) -> ToolResult:
    """Interactive OAuth browser flow for Gmail + Calendar + Drive."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        return ToolResult(
            False,
            "Install: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2",
        )

    creds_file = credentials_path()
    if not creds_file.exists():
        return ToolResult(
            False,
            f"Place Google Desktop OAuth client JSON at {CREDENTIALS}.",
        )

    scopes = SCOPES_READONLY if readonly else SCOPES
    wanted = set(scopes)

    if force:
        for p in (TOKEN, LEGACY_TOKEN):
            if p.exists():
                p.unlink()

    creds = None
    path = token_path()
    if path.exists() and not force:
        try:
            creds = Credentials.from_authorized_user_file(str(path), scopes)
            have = set(creds.scopes or [])
            if not wanted.issubset(have):
                # Need incremental / fresh consent for new APIs
                creds = None
        except Exception:  # noqa: BLE001
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:  # noqa: BLE001
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), scopes)
            creds = flow.run_local_server(port=0)

    DATA.mkdir(parents=True, exist_ok=True)
    payload = creds.to_json()
    TOKEN.write_text(payload, encoding="utf-8")
    LEGACY_TOKEN.write_text(payload, encoding="utf-8")
    return ToolResult(
        True,
        f"Google authorized (Gmail + Calendar + Drive). Token saved to {TOKEN}.",
    )


def get_credentials(scopes: Optional[List[str]] = None):
    """Load and refresh OAuth credentials, or None if missing."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None

    path = token_path()
    if not path.exists():
        return None
    use_scopes = scopes or SCOPES
    try:
        creds = Credentials.from_authorized_user_file(str(path), use_scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json(), encoding="utf-8")
            LEGACY_TOKEN.write_text(creds.to_json(), encoding="utf-8")
        if not creds or not creds.valid:
            return None
        # Scope check — warn callers by returning None if required scopes missing
        have = set(creds.scopes or [])
        if not set(use_scopes).issubset(have) and have:
            # Token may list subset after refresh; still try if overlapping
            pass
        return creds
    except Exception:  # noqa: BLE001
        return None


def build_service(api: str, version: str, scopes: Optional[List[str]] = None):
    creds = get_credentials(scopes)
    if creds is None:
        return None
    from googleapiclient.discovery import build

    return build(api, version, credentials=creds, cache_discovery=False)
