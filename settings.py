"""Central settings for Marc laptop assistant."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example", override=False)


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    laya_model_path: Path = Path(os.getenv("LAYA_MODEL_PATH", r"E:\laya-models"))
    laya_marc_intent_path: Path = Path(
        os.getenv("LAYA_MARC_INTENT_PATH", r"E:\laya-models\marc-intent")
    )
    confidence_threshold: float = float(os.getenv("LAYA_CONFIDENCE_THRESHOLD", "0.85"))
    quiet_mode: bool = os.getenv("MARC_QUIET_MODE", "false").lower() in ("1", "true", "yes")
    # unclear_only (default): Gemini only for clarify/chat/needs_planner multi-step
    # always: legacy planner triggers; off: never call Gemini
    gemini_mode: str = (os.getenv("MARC_GEMINI_MODE") or "unclear_only").strip().lower()
    mail_gemini: bool = os.getenv("MARC_MAIL_GEMINI", "false").lower() in ("1", "true", "yes")
    step_gap_s: float = float(os.getenv("MARC_STEP_GAP", "0.7"))
    # Skip spoken closers for instant OS actions (island + console only)
    silent_rapid: bool = os.getenv("MARC_SILENT_RAPID", "true").lower() in ("1", "true", "yes")
    ptt_hotkey: str = os.getenv("MARC_PTT_HOTKEY", "ctrl+shift+m")
    whisper_model: str = os.getenv("MARC_WHISPER_MODEL", "base")
    whisper_device: str = os.getenv("MARC_WHISPER_DEVICE", "cpu")
    tts_voice: str = os.getenv("MARC_TTS_VOICE", "en-US-GuyNeural")
    audit_log: Path = Path(
        os.getenv("MARC_AUDIT_LOG", str(ROOT / "data" / "logs" / "audit.jsonl"))
    )
    use_multilingual: bool = os.getenv("MARC_USE_MULTILINGUAL", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    # Free / Basic default: Flash-Lite (override with GEMINI_MODEL)
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    gemini_timeout: float = float(os.getenv("GEMINI_TIMEOUT", "45"))
    google_maps_api_key: str = (
        os.getenv("GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or ""
    )
    wake_threshold: float = float(os.getenv("MARC_WAKE_THRESHOLD", "0.25"))
    audio_device: str = (os.getenv("MARC_AUDIO_DEVICE") or "").strip()
    apps_config: Path = ROOT / "config" / "apps.json"
    hotkeys_config: Path = ROOT / "config" / "hotkeys.json"
    file_roots: tuple[Path, ...] = (
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        Path.home() / "Documents",
    )


settings = Settings()
