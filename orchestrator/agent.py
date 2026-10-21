"""Marc agent loop: followup → compound → Laya → tools + session + persona."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from laya_router import MarcLayaRouter
from laya_router.clause_plan import parse_clause_plan
from laya_router.compound import is_cancel, is_confirm, normalize_transcript, parse_compound
from laya_router.intents import PLANNER_INTENTS, SIMPLE_AUTO_INTENTS
from laya_router.rules import describe_intents, extract_slots
from orchestrator.audit import audit, log_misroute, log_turn
from orchestrator.followup import resolve_followup
from orchestrator.persona import closer_for, speakable
from orchestrator.session import SessionState, VideoResult
from planner import GeminiPlanner
from settings import settings
from tools import OSTools, ToolResult
from tools.browser import get_browser


ConfirmFn = Callable[[str], bool]
SpeakFn = Callable[[str], None]


@dataclass
class TurnResult:
    transcript: str
    intent: str
    confidence: float
    source: str
    reply: str
    spoken: str = ""
    steps_run: List[Dict[str, Any]] = field(default_factory=list)
    used_planner: bool = False
    pending_confirm: Optional[Dict[str, Any]] = None
    should_continue: bool = True
    session: Optional[SessionState] = None


class MarcOrchestrator:
    def __init__(
        self,
        preload_laya: bool = True,
        confirm_fn: Optional[ConfirmFn] = None,
        speak_fn: Optional[SpeakFn] = None,
        session: Optional[SessionState] = None,
        *,
        lazy_laya: bool = False,
    ) -> None:
        # lazy_laya: rules work immediately; Laya loads in background after ready TTS
        if lazy_laya:
            self.router = MarcLayaRouter(preload=False, rules_only=False)
        else:
            self.router = MarcLayaRouter(preload=preload_laya, rules_only=not preload_laya)
        self.planner = GeminiPlanner()
        self.tools = OSTools()
        self.browser = get_browser()
        self.confirm_fn = confirm_fn or (lambda msg: True)
        self.speak_fn = speak_fn or (lambda msg: None)
        self.session = session or SessionState()
        self._pending: Optional[Dict[str, Any]] = None

    def start_laya_background(self) -> None:
        """Load Laya weights off the voice thread (after ready TTS)."""
        import threading

        def _load() -> None:
            try:
                print("[marc] Laya loading in background…", flush=True)
                agent = self.router._ensure_agent()
                if agent is not None:
                    print("[marc] Laya ready", flush=True)
                    os.environ["MARC_LAYA_READY"] = "1"
                else:
                    print("[marc] Laya unavailable; staying rules-first", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[marc] Laya background load failed: {exc}", flush=True)

        threading.Thread(target=_load, daemon=True, name="marc-laya-load").start()

    def _speak(self, spoken: str, full: str = "") -> None:
        print(f"Marc: {full or spoken}")
        self.speak_fn(spoken)

    def _finish(
        self,
        transcript: str,
        intent: str,
        confidence: float,
        source: str,
        reply: str,
        *,
        steps_run: Optional[List] = None,
        used_planner: bool = False,
        pending: Optional[Dict] = None,
        should_continue: bool = True,
        tool_ok: bool = True,
    ) -> TurnResult:
        spoken = closer_for(
            intent,
            tool_ok,
            reply,
            awaiting=self.session.awaiting,
            site=self.session.last_site,
            query=self.session.last_search_query,
        )
        # For status / blocked messages, prefer persona spoken line
        if intent == "mail_summarize_blocked":
            spoken = closer_for("mail_summarize_blocked", True, reply)
        elif intent == "system_status" and reply:
            spoken = closer_for("system_status", True, reply)
        elif intent == "sleep":
            spoken = closer_for("sleep", True, reply)
            should_continue = False

        # Instant OS actions: skip Edge-TTS (was adding 1–3s after every hotkey/close/play)
        _RAPID = {
            "close_app",
            "hotkey",
            "volume_media",
            "open_app",
            "type_text",
            "focus_window",
            "clipboard",
            "settings",
            "camera_photo",
            "camera_mode",
            "open_last_photo",
        }
        silent = (
            bool(getattr(settings, "silent_rapid", True))
            and tool_ok
            and not pending
            and (intent or "").lower() in _RAPID
        )
        if silent:
            print(f"Marc: {speakable(spoken)}", flush=True)
        else:
            self._speak(speakable(spoken), full=reply if reply != spoken else spoken)
        result = TurnResult(
            transcript=transcript,
            intent=intent,
            confidence=confidence,
            source=source,
            reply=reply,
            spoken=spoken,
            steps_run=steps_run or [],
            used_planner=used_planner,
            pending_confirm=pending,
            should_continue=should_continue,
            session=self.session,
        )
        try:
            log_turn(
                transcript,
                intent=intent,
                confidence=confidence,
                source=source,
                awaiting=self.session.awaiting,
                pending=bool(pending or self._pending),
                steps=steps_run or [],
                tool_ok=tool_ok,
            )
        except Exception:  # noqa: BLE001
            pass
        return result

    def handle(self, transcript: str, confirmed: bool = False) -> TurnResult:
        transcript = normalize_transcript(transcript or "")
        if not transcript:
            return self._finish(
                "",
                "clarify",
                1.0,
                "rules",
                "I did not catch that.",
                tool_ok=False,
            )

        self.session.push_history(transcript)
        low = transcript.lower().strip()

        # Multi-step runtime controls while a plan is queued
        if low in ("pause", "pause plan", "hold on", "wait"):
            if self.session.pending_plan and (self.session.pending_plan.get("steps") or []):
                self.session.plan_paused = True
                return self._finish(
                    transcript,
                    "clarify",
                    1.0,
                    "rules",
                    "Paused. Say continue or cancel.",
                    tool_ok=True,
                )
        if low in ("continue", "resume", "resume plan", "keep going"):
            if self.session.pending_plan and (self.session.pending_plan.get("steps") or []):
                self.session.plan_paused = False
                cont = dict(self.session.pending_plan)
                self.session.pending_plan = None
                return self._execute_plan(transcript, cont)
        if low in ("skip", "skip step", "next step"):
            if self.session.pending_plan and (self.session.pending_plan.get("steps") or []):
                steps = list(self.session.pending_plan.get("steps") or [])
                skipped = steps.pop(0) if steps else None
                self.session.pending_plan["steps"] = steps
                if steps:
                    return self._finish(
                        transcript,
                        "clarify",
                        1.0,
                        "rules",
                        f"Skipped. {len(steps)} steps left. Say continue.",
                        tool_ok=True,
                    )
                self.session.pending_plan = None
                return self._finish(
                    transcript,
                    "clarify",
                    1.0,
                    "rules",
                    "Skipped last step. Done.",
                    tool_ok=True,
                )
        if low in ("cancel plan", "stop plan", "abort plan") or (
            low == "cancel" and self.session.pending_plan and not self._pending
        ):
            if self.session.pending_plan:
                self.session.pending_plan = None
                self.session.plan_paused = False
                self.session.abort_plan = True
                return self._finish(
                    transcript,
                    "clarify",
                    1.0,
                    "rules",
                    "Cancelled the remaining steps.",
                    tool_ok=True,
                )

        if low in ("what can you do", "help", "capabilities", "who are you"):
            from laya_router.synonyms import capability_blurb

            reply = capability_blurb() + "\n" + describe_intents()
            return self._finish(transcript, "chat", 1.0, "rules", reply)

        if self._pending and (confirmed or is_confirm(transcript)):
            pending = self._pending
            self._pending = None
            self.session.clear_awaiting()
            # Multi-close batch: args may include apps list
            if pending.get("tool") == "close_apps":
                apps = list(pending.get("args", {}).get("apps") or [])
                last = ToolResult(True, "Done.")
                for app in apps:
                    last = self._exec_tool("close_app", {"app": app}, confirmed=True)
                    time.sleep(0.4)
                return self._finish(
                    transcript,
                    "close_app",
                    1.0,
                    "confirm",
                    last.message,
                    steps_run=[{"tool": "close_apps", "args": {"apps": apps}, "result": last.to_dict()}],
                    tool_ok=last.ok,
                )
            result = self._exec_tool(pending["tool"], pending["args"], confirmed=True)
            audit(
                "tool",
                {
                    "tool": pending["tool"],
                    "args": pending["args"],
                    "result": result.to_dict(),
                    "confirmed": True,
                },
            )
            steps_run = [
                {
                    "tool": pending["tool"],
                    "args": pending["args"],
                    "result": result.to_dict(),
                }
            ]
            # Resume remaining multi-step queue if any
            rest = getattr(self.session, "pending_plan", None) or {}
            rest_steps = list(rest.get("steps") or [])
            self.session.pending_plan = None
            if result.ok and rest_steps:
                cont = {
                    "intent": rest.get("intent") or pending.get("intent", "multi_step"),
                    "steps": rest_steps,
                    "reply": rest.get("reply") or result.message,
                    "source": rest.get("source") or "clause_plan",
                }
                more, reply2, pend2, ok2 = self._run_plan_steps(cont)
                steps_run.extend(more)
                if pend2:
                    self.session.awaiting = "confirm"
                    return self._finish(
                        transcript,
                        cont["intent"],
                        1.0,
                        "confirm",
                        reply2,
                        steps_run=steps_run,
                        pending=pend2,
                        tool_ok=True,
                    )
                return self._finish(
                    transcript,
                    cont["intent"],
                    1.0,
                    "confirm",
                    reply2 or result.message,
                    steps_run=steps_run,
                    tool_ok=result.ok and ok2,
                )
            return self._finish(
                transcript,
                pending.get("intent", "clarify"),
                1.0,
                "confirm",
                result.message,
                steps_run=steps_run,
                tool_ok=result.ok,
            )
        if self._pending and is_cancel(transcript):
            self._pending = None
            self.session.pending_plan = None
            self.session.clear_awaiting()
            return self._finish(transcript, "clarify", 1.0, "confirm", "Cancelled.")

        if is_confirm(transcript) and not self._pending:
            return self._finish(
                transcript,
                "clarify",
                1.0,
                "rules",
                "Nothing to confirm. Say a command.",
            )

        # Follow-ups (play first, search youtube, sleep, mail search)
        fplan = resolve_followup(transcript, self.session)
        if fplan:
            if fplan.get("intent") == "reparse" and fplan.get("reparse"):
                return self.handle(str(fplan["reparse"]))
            audit("followup", {"transcript": transcript, "plan": fplan})
            return self._execute_plan(transcript, fplan)

        # N-step clause planner (before binary compound — fixes nested chains)
        cplan = parse_clause_plan(transcript)
        if cplan:
            if cplan.get("awaiting"):
                self.session.hold_slot(
                    cplan.get("awaiting") or "slot:continue",
                    cplan.get("pending_prefix") or "",
                )
            audit("clause_plan", {"transcript": transcript, "plan": cplan})
            return self._execute_plan(transcript, cplan)

        # Compound multi-step (≤2-step regex patterns)
        plan = parse_compound(transcript)
        if plan:
            if plan.get("intent") == "hold_slot":
                awaiting = plan.get("awaiting") or "slot:open_app"
                self.session.hold_slot(awaiting, plan.get("pending_prefix") or "")
                audit("hold_slot", {"transcript": transcript, "awaiting": awaiting})
                return self._finish(
                    transcript,
                    "clarify",
                    plan.get("confidence", 0.99),
                    "compound",
                    plan.get("reply") or "What next?",
                    tool_ok=True,
                )
            audit("compound", {"transcript": transcript, "plan": plan})
            return self._execute_plan(transcript, plan)

        intent_res = self.router.classify(transcript)
        audit(
            "intent",
            {
                "transcript": transcript,
                "intent": intent_res.intent,
                "confidence": intent_res.confidence,
                "source": intent_res.source,
            },
        )

        if intent_res.intent == "refuse":
            from laya_router.rules import rule_classify

            ri, rc = rule_classify(transcript)
            if ri != "refuse":
                intent_res.intent = ri
                intent_res.confidence = rc
                intent_res.source = "hybrid"
            else:
                return self._finish(
                    transcript,
                    "refuse",
                    intent_res.confidence,
                    intent_res.source,
                    "That looks unsafe.",
                    tool_ok=False,
                )

        use_planner = (
            intent_res.intent in PLANNER_INTENTS
            or intent_res.needs_planner_bool
            or intent_res.confidence < settings.confidence_threshold
            or intent_res.intent == "chat"
        )
        gemini_mode = (getattr(settings, "gemini_mode", None) or "unclear_only").lower()
        if settings.quiet_mode or gemini_mode in ("off", "never", "false", "0"):
            use_planner = False
        elif gemini_mode in ("unclear_only", "unclear", "laya_first"):
            # Fast path: only Gemini when unclear / chat / true multi-step need
            use_planner = intent_res.intent in ("chat", "clarify", "multi_step") or (
                intent_res.needs_planner_bool
                and intent_res.intent not in SIMPLE_AUTO_INTENTS
                and intent_res.confidence < settings.confidence_threshold
            )
            # mail_compose still allowed via PLANNER when needs_planner
            if intent_res.intent == "mail_compose" and intent_res.needs_planner_bool:
                use_planner = True


        # Never call Gemini just to say "rephrase" — that freezes the UI on slow/hung API
        if intent_res.intent == "clarify" and intent_res.confidence >= 0.5:
            # Keep pick/slot context — ask a useful question instead of wiping memory
            if self.session.awaiting in ("pick_result", "pick_video"):
                return self._finish(
                    transcript,
                    "clarify",
                    intent_res.confidence,
                    intent_res.source,
                    "Which one — first, second, or third?",
                    tool_ok=True,
                )
            if self.session.awaiting.startswith("slot:"):
                prompts = {
                    "slot:open_app": "Open what?",
                    "slot:web_search": "Search for what?",
                    "slot:type_text": "Type what?",
                    "slot:continue": "And then?",
                }
                return self._finish(
                    transcript,
                    "clarify",
                    intent_res.confidence,
                    intent_res.source,
                    prompts.get(self.session.awaiting, "Could you finish that?"),
                    tool_ok=True,
                )
            log_misroute(
                transcript,
                "clarify",
                intent_res.source,
                confidence=intent_res.confidence,
                note="ambiguous_utterance",
            )
            return self._finish(
                transcript,
                "clarify",
                intent_res.confidence,
                intent_res.source,
                "Could you rephrase that?",
                tool_ok=False,
            )

        slots = extract_slots(transcript, intent_res.intent)

        # Prefer opening a known app over googling its name (exact apps only)
        if intent_res.intent == "web_search":
            q = (slots.get("query") or "").strip()
            eng = (slots.get("engine") or "google").lower()
            topic_block = {"music", "songs", "song", "news", "videos", "video", "movies"}
            if (
                eng not in ("youtube", "yt")
                and q
                and len(q.split()) <= 3
                and q.lower() not in topic_block
            ):
                key = q.lower()
                if key in self.tools._alias_index or key in self.tools.apps:
                    canon, meta = self.tools.resolve_app(q)
                    if meta and not re.search(r"\b(for|about|how|what|why|near)\b", q, re.I):
                        intent_res.intent = "open_app"
                        slots = {"intent": "open_app", "raw": transcript, "app": canon}

        # Don't auto-run low-confidence System-1 guesses 
        # Exception: mail_summarize near threshold when utterance clearly mentions mail
        _mailish = bool(re.search(r"\b(email|mail|inbox|gmail|message)\b", transcript, re.I))
        if (
            intent_res.intent in SIMPLE_AUTO_INTENTS
            and intent_res.confidence < settings.confidence_threshold
            and intent_res.source in ("laya", "hybrid")
        ):
            if not (
                intent_res.intent == "mail_summarize"
                and intent_res.confidence >= 0.75
                and _mailish
            ):
                return self._finish(
                    transcript,
                    "clarify",
                    intent_res.confidence,
                    intent_res.source,
                    "Could you rephrase that?",
                    tool_ok=False,
                )

        if use_planner and intent_res.intent not in SIMPLE_AUTO_INTENTS:
            gplan = self.planner.plan(
                transcript,
                laya_hints={
                    "intent": intent_res.intent,
                    "confidence": intent_res.confidence,
                },
                slots=slots,
            )
            audit("plan", {"transcript": transcript, "plan": gplan})
            fake = {
                "intent": intent_res.intent,
                "confidence": intent_res.confidence,
                "steps": gplan.get("steps") or [],
                "reply": gplan.get("reply") or "Done.",
                "source": "gemini",
            }
            return self._execute_plan(transcript, fake, used_planner=True)

        tool_name = intent_res.intent
        args = {k: v for k, v in slots.items() if k not in ("intent", "raw")}
        if tool_name == "type_text" and args.get("text"):
            args["text"] = re.sub(
                r"^(?:now\s+)*(?:type|write|dictate)\s+",
                "",
                args["text"],
                flags=re.I,
            ).strip(" .,\"'")

        fake = {
            "intent": tool_name,
            "confidence": intent_res.confidence,
            "source": intent_res.source,
            "steps": [
                {
                    "tool": tool_name,
                    "args": args,
                    "confirm": False if tool_name == "type_text" else None,
                }
            ],
        }
        return self._execute_plan(transcript, fake)

    def _execute_plan(
        self,
        transcript: str,
        plan: Dict[str, Any],
        used_planner: bool = False,
    ) -> TurnResult:
        intent = plan.get("intent", "clarify")
        if intent == "sleep":
            self.session.sleeping = True
            return self._finish(
                transcript,
                "sleep",
                1.0,
                plan.get("source", "followup"),
                "Going quiet.",
                should_continue=False,
            )
        if intent == "clarify" and not (plan.get("steps") or []):
            # Don't wipe pick/slot memory unless caller asked to
            if not plan.get("keep_awaiting") and not self.session.is_holding():
                self.session.clear_awaiting()
            elif plan.get("keep_awaiting") is False:
                self.session.clear_awaiting()
            return self._finish(
                transcript,
                "clarify",
                plan.get("confidence", 0.9),
                plan.get("source", "followup"),
                plan.get("reply") or "Could you rephrase that?",
                tool_ok=False,
            )
        if intent == "mail_summarize_blocked":
            return self._finish(
                transcript,
                "mail_summarize_blocked",
                1.0,
                plan.get("source", "followup"),
                "Authorize Gmail first: python main.py gmail-auth",
            )

        steps = plan.get("steps") or []
        # Skip "N steps" TTS for compound/OS plans — it delays the first action
        rapid_tools = {
            "open_app",
            "close_app",
            "close_apps",
            "hotkey",
            "volume_media",
            "type_text",
            "focus_window",
        }
        announce = (
            len(steps) >= 3
            and plan.get("source") in ("clause_plan", "gemini")
            and not all((s.get("tool") in rapid_tools) for s in steps)
        )
        if announce:
            try:
                self._speak(f"{len(steps)} steps.")
            except Exception:  # noqa: BLE001
                pass

        steps_run, reply, pending, tool_ok = self._run_plan_steps(plan)
        if pending:
            self.session.awaiting = "confirm"
            audit("confirm_required", {"transcript": transcript, "pending": pending, "reply": reply})
            return self._finish(
                transcript,
                intent,
                plan.get("confidence", 0.9),
                plan.get("source", "compound"),
                reply,
                steps_run=steps_run,
                used_planner=used_planner,
                pending=pending,
                tool_ok=True,  # speak confirm question, not failure closer
            )
        if not tool_ok:
            log_misroute(
                transcript,
                intent,
                plan.get("source", "compound"),
                confidence=float(plan.get("confidence") or 0),
                note=f"plan_fail:{reply[:120]}",
            )
        return self._finish(
            transcript,
            intent,
            plan.get("confidence", 0.9),
            plan.get("source", "compound"),
            reply,
            steps_run=steps_run,
            used_planner=used_planner,
            tool_ok=tool_ok,
        )

    def _run_plan_steps(
        self, plan: Dict[str, Any]
    ) -> tuple[List[Dict[str, Any]], str, Optional[Dict[str, Any]], bool]:
        steps_run: List[Dict[str, Any]] = []
        reply = plan.get("reply") or "Done."
        auto_type = bool(plan.get("auto_type"))
        all_ok = True
        steps_list = list(plan.get("steps") or [])
        default_gap = float(os.getenv("MARC_STEP_GAP", str(getattr(settings, "step_gap_s", 0.7) or 0.7)))
        for i, step in enumerate(steps_list):
            if getattr(self.session, "abort_plan", False):
                self.session.abort_plan = False
                self.session.pending_plan = None
                return steps_run, "Cancelled remaining steps.", None, all_ok
            if getattr(self.session, "plan_paused", False):
                rest = steps_list[i:]
                self.session.pending_plan = {
                    "intent": plan.get("intent", "multi_step"),
                    "steps": rest,
                    "reply": plan.get("reply") or "",
                    "source": plan.get("source") or "clause_plan",
                }
                return steps_run, f"Paused with {len(rest)} steps left. Say continue.", None, all_ok
            # Keep remaining visible for skip/cancel between turns if interrupted
            rest_after = steps_list[i + 1 :]
            if rest_after:
                self.session.pending_plan = {
                    "intent": plan.get("intent", "multi_step"),
                    "steps": rest_after,
                    "reply": plan.get("reply") or "",
                    "source": plan.get("source") or "clause_plan",
                }
            # Wait AFTER previous tool finished before starting this one (never before first)
            if i > 0:
                delay = float(step.get("delay") or 0)
                if delay <= 0 and len(steps_list) >= 2:
                    delay = default_gap
                if delay > 0:
                    time.sleep(delay)
            tool = step["tool"]
            args = dict(step.get("args") or {})
            # Inject spoken clock time for time+type compounds
            if (
                tool == "type_text"
                and (args.get("text") or "") == "__SPOKEN_TIME__"
            ):
                from datetime import datetime

                args["text"] = datetime.now().strftime("%I:%M %p").lstrip("0")
            need_confirm = step.get("confirm")
            if need_confirm is None:
                confirmed = auto_type and tool in ("type_text", "click_then_type")
            else:
                confirmed = not need_confirm
            if tool == "click_then_type":
                try:
                    self._speak("Click where to type.")
                except Exception:  # noqa: BLE001
                    pass
            if tool == "speak":
                msg = args.get("text") or ""
                try:
                    self._speak(msg)
                except Exception:  # noqa: BLE001
                    pass
                result = ToolResult(True, msg)
                steps_run.append({"tool": tool, "args": args, "result": result.to_dict()})
                continue
            if tool == "hotkey":
                confirmed = True
            t0 = time.perf_counter()
            result = self._exec_tool(tool, args, confirmed=confirmed)
            ms = int((time.perf_counter() - t0) * 1000)
            tr = {
                "tool": tool,
                "args": args,
                "result": result.to_dict(),
                "needs_confirm": result.needs_confirm,
                "ms": ms,
            }
            steps_run.append(tr)
            if result.needs_confirm:
                # Keep remaining steps so confirm doesn't wipe the multi-step queue
                remaining = list(plan.get("steps") or [])[len(steps_run) :]
                # steps_run already includes the confirming step; remaining = after current
                idx = len(steps_run) - 1
                rest = list(plan.get("steps") or [])[idx + 1 :]
                self.session.pending_plan = {
                    "intent": plan.get("intent", "clarify"),
                    "steps": rest,
                    "reply": plan.get("reply") or "",
                    "source": plan.get("source") or "compound",
                }
                self._pending = {
                    "tool": tool,
                    "args": args,
                    "intent": plan.get("intent", "clarify"),
                }
                return steps_run, result.message, self._pending, False
            audit("tool", {"tool": tool, "args": args, "result": result.to_dict(), "ms": ms})
            print(f"[marc] tool {tool} {ms}ms", flush=True)
            self._update_session_from_tool(tool, args, result)
            if result.ok:
                reply = result.message
            else:
                all_ok = False
                reply = result.message
                # Soft-continue for clause plans on non-fatal open failures
                if plan.get("source") == "clause_plan" and tool in (
                    "open_app",
                    "youtube_home",
                    "set_preferred_browser",
                ):
                    continue
                break
        if plan.get("reply") and all_ok:
            # Keep custom reply only if not youtube_search (persona handles awaiting)
            if plan.get("intent") not in ("youtube_search", "youtube_home", "web_search", "google_search"):
                reply = plan["reply"]
        if all_ok:
            self.session.pending_plan = None
            self.session.plan_paused = False
        return steps_run, reply, None, all_ok

    def _update_session_from_tool(self, tool: str, args: Dict[str, Any], result: ToolResult) -> None:
        if result.ok:
            self.session.last_tool = tool
        # Non-YouTube OS actions must leave sticky pick_video / last_results
        _CLEAR_PICK = {
            "open_app",
            "close_app",
            "close_apps",
            "type_text",
            "click_then_type",
            "whatsapp_send",
            "mail_search",
            "mail_summarize",
            "mail_compose",
            "mail_reply",
            "mail_send",
            "gmail_search",
            "camera_photo",
            "camera_record",
            "camera_stop",
            "camera_mode",
            "maps_search",
            "maps_directions",
            "drive_search",
            "drive_open",
            "calendar_list",
            "calendar_create",
            "set_reminder",
            "hotkey",
            "focus_window",
            "settings",
            "system_status",
            "volume_media",
        }
        if result.ok and tool in _CLEAR_PICK:
            # type_text clears YouTube pick sticky but stays in dictate slot for long content
            if tool in ("type_text", "click_then_type"):
                self.session.last_results = []
                if self.session.last_site in ("youtube", "google"):
                    self.session.last_site = ""
                self.session.last_search_query = ""
            else:
                self.session.clear_pick_context()

        if tool == "open_app":
            app = (args.get("app") or "").lower()
            self.session.last_app = app
            if app in ("youtube",):
                self.session.last_site = "youtube"
            elif app in ("gmail", "mail", "email"):
                self.session.last_site = "gmail"
            elif app in ("chrome", "brave", "edge", "browser"):
                self.session.last_site = "google"
            elif app in ("whatsapp",):
                self.session.last_site = "whatsapp"
            if app in ("brave", "chrome", "edge"):
                self.session.preferred_browser = app
                self.browser.set_preferred_browser(app)
        if tool == "web_search":
            eng = (args.get("engine") or "google").lower()
            data = result.data or {}
            results = data.get("results") or []
            q = data.get("query") or args.get("query") or ""
            if eng in ("youtube", "yt"):
                self.session.set_youtube_results(q, results)
                if not results:
                    self.session.last_site = "youtube"
                    self.session.last_search_query = q
                    self.session.awaiting = "none"
                    self.session.last_results = []
            else:
                if results:
                    self.session.set_results("google", q, results)
                else:
                    self.session.last_site = "google"
                    self.session.last_search_query = q
                    self.session.awaiting = "none"
                    self.session.last_results = []
        if tool == "youtube_search":
            data = result.data or {}
            results = data.get("results") or []
            q = data.get("query") or args.get("query") or ""
            self.session.set_youtube_results(q, results)
            if not results:
                self.session.last_site = "youtube"
                self.session.last_search_query = q
                self.session.awaiting = "none"
                self.session.last_results = []
        if tool == "youtube_home":
            data = result.data or {}
            results = data.get("results") or []
            self.session.set_results("youtube", data.get("query") or "home", results)
            if not results:
                self.session.last_site = "youtube"
                self.session.awaiting = "none"
                self.session.last_results = []
        if tool == "google_search":
            data = result.data or {}
            results = data.get("results") or []
            q = data.get("query") or args.get("query") or ""
            if results:
                self.session.set_results("google", q, results)
            else:
                self.session.last_site = "google"
                self.session.last_search_query = q
                self.session.awaiting = "none"
                self.session.last_results = []
        if tool == "youtube_play":
            self.session.last_site = "youtube"
            self.session.clear_awaiting()
        if tool == "open_url":
            if self.session.last_site == "google":
                self.session.clear_awaiting()
        if tool == "set_preferred_browser":
            name = (args.get("browser") or args.get("name") or "chrome").lower()
            self.session.preferred_browser = name
            self.browser.set_preferred_browser(name)
        if tool == "gmail_search":
            self.session.last_site = "gmail"
            self.session.last_search_query = args.get("query") or ""
        if tool == "mail_search":
            data = result.data or {}
            results = data.get("results") or []
            self.session.last_site = "gmail"
            self.session.last_search_query = data.get("query") or args.get("query") or ""
            self.session.last_mail_ids = [r.get("id") for r in results if r.get("id")]
            if results:
                self.session.awaiting = "pick_mail"
                self.session.last_results = [
                    VideoResult(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        index=i,
                    )
                    for i, r in enumerate(results)
                ]
            else:
                self.session.awaiting = "none"
        if tool == "mail_summarize":
            self.session.last_site = "gmail"
            self.session.last_summary = (result.data or {}).get("summary") or result.message
        if tool in ("type_text", "click_then_type"):
            if result.ok:
                chunk = args.get("text") or ""
                prev = self.session.last_typed or ""
                self.session.last_typed = (prev + (" " if prev and chunk else "") + chunk).strip()
                # Keep listening for more dictation until user says done/enter/open…
                self.session.awaiting = "slot:type_text"
                self.session.pending_prefix = ""
        if tool == "whatsapp_send":
            self.session.last_contact = args.get("contact") or ""
        if tool == "mail_compose":
            self.session.last_contact = args.get("to") or ""
        if tool == "hotkey" and (args.get("action") or "").lower() in ("enter", "return"):
            # After send, drop type memory so next "send" doesn't confuse
            pass

    def _exec_tool(self, tool: str, args: Dict[str, Any], confirmed: bool = False) -> ToolResult:
        tool = (tool or "").lower()
        if tool == "set_preferred_browser":
            name = (args.get("browser") or args.get("name") or "chrome").lower()
            self.session.preferred_browser = name
            self.browser.set_preferred_browser(name)
            return ToolResult(True, f"Preferred browser set to {name}.", {"browser": name})
        if tool == "youtube_search":
            return self.browser.youtube_search(args.get("query", ""))
        if tool == "youtube_home":
            return self.browser.youtube_home()
        if tool == "google_search":
            return self.browser.google_search(args.get("query", ""))
        if tool == "open_url":
            return self.browser.open_url(args.get("url", ""), args.get("title", ""))
        if tool == "play_nth":
            idx = int(args.get("index", 0) or 0)
            if not self.session.last_results or idx < 0 or idx >= len(self.session.last_results):
                return ToolResult(
                    False,
                    "I still don't have a result list. Try searching first.",
                )
            v = self.session.last_results[idx]
            if self.session.last_site in ("google", "gmail"):
                return self.browser.open_url(v.url, v.title)
            return self.browser.youtube_play(v.url, v.title)
        if tool == "youtube_play":
            return self.browser.youtube_play(args.get("url", ""), args.get("title", ""))
        if tool == "youtube_media":
            return self.browser.youtube_media(args.get("action", "play"))
        if tool in ("mail_search", "gmail_search"):
            from tools.gmail_api import get_gmail

            return get_gmail().search(args.get("query") or "in:inbox")
        if tool == "mail_summarize":
            from tools.gmail_api import get_gmail

            return get_gmail().summarize(
                query=args.get("query") or "is:unread",
                max_messages=int(args.get("max") or 5),
            )
        if tool == "mail_compose":
            from tools.gmail_api import get_gmail

            return get_gmail().compose(
                to=args.get("to") or "",
                subject=args.get("subject") or "",
                body=args.get("body") or args.get("message") or "",
                confirmed=confirmed,
                draft_id=args.get("draft_id") or "",
            )
        if tool == "mail_reply":
            from tools.gmail_api import get_gmail

            return get_gmail().reply(
                message_id=args.get("message_id") or args.get("id") or "",
                body=args.get("body") or args.get("message") or "Thanks, got it.",
                confirmed=confirmed,
            )
        if tool == "mail_send":
            from tools.gmail_api import get_gmail

            return get_gmail().compose(
                to=args.get("to") or "",
                subject=args.get("subject") or "",
                body=args.get("body") or "",
                confirmed=True,
                draft_id=args.get("draft_id") or "",
            )
        if tool in ("set_reminder", "set_alarm"):
            from tools.calendar_tools import set_reminder

            return set_reminder(
                text=args.get("text") or args.get("message") or "",
                when=args.get("when") or args.get("at") or "",
                minutes=args.get("minutes"),
            )
        if tool == "list_reminders":
            from tools.calendar_tools import list_reminders

            return list_reminders()
        if tool == "calendar_list":
            from tools.google_calendar_api import list_events

            return list_events(
                query=args.get("query") or "",
                max_results=int(args.get("max") or args.get("max_results") or 5),
                days=int(args.get("days") or 7),
            )
        if tool == "calendar_create":
            from tools.google_calendar_api import create_event

            return create_event(
                title=args.get("title") or args.get("text") or args.get("summary") or "",
                when=args.get("when") or args.get("at") or args.get("time") or "",
                duration_minutes=int(args.get("duration_minutes") or args.get("minutes") or 60),
                location=args.get("location") or "",
                description=args.get("description") or "",
                confirmed=confirmed,
            )
        if tool == "drive_search":
            from tools.google_drive_api import search_files

            return search_files(query=args.get("query") or args.get("name") or "")
        if tool == "drive_open":
            from tools.google_drive_api import open_file

            return open_file(
                file_id=args.get("file_id") or args.get("id") or "",
                url=args.get("url") or "",
            )
        if tool == "maps_search":
            from tools.google_maps_api import maps_search

            return maps_search(query=args.get("query") or args.get("place") or "")
        if tool == "maps_directions":
            from tools.google_maps_api import maps_directions

            return maps_directions(
                destination=args.get("destination") or args.get("to") or args.get("query") or "",
                origin=args.get("origin") or args.get("from") or "",
                mode=args.get("mode") or "driving",
            )
        if tool == "close_apps":
            apps = [a for a in (args.get("apps") or []) if a]
            if not apps:
                return ToolResult(False, "No apps to close.")
            last = ToolResult(True, "Done.")
            gap = min(1.0, float(getattr(settings, "step_gap_s", 2.5) or 2.5))
            for i, app in enumerate(apps):
                if i > 0:
                    time.sleep(gap)
                last = self.tools.execute("close_app", {"app": app}, confirmed=True)
            return last
        if tool == "web_search":
            eng = (args.get("engine") or "google").lower()
            q = args.get("query", "")
            if eng in ("youtube", "yt"):
                return self.browser.youtube_search(q)
            return self.browser.google_search(q)
        if tool == "gmail_search":
            return self.browser.gmail_search(args.get("query", ""))
        if tool == "gmail_open":
            return self.browser.gmail_open()
        if tool == "camera_photo":
            from tools.camera import get_camera

            result = get_camera().take_photo()
            if result.ok and (result.data or {}).get("path"):
                self.session.last_photo_path = str((result.data or {}).get("path") or "")
            return result
        if tool == "open_last_photo":
            from tools.camera import get_camera

            path = args.get("path") or getattr(self.session, "last_photo_path", "") or ""
            return get_camera().open_last_photo(path)
        if tool == "camera_record":
            from tools.camera import get_camera

            return get_camera().start_recording()
        if tool == "camera_stop":
            from tools.camera import get_camera

            return get_camera().stop_recording()
        if tool == "camera_mode":
            from tools.camera import get_camera

            return get_camera().set_mode(args.get("mode", "photo"), open_first=True)
        # Map open gmail through os tools (url apps)
        return self.tools.execute(tool, args, confirmed=confirmed)
