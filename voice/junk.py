"""Reject ambient / hallucinated STT before it hits the orchestrator."""
from __future__ import annotations

import os
import re
from typing import Optional, Tuple

# Confirm / cancel tokens — never treat as junk when a confirm is pending
_CONFIRM_OR_CANCEL = re.compile(
    r"^\s*(yes|y|yeah|yep|confirm|ok|okay|do it|go ahead|sure|"
    r"no|n|cancel|never mind|nevermind|forget it)\s*\.?\s*$",
    re.I,
)

# Filler / ambient patterns that should be ignored (no Gemini)
# Note: ok/yeah/yep removed — those are valid confirms when pending
_JUNK = re.compile(
    r"^\s*("
    r"hmm+|uh+|um+|ah+|"
    r"(?:you\s+)?can\s+hear\s+(?:it|that|me|this)|"
    r"i\s+can\s+hear\s+it|"
    r"now\.?|"
    r"if\s+you\s+want\s+to\s+get\s+a\s+banana|"
    r"you\s+know\s+that\s+side\s+of\s+the\s+panel|"
    r"i'?m\s+going\s+to\s+take\s+the\s+neck|"
    r"i\s+can'?t\s+do\s+it|"
    r"some\??\s*no,?\s*i'?m\s+back\s+in\s+the\s+car\.?|"
    r"there\s+needs\s+to\s+be\s+a\s+way\s+to\s+make\s+it\s+work\.?|"
    r"thank\s+you\.?|"
    r"subscribe\.?|"
    r"thanks\s+for\s+watching\.?"
    r")\s*$",
    re.I,
)


_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")

# Align with STT speech peak — post-AGC RMS is a poor quietness gate
_SPEECH_PEAK = float(os.getenv("MARC_SPEECH_PEAK", "0.012"))


def is_junk_transcript(
    text: str,
    rms: float = 999.0,
    allow_confirm: bool = False,
    peak: Optional[float] = None,
) -> Tuple[bool, str]:
    """Return (is_junk, reason).

    Prefer float peak (pre-AGC) over PCM RMS for too_quiet — soft speech often
    has low post-AGC RMS while peak still shows real energy.
    """
    t = (text or "").strip()
    if not t:
        return True, "empty"
    # Peak gate: only drop when we know energy was below speech floor
    if peak is not None and peak < _SPEECH_PEAK and rms < 40:
        return True, "too_quiet"
    # Legacy RMS-only path when peak unknown — use a softer floor
    if peak is None and rms < 40:
        return True, "too_quiet"
    if allow_confirm and _CONFIRM_OR_CANCEL.match(t):
        return False, ""
    # Bare ok/yeah without pending confirm — still ignore as filler
    if not allow_confirm and re.match(r"^\s*(ok|okay|yeah|yep)\s*\.?\s*$", t, re.I):
        return True, "filler"
    if _JUNK.match(t):
        return True, "filler"
    if _HANGUL.search(t) or _CJK.search(t):
        return True, "non_english"
    if len(t) > 220:
        return True, "too_long"
    return False, ""
