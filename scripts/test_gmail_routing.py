#!/usr/bin/env python3
"""Gmail routing smoke: unauthorized must return a clear message (no crash)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.gmail_api import GmailAPI, TOKEN, CREDENTIALS
from tools.os_tools import ToolResult


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    g = GmailAPI()
    # Force unauthorized path
    with patch.object(g, "_get_service", return_value=None):
        g._error = "not_authorized"
        r = g.summarize("is:unread")
        expect(not r.ok or "Authorize" in r.message.lower() or r.data.get("need_auth"), r.message)
        expect("Authorize" in r.message or r.data.get("need_auth") or "gmail-auth" in r.message.lower(), r.message)
        print("OK summarize unauthorized:", r.message[:80])

        r2 = g.compose("a@b.com", "hi", "body", confirmed=False)
        expect(r2.needs_confirm or "Confirm" in r2.message, r2.message)
        print("OK compose needs confirm before API")

        r3 = g.compose("a@b.com", "hi", "body", confirmed=True)
        expect(not r3.ok, r3.message)
        expect(
            "authorize" in r3.message.lower() or "gmail-auth" in r3.message.lower(),
            r3.message,
        )
        print("OK compose confirmed unauthorized:", r3.message[:80])

    status = g.auth_status()
    expect(status in ("authorized", "credentials_present_need_auth", "missing_credentials"), status)
    print("OK auth_status:", status)
    print("GMAIL ROUTING SMOKE PASSED")
    print("Setup guide: docs/gmail_setup.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
