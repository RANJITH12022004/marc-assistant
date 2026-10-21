"""Speech-to-text — free Google primary; Whisper when loud+empty or opt-in.

CRITICAL: Do NOT fall back to Whisper on quiet UnknownValueError (ambient noise).
That path loads a ~140–300MB CPU model and freezes the UI.
Exception: Google returns empty/UnknownValue AND real speech peak is present
→ try Whisper once (plan Phase 1).
"""
from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from settings import settings
from voice.audio_io import record_mono, record_vad_mono

# Opt-in always-on Whisper fallback (heavy). Default off.
_WHISPER_FALLBACK = os.getenv("MARC_WHISPER_FALLBACK", "false").lower() in (
    "1",
    "true",
    "yes",
)
# Real speech peak (float32) before AGC — NOT post-AGC PCM RMS
_SPEECH_PEAK = float(os.getenv("MARC_SPEECH_PEAK", "0.012"))
# Soft AGC only when speech is quiet but real
_AGC_MIN_PEAK = float(os.getenv("MARC_AGC_MIN_PEAK", "0.02"))
_AGC_MAX_PEAK = float(os.getenv("MARC_AGC_MAX_PEAK", "0.30"))
# Energy VAD: end listen after silence (default on)
_VAD = os.getenv("MARC_VAD", "true").lower() in ("1", "true", "yes")
_VAD_SILENCE_MS = float(os.getenv("MARC_VAD_SILENCE_MS", "900"))
# Longer pause tolerance while dictating / type-slot follow-up
_VAD_DICTATE_SILENCE_MS = float(os.getenv("MARC_VAD_DICTATE_SILENCE_MS", "1800"))
_DICTATE_MAX_S = float(os.getenv("MARC_DICTATE_MAX_S", "25"))
_DEBUG_WAV = os.getenv("MARC_DEBUG_STT", "false").lower() in ("1", "true", "yes")


