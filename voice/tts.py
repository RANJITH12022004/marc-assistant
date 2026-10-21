"""Text-to-speech — Windows SAPI (offline, no login)."""
from __future__ import annotations

import threading
from typing import Optional

from settings import settings


class TextToSpeech:
    def __init__(self, voice: Optional[str] = None) -> None:
        self.voice = voice or settings.tts_voice
        self._engine = None
        self._sapi = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def stop(self) -> None:
        """Best-effort interrupt of current speech (Esc abort)."""
        self._stop.set()
        try:
            if self._sapi is not None:
                self._sapi.Speak("", 2)  # SVSFPurgeBeforeSpeak
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._engine is not None:
                self._engine.stop()
        except Exception:  # noqa: BLE001
            pass

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        spoken = text if len(text) < 280 else text[:277] + "..."
        print(f"[marc] TTS: {spoken}", flush=True)
        self._stop.clear()
        with self._lock:
            # In-process SAPI — no PowerShell window, no hung child process
            try:
                self._speak_sapi(spoken)
                return
            except Exception as exc:  # noqa: BLE001
                print(f"[marc] SAPI failed ({exc}); trying pyttsx3", flush=True)
            try:
                self._speak_pyttsx3(spoken)
            except Exception as exc2:  # noqa: BLE001
                print(f"[marc] TTS failed: {exc2}", flush=True)

    def _speak_sapi(self, text: str) -> None:
        import win32com.client

        if self._sapi is None:
            self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
        if self._stop.is_set():
            return
        # 0 = default (sync). Keep sync so voice loop knows when speaking ends.
        self._sapi.Speak(text, 0)

    def _speak_pyttsx3(self, text: str) -> None:
        import pyttsx3

        # Fresh engine each call — reused engines often hang after stop()/threads
        engine = pyttsx3.init()
        self._engine = engine
        try:
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
        finally:
            try:
                engine.stop()
            except Exception:  # noqa: BLE001
                pass
            self._engine = None
