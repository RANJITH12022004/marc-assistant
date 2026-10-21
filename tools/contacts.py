"""Resolve spoken contact names to WhatsApp / email from config/contacts.json."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
CONTACTS_PATH = ROOT / "config" / "contacts.json"


def load_contacts() -> Dict[str, Dict[str, str]]:
    if not CONTACTS_PATH.exists():
        return {}
    try:
        data = json.loads(CONTACTS_PATH.read_text(encoding="utf-8"))
        return {str(k).lower(): (v if isinstance(v, dict) else {}) for k, v in data.items()}
    except Exception:  # noqa: BLE001
        return {}


def resolve_contact(name: str) -> Optional[Dict[str, str]]:
    """Return contact dict or None. Fuzzy: exact key, alias, startswith, contains."""
    raw = (name or "").strip()
    if not raw:
        return None
    key = raw.lower()
    key = re.sub(r"^(?:to\s+|for\s+)", "", key).strip()
    book = load_contacts()
    if not book:
        return None
    if key in book:
        return {"key": key, **book[key]}
    # alias field
    for k, meta in book.items():
        aliases = meta.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if key == k or key in [a.lower() for a in aliases]:
            return {"key": k, **meta}
        display = (meta.get("whatsapp") or meta.get("name") or k).lower()
        if key == display:
            return {"key": k, **meta}
    # startswith / contained
    best = None
    for k, meta in book.items():
        display = (meta.get("whatsapp") or meta.get("name") or k).lower()
        if key.startswith(k) or k.startswith(key) or key in display or display in key:
            best = {"key": k, **meta}
            break
    return best


def whatsapp_name(name: str) -> str:
    """Display name to type into WhatsApp search."""
    c = resolve_contact(name)
    if c:
        return (c.get("whatsapp") or c.get("name") or c.get("key") or name).strip()
    return name.strip()


def email_address(name: str) -> Tuple[str, str]:
    """Return (to_address_or_name, display). If email known, use it.

    Placeholder domains (example.com) are treated as missing so compose
    refuses instead of sending to a fake address.
    """
    c = resolve_contact(name)
    if c and c.get("email"):
        addr = c["email"].strip()
        disp = (c.get("name") or c.get("key") or name).strip()
        if is_placeholder_email(addr):
            return "", disp
        return addr, disp
    raw = name.strip()
    if "@" in raw and not is_placeholder_email(raw):
        return raw, raw
    return "", raw


def is_placeholder_email(addr: str) -> bool:
    a = (addr or "").strip().lower()
    if not a or "@" not in a:
        return True
    domain = a.rsplit("@", 1)[-1]
    return domain in ("example.com", "example.org", "example.net", "localhost", "test")


def email_ready(name: str) -> Tuple[bool, str, str]:
    """Return (ok, address, display). ok False if no real email configured."""
    addr, disp = email_address(name)
    if not addr or is_placeholder_email(addr):
        return False, "", disp or name
    return True, addr, disp