class SpeechToText:
    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        prefer: str = "google",
    ) -> None:
        self.model_size = model_size or settings.whisper_model
        self.device = device or settings.whisper_device
        self.prefer = (prefer or "google").lower()
        self._whisper = None
        self._last_rms = 0.0
        self._last_peak = 0.0

    def record_wav(
        self,
        seconds: float = 4.0,
        samplerate: int = 16000,
        silence_ms: Optional[float] = None,
        cancel=None,
    ) -> Path:
        sil = float(silence_ms) if silence_ms is not None else _VAD_SILENCE_MS
        # Always allow VAD for dictate (even short max) so pauses can end early
        use_vad = _VAD and (seconds >= 2.0 or silence_ms is not None)
        if use_vad:
            audio, sr, peak = record_vad_mono(
                max_seconds=seconds,
                target_sr=samplerate,
                silence_ms=sil,
                speech_peak=_SPEECH_PEAK,
                cancel=cancel,
            )
        else:
            print(f"[marc] Listening for {seconds:.0f}s — speak now...", flush=True)
            try:
                print("\a", end="", flush=True)
            except Exception:  # noqa: BLE001
                pass
            audio, sr, peak = record_mono(
                seconds=seconds, target_sr=samplerate, cancel=cancel
            )
        return self._write_wav(audio, sr, peak)

    def _write_wav(self, audio, samplerate: int, peak: float = 0.0) -> Path:
        flat = np.clip(np.asarray(audio, dtype=np.float32).flatten(), -1.0, 1.0)
        if peak <= 0.0 and flat.size:
            peak = float(np.max(np.abs(flat)))
        self._last_peak = peak

        # Soft AGC only for quiet-but-real speech — never boost mic-floor noise
        if _AGC_MIN_PEAK <= peak < _AGC_MAX_PEAK:
            flat = np.clip(flat * (0.40 / peak), -1.0, 1.0)

        pcm = (flat * 32767.0).astype(np.int16)
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if pcm.size else 0.0
        self._last_rms = rms
        print(
            f"[marc] recorded (peak={peak:.4f} rms={rms:.0f})",
            flush=True,
        )
        if peak < _SPEECH_PEAK:
            print(
                "[marc] WARNING: mic nearly silent — check Windows mic privacy, "
                "unmute Mic Array, or set MARC_AUDIO_DEVICE to your headset index",
                flush=True,
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = Path(f.name)
        with wave.open(str(tmp), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            wf.writeframes(pcm.tobytes())
        if _DEBUG_WAV or peak < _SPEECH_PEAK:
            try:
                dbg = Path(__file__).resolve().parents[1] / "data" / "debug_last_stt.wav"
                dbg.parent.mkdir(parents=True, exist_ok=True)
                dbg.write_bytes(tmp.read_bytes())
            except Exception:  # noqa: BLE001
                pass
        return tmp

    def transcribe_google(self, path: Path) -> str:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        with sr.AudioFile(str(path)) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio)

    def _ensure_whisper(self):
        if self._whisper is not None:
            return self._whisper
        from faster_whisper import WhisperModel

        print(
            f"[marc] loading Whisper {self.model_size} on {self.device} "
            "(heavy — may spike CPU/RAM)...",
            flush=True,
        )
        self._whisper = WhisperModel(
            self.model_size, device=self.device, compute_type="int8"
        )
        return self._whisper

    def transcribe_whisper(self, path: Path) -> str:
        model = self._ensure_whisper()
        # Short command clips + Silero VAD often wipe the whole file → empty.
        segments, info = model.transcribe(
            str(path),
            beam_size=1,
            vad_filter=False,
            language="en",
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if not text:
            # Second pass without language lock (accents / code-switch)
            segments, info = model.transcribe(
                str(path),
                beam_size=1,
                vad_filter=False,
                no_speech_threshold=0.5,
                condition_on_previous_text=False,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
        if not text:
            try:
                with wave.open(str(path), "rb") as wf:
                    dur = wf.getnframes() / float(wf.getframerate() or 1)
            except Exception:  # noqa: BLE001
                dur = -1.0
            print(
                f"[marc] STT whisper empty "
                f"(dur={dur:.1f}s peak={self._last_peak:.4f} lang={getattr(info, 'language', '?')})",
                flush=True,
            )
        return text

    def _try_whisper(self, path: Path, reason: str) -> str:
        try:
            text = self.transcribe_whisper(path)
            print(f"[marc] STT backend: whisper ({reason})", flush=True)
            return (text or "").strip()
        except Exception as exc:  # noqa: BLE001
            print(f"[marc] STT whisper failed: {type(exc).__name__}: {exc}", flush=True)
            return ""

    def record_and_transcribe(
        self,
        seconds: float = 4.0,
        samplerate: int = 16000,
        silence_ms: Optional[float] = None,
        cancel=None,
    ) -> str:
        text, _rms = self.record_and_transcribe_ex(
            seconds=seconds, samplerate=samplerate, silence_ms=silence_ms, cancel=cancel
        )
        return text

    def record_and_transcribe_ex(
        self,
        seconds: float = 4.0,
        samplerate: int = 16000,
        silence_ms: Optional[float] = None,
        cancel=None,
    ) -> Tuple[str, float]:
        """Return (transcript, rms). Empty string = no usable speech (not an error)."""
        path = self.record_wav(
            seconds=seconds, samplerate=samplerate, silence_ms=silence_ms, cancel=cancel
        )
        rms = getattr(self, "_last_rms", 0.0)
        peak = getattr(self, "_last_peak", 0.0)
        if cancel is not None and cancel():
            return "", rms
        try:
            if peak < _SPEECH_PEAK * 0.5:
                print("[marc] STT skip: too quiet (mic)", flush=True)
                return "", rms

            if self.prefer == "whisper":
                text = self._try_whisper(path, "local")
                return text, rms

            # Google primary
            try:
                text = self.transcribe_google(path)
                text = (text or "").strip()
                if text:
                    print("[marc] STT backend: google (free, no login)", flush=True)
                    return text, rms
                if peak >= _SPEECH_PEAK:
                    print(
                        f"[marc] STT google empty + speech (peak={peak:.3f}) → Whisper",
                        flush=True,
                    )
                    return self._try_whisper(path, "empty+speech"), rms
                print("[marc] STT google: empty transcript", flush=True)
                return "", rms
            except Exception as exc:  # noqa: BLE001
                name = type(exc).__name__
                if name == "UnknownValueError" or "UnknownValue" in name:
                    if peak >= _SPEECH_PEAK:
                        print(
                            f"[marc] STT google UnknownValue + speech "
                            f"(peak={peak:.3f}) → Whisper",
                            flush=True,
                        )
                        return self._try_whisper(path, "empty+speech"), rms
                    print(
                        "[marc] STT google: no speech understood (not falling back to Whisper)",
                        flush=True,
                    )
                    return "", rms
                print(f"[marc] STT google failed: {name}: {exc}", flush=True)
                if _WHISPER_FALLBACK or self.prefer == "whisper":
                    return self._try_whisper(path, "fallback"), rms
                return "", rms
        finally:
            path.unlink(missing_ok=True)
