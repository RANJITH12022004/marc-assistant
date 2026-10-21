"""Gmail API tools for Marc — OAuth Desktop + search / summarize / compose / send.

Requires one-time: python main.py google-auth
Credentials: data/gmail_credentials.json (Google Cloud Desktop OAuth client)
Token: data/google_token.json (mirrored to data/gmail_token.json)
"""
from __future__ import annotations

import base64
import re
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.os_tools import ToolResult
from tools.google_oauth import (
    CREDENTIALS,
    LEGACY_TOKEN,
    TOKEN,
    authorize as google_authorize,
    auth_status as google_auth_status,
    build_service,
)

# Back-compat aliases for tests/scripts
DATA = Path(__file__).resolve().parents[1] / "data"


def _clean_body(text: str) -> str:
    """Prefer Laya email_utils if present on the model drive."""
    try:
        import sys

        email_utils = Path(r"E:\laya-models\email_utils.py")
        if email_utils.exists():
            parent = str(email_utils.parent)
            if parent not in sys.path:
                sys.path.insert(0, parent)
            import email_utils as eu  # type: ignore

            if hasattr(eu, "clean_email_body"):
                return eu.clean_email_body(text) or text
            if hasattr(eu, "clean"):
                return eu.clean(text) or text
    except Exception:  # noqa: BLE001
        pass
    # Fallback: strip quoted noise / html-ish tags
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\r\n?", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"(?m)^>.*$", "", t)
    return re.sub(r"\s+", " ", t).strip()[:4000]


