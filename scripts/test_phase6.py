#!/usr/bin/env python3
"""Phase 6 regression: contacts, reminders, multi-step controls, mail reply routing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laya_router.compound import parse_compound
from orchestrator import MarcOrchestrator
from orchestrator.followup import resolve_followup
from orchestrator.session import SessionState, VideoResult
from tools.calendar_tools import parse_when, set_reminder, REMINDERS_PATH
from tools.contacts import email_address, resolve_contact, whatsapp_name


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    c = resolve_contact("Mom")
    expect(c is not None and c.get("email"), f"mom={c}")
    expect(whatsapp_name("mummy").lower() == "mom" or "mom" in whatsapp_name("mummy").lower(), whatsapp_name("mummy"))
    to, _ = email_address("alex")
    expect("@" in to or to.lower() == "alex", to)
    print("OK contacts")

    p = parse_compound("message Mom on WhatsApp hi")
    expect(p is not None and p["steps"][0]["args"]["contact"].lower() in ("mom",), p)
    p = parse_compound("send email to alex saying hello")
    expect(p is not None and "@" in p["steps"][0]["args"]["to"].lower(), p)
    print("OK contacts in compound")

    p = parse_compound("remind me in 5 minutes to stand up")
    expect(p is not None and p["steps"][0]["tool"] == "set_reminder", p)
    # Use temp reminders file path by calling set_reminder
    r = set_reminder(text="in 2 minutes drink water")
    expect(r.ok, r.message)
    expect(REMINDERS_PATH.exists(), "reminders.json")
    due = parse_when(text="in 10 minutes")
    expect(due is not None, "parse_when")
    print("OK reminders", r.message)

    session = SessionState()
    session.awaiting = "pick_mail"
    session.last_results = [
        VideoResult(title="Hello — a@b.com", url="https://mail.google.com/mail/u/0/#inbox/abc123", index=0)
    ]
    session.last_mail_ids = ["abc123"]
    f = resolve_followup("reply to the first", session)
    expect(f is not None and f["intent"] == "mail_reply", f)
    expect(f["steps"][0]["args"].get("message_id") == "abc123", f["steps"])
    print("OK mail reply followup")

    session.last_typed = "hello from marc"
    f = resolve_followup("send that to Mom on WhatsApp", session)
    expect(f is not None and f["intent"] == "whatsapp_send", f)
    expect("hello" in (f["steps"][0]["args"].get("message") or "").lower(), f["steps"])
    print("OK send-that memory")

    orch = MarcOrchestrator(preload_laya=False, speak_fn=lambda m: None)
    orch.session.pending_plan = {
        "intent": "multi_step",
        "steps": [{"tool": "open_app", "args": {"app": "chrome"}}],
        "source": "clause_plan",
    }
    r = orch.handle("cancel")
    expect(orch.session.pending_plan is None, "cancel clears plan")
    print("OK multi-step cancel", r.reply)

    orch.session.pending_plan = {
        "intent": "multi_step",
        "steps": [
            {"tool": "open_app", "args": {"app": "chrome"}},
            {"tool": "open_app", "args": {"app": "notepad"}},
        ],
        "source": "clause_plan",
    }
    r = orch.handle("pause")
    expect(orch.session.plan_paused is True, "paused")
    print("OK multi-step pause")

    # Confirm awaiting regression
    orch2 = MarcOrchestrator(preload_laya=False, speak_fn=lambda m: None)
    r = orch2.handle("close camera")
    expect(orch2.session.awaiting == "confirm", orch2.session.awaiting)
    expect(orch2._pending is not None, "pending")
    print("OK confirm awaiting")

    print("PHASE6 REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
