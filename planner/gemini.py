"""Gemini System-2 planner for Marc."""
from __future__ import annotations

import concurrent.futures
import json
import re
from typing import Any, Dict, List, Optional

from settings import settings
from tools.os_tools import TOOL_SCHEMAS


def _tool_names() -> str:
    return ", ".join(t["name"] for t in TOOL_SCHEMAS)


SYSTEM = """You are Marc's planner on a Windows laptop.
Return ONLY valid JSON with this shape:
{"reply":"short spoken reply","steps":[{"tool":"tool_name","args":{...},"delay":0.5}]}
Rules:
- Emit ONE step per user-chained action (and/then/plus). Max 8 steps.
- Do NOT collapse site navigation into a google query. Example:
  "open browser and search for youtube and on youtube search for samsung"
  → open_app chrome, then youtube_search query=samsung (or youtube_home then youtube_search).
  NEVER google_search query="youtube and on youtube search for samsung".
- Prefer youtube_search / google_search / youtube_home over generic web_search when the site is clear.
- Destructive actions (mail_compose send, whatsapp_send, close_app) may be included; the runtime confirms.
- Use only these tools: """ + _tool_names() + """
- No shell, no PowerShell, no cmd, no deleting files, no shutdown.
- If the user is chatting, return steps=[] and a helpful reply.
- If ambiguous, steps=[] and ask a clarifying question in reply.
"""


class GeminiPlanner:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or settings.gemini_api_key
        self._model = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _ensure(self):
        if self._model is not None:
            return self._model
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        import google.generativeai as genai

        genai.configure(api_key=self.api_key)
        self._model = genai.GenerativeModel(settings.gemini_model)
        return self._model

    def plan(
        self,
        transcript: str,
        laya_hints: Optional[Dict[str, Any]] = None,
        slots: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.available:
            return self._offline_plan(transcript, slots)

        # Inject skill manifest when present
        skills_blurb = ""
        try:
            from pathlib import Path

            root = Path(__file__).resolve().parents[1]
            man = root / "config" / "skills_manifest.json"
            if man.exists():
                skills_blurb = "\nSkills:\n" + man.read_text(encoding="utf-8")[:2000]
        except Exception:  # noqa: BLE001
            pass

        model = self._ensure()
        user = {
            "transcript": transcript,
            "laya_hints": laya_hints or {},
            "slots": slots or {},
            "tool_schemas": TOOL_SCHEMAS,
        }
        prompt = (
            SYSTEM
            + skills_blurb
            + "\n\nUser request JSON:\n"
            + json.dumps(user, ensure_ascii=False)
        )
        try:
            def _call():
                return model.generate_content(prompt)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(_call)
                # Free Flash-Lite can be slow; default 45s (override GEMINI_TIMEOUT)
                timeout_s = float(getattr(settings, "gemini_timeout", 45) or 45)
                resp = fut.result(timeout=timeout_s)
            text = (resp.text or "").strip()
            return self._parse(text, transcript)
        except concurrent.futures.TimeoutError:
            timeout_s = float(getattr(settings, "gemini_timeout", 45) or 45)
            print(f"[marc] Gemini timed out ({timeout_s:.0f}s) — offline plan", flush=True)
            return self._offline_plan(transcript, slots)
        except Exception as exc:  # noqa: BLE001
            offline = self._offline_plan(transcript, slots)
            offline["reply"] = offline.get("reply") or "Could you rephrase that?"
            print(f"[marc] Gemini error: {exc}", flush=True)
            return offline

    def slots_only(self, transcript: str, intent: str) -> Dict[str, Any]:
        """Light slot fill when Laya already chose intent."""
        if not self.available:
            from laya_router.rules import extract_slots

            return extract_slots(transcript, intent)
        model = self._ensure()
        prompt = (
            f"Extract JSON args for intent '{intent}' from: {transcript!r}. "
            f"Return only a JSON object of args for tool {intent}."
        )
        try:
            resp = model.generate_content(prompt)
            text = (resp.text or "").strip()
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            pass
        from laya_router.rules import extract_slots

        return extract_slots(transcript, intent)

    def _parse(self, text: str, transcript: str) -> Dict[str, Any]:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {"reply": text or "I am not sure.", "steps": []}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"reply": "I could not parse a plan.", "steps": []}
        steps = data.get("steps") or []
        clean = []
        allowed = {t["name"] for t in TOOL_SCHEMAS}
        for step in steps[:8]:
            tool = (step.get("tool") or step.get("name") or "").lower()
            if tool in allowed:
                item: Dict[str, Any] = {"tool": tool, "args": step.get("args") or {}}
                if step.get("delay") is not None:
                    item["delay"] = step.get("delay")
                clean.append(item)
        return {"reply": data.get("reply") or "Done.", "steps": clean}

    def _offline_plan(self, transcript: str, slots: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        # Prefer clause planner for multi-step chains
        try:
            from laya_router.clause_plan import parse_clause_plan

            cplan = parse_clause_plan(transcript or "")
            if cplan and cplan.get("steps"):
                return {
                    "reply": cplan.get("reply") or "Done.",
                    "steps": cplan["steps"],
                }
        except Exception:  # noqa: BLE001
            pass

        from laya_router.rules import extract_slots, rule_classify

        slots = slots or extract_slots(transcript)
        intent = slots.get("intent") or rule_classify(transcript)[0]
        if intent == "chat":
            return {
                "reply": "I'm offline for chat. Try a command like open YouTube.",
                "steps": [],
            }
        if intent == "clarify":
            return {"reply": "Could you rephrase that?", "steps": []}
        if intent == "refuse":
            return {"reply": "I will not do that.", "steps": []}
        tool = intent
        args = {k: v for k, v in slots.items() if k not in ("intent", "raw")}
        return {"reply": f"Running {tool}.", "steps": [{"tool": tool, "args": args}]}
