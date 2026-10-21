"""Load Laya from SD card and classify Marc intents."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

# Prefer the local laya clone + venv packages
_LAYA_REPO = Path(r"C:\Users\ranjith\laya")
if _LAYA_REPO.exists() and str(_LAYA_REPO) not in sys.path:
    sys.path.insert(0, str(_LAYA_REPO))

from laya_router.intents import INTENT_LABELS, marc_intent_questions, state_from_transcript
from settings import settings


@dataclass
class IntentResult:
    intent: str
    confidence: float
    needs_planner: float
    destructive: float
    raw: Dict[str, Any]
    source: str  # "laya" | "rules" | "fallback"

    @property
    def needs_planner_bool(self) -> bool:
        return self.needs_planner >= 0.5

    @property
    def destructive_bool(self) -> bool:
        return self.destructive >= 0.5


class MarcLayaRouter:
    """System-1 router backed by local Laya weights (with rule fallback)."""

    def __init__(
        self,
        model_path: Optional[Path] = None,
        use_multilingual: Optional[bool] = None,
        preload: bool = True,
        rules_only: bool = False,
    ) -> None:
        self.model_path = Path(model_path or settings.laya_model_path)
        self.use_multilingual = (
            settings.use_multilingual if use_multilingual is None else use_multilingual
        )
        self.rules_only = rules_only
        self._agent = None
        self._load_error: Optional[str] = None
        if preload and not rules_only:
            self._ensure_agent()

    def _resolve_path(self) -> Path:
        marc_intent = settings.laya_marc_intent_path
        if (marc_intent / "model.safetensors").exists() or (
            marc_intent / "rl_agent_config.json"
        ).exists():
            return marc_intent
        return self.model_path

    def _ensure_agent(self):
        if self.rules_only:
            return None
        if self._agent is not None:
            return self._agent
        try:
            import laya

            path = self._resolve_path()
            subfolder = None
            if self.use_multilingual and path == self.model_path:
                subfolder = "multilingual"
            print(f"[marc] loading Laya from {path}" + (f"/{subfolder}" if subfolder else ""))
            self._agent = laya.load(str(path), subfolder=subfolder)
            return self._agent
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            print(f"[marc] Laya load failed ({exc}); rule fallback only")
            return None

    def classify(self, transcript: str) -> IntentResult:
        if self.rules_only:
            from laya_router.rules import rule_classify

            intent, conf = rule_classify(transcript)
            return IntentResult(
                intent=intent,
                confidence=conf,
                needs_planner=0.7 if intent in ("chat", "clarify") else 0.2,
                destructive=0.9 if intent == "refuse" else 0.05,
                raw={},
                source="rules",
            )
        # Non-blocking: use rules until background (or prior) load finishes
        agent = self._agent
        if agent is None:
            from laya_router.rules import rule_classify

            intent, conf = rule_classify(transcript)
            return IntentResult(
                intent=intent,
                confidence=conf,
                needs_planner=0.7 if intent in ("chat", "clarify") else 0.2,
                destructive=0.9 if intent == "refuse" else 0.05,
                raw={"pending_laya": True, "error": self._load_error},
                source="rules",
            )

        state = state_from_transcript(transcript)
        questions = marc_intent_questions()
        try:
            result = agent.predict(state, questions)
            answers = result.get("answers", {})
            intent_ans = answers.get("intent", {})
            intent = intent_ans.get("choice") or "clarify"
            if intent not in INTENT_LABELS:
                intent = "clarify"
            conf = float(intent_ans.get("confidence", 0.0) or 0.0)
            needs = float(answers.get("needs_planner", {}).get("noul", 0.5) or 0.5)
            destr = float(answers.get("destructive", {}).get("noul", 0.0) or 0.0)

            # Safety + pre-finetune policy: high-confidence rules win (esp. refuse).
            # Flip off when marc_finetune_meta.json has "trained": true after RLCD.
            from laya_router.rules import rule_classify

            rule_intent, rule_conf = rule_classify(transcript)
            trained = False
            try:
                import json
                from settings import settings as _settings

                meta_path = _settings.laya_marc_intent_path / "marc_finetune_meta.json"
                if meta_path.exists():
                    trained = bool(json.loads(meta_path.read_text(encoding="utf-8")).get("trained"))
            except Exception:  # noqa: BLE001
                trained = False

            prefer_rules = (not trained) and rule_conf >= 0.85
            force_refuse = rule_intent == "refuse" and rule_conf >= 0.85
            if force_refuse or (prefer_rules and rule_intent != intent):
                return IntentResult(
                    intent=rule_intent,
                    confidence=rule_conf,
                    needs_planner=0.7 if rule_intent in ("chat", "clarify") else 0.2,
                    destructive=0.9 if rule_intent == "refuse" else float(destr),
                    raw={"laya": result, "blended": True, "trained": trained},
                    source="hybrid",
                )

            return IntentResult(
                intent=intent,
                confidence=conf,
                needs_planner=needs,
                destructive=destr,
                raw=result,
                source="laya",
            )
        except Exception as exc:  # noqa: BLE001
            from laya_router.rules import rule_classify

            intent, conf = rule_classify(transcript)
            return IntentResult(
                intent=intent,
                confidence=conf,
                needs_planner=0.5,
                destructive=0.05,
                raw={"predict_error": str(exc)},
                source="fallback",
            )


__all__ = ["MarcLayaRouter", "IntentResult"]