class GmailAPI:
    def __init__(self) -> None:
        self._service = None
        self._error = ""

    @property
    def available(self) -> bool:
        return TOKEN.exists() or LEGACY_TOKEN.exists() or CREDENTIALS.exists()

    def auth_status(self) -> str:
        return google_auth_status()

    def authorize(self, *, compose: bool = True) -> ToolResult:
        """Interactive OAuth browser flow (Gmail + Calendar + Drive)."""
        self._service = None
        return google_authorize(readonly=not compose)

    def _get_service(self, need_modify: bool = False):
        if self._service is not None:
            return self._service
        if google_auth_status() != "authorized":
            self._error = "not_authorized"
            return None
        try:
            self._service = build_service("gmail", "v1")
            if self._service is None:
                self._error = "not_authorized"
            return self._service
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
            return None

    def search(self, query: str = "in:inbox", max_results: int = 5) -> ToolResult:
        svc = self._get_service(need_modify=False)
        if svc is None:
            if self._error == "not_authorized":
                return ToolResult(
                    False,
                    "Authorize Gmail first: python main.py gmail-auth",
                    {"need_auth": True},
                )
            # Fallback: URL deep-link
            from urllib.parse import quote_plus
            import webbrowser

            q = query or "in:inbox"
            webbrowser.open(f"https://mail.google.com/mail/u/0/#search/{quote_plus(q)}")
            return ToolResult(
                True,
                f"Opened Gmail search for {q} (API unavailable: {self._error or 'no token'}).",
                {"query": q, "results": [], "fallback": True},
            )
        q = (query or "in:inbox").strip()
        try:
            resp = (
                svc.users()
                .messages()
                .list(userId="me", q=q, maxResults=max(1, min(max_results, 10)))
                .execute()
            )
            messages = resp.get("messages") or []
            results: List[Dict[str, str]] = []
            for i, m in enumerate(messages):
                full = (
                    svc.users()
                    .messages()
                    .get(userId="me", id=m["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"])
                    .execute()
                )
                headers = {
                    h["name"].lower(): h["value"]
                    for h in (full.get("payload") or {}).get("headers") or []
                }
                title = headers.get("subject") or "(no subject)"
                frm = headers.get("from") or ""
                results.append(
                    {
                        "id": m["id"],
                        "title": f"{title} — {frm}" if frm else title,
                        "url": f"https://mail.google.com/mail/u/0/#inbox/{m['id']}",
                        "snippet": (full.get("snippet") or "")[:200],
                    }
                )
            if not results:
                return ToolResult(True, f"No mail matching {q!r}.", {"query": q, "results": []})
            lines = [f"{i+1}. {r['title']}" for i, r in enumerate(results)]
            return ToolResult(
                True,
                "Mail results:\n" + "\n".join(lines),
                {"query": q, "results": results},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"Gmail search failed: {exc}")

    def summarize(self, query: str = "is:unread", max_messages: int = 5) -> ToolResult:
        found = self.search(query=query or "is:unread", max_results=max_messages)
        if not found.ok:
            return found
        results = (found.data or {}).get("results") or []
        if (found.data or {}).get("fallback"):
            return ToolResult(
                False,
                "Authorize Gmail to summarize: python main.py gmail-auth",
                {"need_auth": True},
            )
        if not results:
            return ToolResult(True, "No unread mail to summarize.", {"summary": ""})

        svc = self._get_service(need_modify=False)
        bodies: List[str] = []
        for r in results[:max_messages]:
            mid = r.get("id")
            if not mid or svc is None:
                bodies.append(f"{r.get('title')}: {r.get('snippet')}")
                continue
            try:
                full = svc.users().messages().get(userId="me", id=mid, format="full").execute()
                body = self._extract_body(full) or r.get("snippet") or ""
                bodies.append(f"From/Subject: {r.get('title')}\n{_clean_body(body)[:800]}")
            except Exception:  # noqa: BLE001
                bodies.append(f"{r.get('title')}: {r.get('snippet')}")

        blob = "\n---\n".join(bodies)
        summary = self._llm_summarize(blob) or self._heuristic_summary(results)
        return ToolResult(
            True,
            summary,
            {"summary": summary, "results": results, "query": query},
        )

    def _extract_body(self, msg: Dict[str, Any]) -> str:
        payload = msg.get("payload") or {}
        parts = payload.get("parts") or []
        if payload.get("body", {}).get("data"):
            return self._b64(payload["body"]["data"])
        for part in parts:
            mime = (part.get("mimeType") or "").lower()
            data = (part.get("body") or {}).get("data")
            if data and mime.startswith("text/plain"):
                return self._b64(data)
        for part in parts:
            data = (part.get("body") or {}).get("data")
            if data:
                return self._b64(data)
        return ""

    @staticmethod
    def _b64(data: str) -> str:
        raw = base64.urlsafe_b64decode(data + "===")
        return raw.decode("utf-8", errors="replace")

    def _llm_summarize(self, blob: str) -> str:
        try:
            from settings import settings
            import google.generativeai as genai

            if not settings.gemini_api_key:
                return ""
            if not getattr(settings, "mail_gemini", False):
                return ""
            if settings.quiet_mode:
                return ""
            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel(settings.gemini_model)
            resp = model.generate_content(
                "Summarize these emails for a spoken voice assistant in 2-4 short sentences. "
                "No bullet lists.\n\n"
                + blob[:6000]
            )
            return (resp.text or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _heuristic_summary(results: List[Dict[str, str]]) -> str:
        bits = []
        for r in results[:5]:
            bits.append(r.get("title") or r.get("snippet") or "")
        return "You have " + str(len(results)) + " messages. " + ". ".join(bits[:3]) + "."

    def compose(
        self,
        to: str,
        subject: str = "",
        body: str = "",
        confirmed: bool = False,
        draft_id: str = "",
    ) -> ToolResult:
        to = (to or "").strip()
        body = (body or "").strip()
        subject = (subject or "").strip() or "(no subject)"
        if not to:
            # Resolve contact name → email if possible
            return ToolResult(False, "Who should I email?")
        try:
            from tools.contacts import email_address, is_placeholder_email, resolve_contact

            # If `to` looks like a name, resolve
            if "@" not in to:
                addr, disp = email_address(to)
                if not addr or is_placeholder_email(addr):
                    return ToolResult(
                        False,
                        f"Add a real email for {disp or to} in config/contacts.json.",
                        {"need_contact_email": True, "contact": disp or to},
                    )
                to = addr
            elif is_placeholder_email(to):
                return ToolResult(
                    False,
                    "That email looks like a placeholder. Update config/contacts.json.",
                    {"need_contact_email": True},
                )
        except Exception:  # noqa: BLE001
            pass
        if not body:
            return ToolResult(False, "What should the email say?")

        preview = f"Email to {to}: {subject} — {body[:80]}"
        if not confirmed and not draft_id:
            return ToolResult(
                False,
                f"Send email to {to} about “{subject}”? Confirm to proceed.",
                {"to": to, "subject": subject, "body": body},
                needs_confirm=True,
            )

        svc = self._get_service(need_modify=True)
        if svc is None:
            return ToolResult(
                False,
                "Authorize Gmail with compose scope: python main.py gmail-auth",
                {"need_auth": True},
            )
        try:
            if draft_id:
                sent = (
                    svc.users()
                    .drafts()
                    .send(userId="me", body={"id": draft_id})
                    .execute()
                )
                return ToolResult(True, f"Email sent to {to}.", {"id": sent.get("id")})

            mime = MIMEText(body)
            mime["to"] = to
            mime["subject"] = subject
            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
            draft = (
                svc.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw}})
                .execute()
            )
            did = draft.get("id")
            # Send immediately after confirm
            svc.users().drafts().send(userId="me", body={"id": did}).execute()
            return ToolResult(
                True,
                f"Email sent to {to}.",
                {"draft_id": did, "to": to, "preview": preview},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"Gmail compose failed: {exc}")

    def reply(
        self,
        message_id: str,
        body: str = "Thanks, got it.",
        confirmed: bool = False,
    ) -> ToolResult:
        """Draft+send a reply to an existing message (confirm-gated)."""
        mid = (message_id or "").strip()
        body = (body or "").strip() or "Thanks, got it."
        if not mid:
            return ToolResult(False, "Which message should I reply to?")
        if not confirmed:
            return ToolResult(
                False,
                f"Send reply “{body[:60]}”? Confirm to proceed.",
                {"message_id": mid, "body": body},
                needs_confirm=True,
            )
        svc = self._get_service(need_modify=True)
        if svc is None:
            return ToolResult(
                False,
                "Authorize Gmail with compose scope: python main.py gmail-auth",
                {"need_auth": True},
            )
        try:
            original = (
                svc.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Message-ID", "References"],
                )
                .execute()
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in (original.get("payload") or {}).get("headers") or []
            }
            subj = headers.get("subject") or ""
            if not subj.lower().startswith("re:"):
                subj = f"Re: {subj}"
            to = headers.get("from") or ""
            # Prefer email in angle brackets
            m = re.search(r"<([^>]+)>", to)
            if m:
                to = m.group(1)
            mime = MIMEText(body)
            mime["to"] = to
            mime["subject"] = subj
            if headers.get("message-id"):
                mime["In-Reply-To"] = headers["message-id"]
                mime["References"] = (
                    (headers.get("references") or "") + " " + headers["message-id"]
                ).strip()
            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
            draft = (
                svc.users()
                .drafts()
                .create(
                    userId="me",
                    body={"message": {"raw": raw, "threadId": original.get("threadId")}},
                )
                .execute()
            )
            svc.users().drafts().send(userId="me", body={"id": draft.get("id")}).execute()
            return ToolResult(True, f"Reply sent to {to}.", {"to": to, "subject": subj})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(False, f"Gmail reply failed: {exc}")


_gmail: Optional[GmailAPI] = None


def get_gmail() -> GmailAPI:
    global _gmail
    if _gmail is None:
        _gmail = GmailAPI()
    return _gmail
