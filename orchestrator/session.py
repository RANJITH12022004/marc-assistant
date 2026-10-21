"""Multi-turn session memory for continuous Marc."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VideoResult:
    title: str
    url: str
    index: int = 0


@dataclass
class SessionState:
    last_app: str = ""
    last_site: str = ""  # youtube | gmail | google | ""
    last_search_query: str = ""
    last_results: List[VideoResult] = field(default_factory=list)
    # none | pick_video | pick_mail | pick_result | slot:open_app | slot:web_search | slot:continue | confirm
    awaiting: str = "none"
    pending_prefix: str = ""  # incomplete utterance to prepend on next turn
    preferred_browser: str = "chrome"  # chrome | brave | edge
    history: List[str] = field(default_factory=list)
    empty_listens: int = 0
    sleeping: bool = False
    # Phase 5 memory
    last_typed: str = ""
    last_contact: str = ""
    last_mail_ids: List[str] = field(default_factory=list)
    last_summary: str = ""
    last_tool: str = ""  # last successful tool name (type_text, whatsapp_send, …)
    last_photo_path: str = ""  # path to last camera capture if known
    pending_plan: Optional[Dict[str, Any]] = None
    plan_paused: bool = False
    abort_plan: bool = False

    def push_history(self, utterance: str) -> None:
        u = (utterance or "").strip()
        if not u:
            return
        self.history.append(u)
        self.history = self.history[-5:]

    def set_youtube_results(self, query: str, results: List[Dict[str, str]]) -> None:
        self.set_results("youtube", query, results)

    def set_results(self, site: str, query: str, results: List[Dict[str, str]]) -> None:
        self.last_site = site
        self.last_search_query = query or ""
        if results:
            self.awaiting = "pick_video" if site == "youtube" else "pick_result"
            self.last_results = [
                VideoResult(title=r.get("title", ""), url=r.get("url", ""), index=i)
                for i, r in enumerate(results)
            ]
        else:
            self.awaiting = "none"
            self.last_results = []

    def clear_awaiting(self) -> None:
        self.awaiting = "none"
        self.pending_prefix = ""

    def clear_pick_context(self) -> None:
        """Leave YouTube/Google pick mode so ordinals/yes don't sticky-misroute."""
        self.awaiting = "none"
        self.pending_prefix = ""
        self.last_results = []
        if self.last_site in ("youtube", "google"):
            self.last_site = ""
        self.last_search_query = ""

    def hold_slot(self, kind: str, prefix: str = "") -> None:
        self.awaiting = kind
        self.pending_prefix = (prefix or "").strip()

    def is_holding(self) -> bool:
        return self.awaiting.startswith("slot:") or self.awaiting in (
            "pick_video",
            "pick_mail",
            "pick_result",
            "confirm",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_app": self.last_app,
            "last_site": self.last_site,
            "last_search_query": self.last_search_query,
            "awaiting": self.awaiting,
            "preferred_browser": self.preferred_browser,
            "results": [{"title": v.title, "url": v.url, "index": v.index} for v in self.last_results],
            "history": list(self.history),
            "last_typed": self.last_typed,
            "last_contact": self.last_contact,
            "last_summary": (self.last_summary or "")[:120],
            "pending_plan_steps": len((self.pending_plan or {}).get("steps") or []),
        }
