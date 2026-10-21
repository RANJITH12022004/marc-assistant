"""Wake-word spotting: openWakeWord (hey_jarvis) + STT phrases (hey marc).

Continuous InputStream feeds OWW while idle; on pause() the stream is closed
so command STT owns the mic. Speech-energy windows also run Google STT for
\"hey marc\" / \"remark\" so brand wake works without a custom ONNX.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from typing import Callable, Deque, Optional

import numpy as np

# hey_jarvis via openWakeWord; STT phrases for hey marc (+ remark alias, mark mishear)
_WAKE_PHRASES = re.compile(
    r"\b(hey\s+marc|okay\s+marc|ok\s+marc|hi\s+marc|"
    r"hey\s+mark|okay\s+mark|ok\s+mark|hi\s+mark|remark|"
    r"hey\s+jarvis|ok\s+jarvis|okay\s+jarvis)\b",
    re.I,
)

_FRAME = 1280  # ~80ms @ 16kHz — openWakeWord expected frame size
_SR = 16000


def _default_threshold() -> float:
    raw = os.environ.get("MARC_WAKE_THRESHOLD", "0.25")
    try:
        return max(0.05, min(0.95, float(raw)))
    except ValueError:
        return 0.25


class WakeListener:
    """Idle-mode wake detection with pause/resume so it never fights TTS/STT."""

    def __init__(
        self,
        on_wake: Optional[Callable[[], None]] = None,
        threshold: Optional[float] = None,
        wake_word: str = "jarvis",
    ) -> None:
        self.on_wake = on_wake
        self.threshold = float(threshold) if threshold is not None else _default_threshold()
        self.wake_word = (wake_word or "jarvis").strip().lower()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._paused.set()  # start paused until resume()
        self._thread: Optional[threading.Thread] = None
        self._model = None
        self._use_oww = False
        self._running = False
        self._cooldown_until = 0.0
        self._pcm_buf: Deque[np.ndarray] = deque(maxlen=40)  # ~3.2s of frames
        self._lock = threading.Lock()
        self._stt_busy = False
        self._last_stt_at = 0.0
        self._last_debug_at = 0.0
        self._max_score_seen = 0.0
        self._stream = None
        self._stream_lock = threading.Lock()

    def start(self) -> None:
        if self._running and self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._init_oww()
        self._thread = threading.Thread(target=self._run, daemon=True, name="marc-wake")
        self._thread.start()
        self._running = True
        if self._use_oww:
            mode = f"hey jarvis (openWakeWord @{self.threshold:.2f}) + STT hey marc"
        else:
            mode = "STT phrases only"
        print(
            f"[marc] Wake idle: say 'hey marc' or 'hey jarvis' ({mode})",
            flush=True,
        )

    def resume(self) -> None:
        self._paused.clear()

    def pause(self) -> None:
        self._paused.set()
        self._close_stream()

    def stop(self) -> None:
        self._paused.set()
        self._stop.set()
        self._close_stream()
        self._running = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.2)
        self._thread = None

    def _close_stream(self) -> None:
        with self._stream_lock:
            stream = self._stream
            self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass

    def _init_oww(self) -> None:
        try:
            from openwakeword.utils import download_models
            from openwakeword.model import Model

            try:
                download_models()
            except Exception as exc:  # noqa: BLE001
                print(f"[marc] openWakeWord model download note: {exc}", flush=True)
            # Free models: hey_jarvis only (no hey_marc ONNX)
            self._model = Model(wakeword_models=["hey_jarvis"])
            self._use_oww = True
        except Exception as exc:  # noqa: BLE001
            print(
                f"[marc] openWakeWord unavailable ({exc}); "
                "STT wake phrases still work; or install: pip install openwakeword onnxruntime",
                flush=True,
            )
            self._use_oww = False

    def _fire(self, reason: str = "") -> None:
        now = time.time()
        if now < self._cooldown_until:
            return
        self._cooldown_until = now + 2.0
        self.pause()
        suffix = f" ({reason})" if reason else ""
        print(f"[marc] wake word detected{suffix}", flush=True)
        if self.on_wake:
            self.on_wake()

    def _idle_wait(self) -> bool:
        while self._paused.is_set() and not self._stop.is_set():
            time.sleep(0.05)
        return not self._stop.is_set()

    def _run(self) -> None:
        import sounddevice as sd

        if self._use_oww and self._model is not None:
            self._run_dual_stream(sd)
        else:
            self._run_stt_only(sd)

    def _run_dual_stream(self, sd) -> None:
        """Open InputStream only while unpaused; close on pause so command STT owns mic."""
        frame = _FRAME
        sr = _SR

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                pass
            if self._paused.is_set() or self._stop.is_set():
                return
            if indata.ndim > 1 and indata.shape[1] > 1:
                mono = np.mean(indata, axis=1).copy()
            else:
                mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
            pcm = (np.clip(mono.flatten(), -1, 1) * 32767).astype(np.int16)
            if pcm.size < frame:
                return
            chunk = pcm[-frame:] if pcm.size >= frame else pcm
            with self._lock:
                self._pcm_buf.append(chunk.astype(np.float32) / 32767.0)
            try:
                preds = self._model.predict(chunk)
                best = 0.0
                for _name, score in (preds or {}).items():
                    best = max(best, float(score))
                    if float(score) >= self.threshold:
                        self._fire(f"oww score={float(score):.2f}")
                        return
                self._max_score_seen = max(self._max_score_seen, best)
            except Exception as exc:  # noqa: BLE001
                now = time.time()
                if now - self._last_debug_at > 5.0:
                    print(f"[marc] wake oww error: {exc}", flush=True)
                    self._last_debug_at = now

        try:
            while not self._stop.is_set():
                if not self._idle_wait():
                    return
                # Open mic only while idle/unpaused
                self._close_stream()
                try:
                    # Stereo mix when available — Senary array mono channel is often dead
                    from voice.audio_io import input_device_index

                    max_ch = 1
                    dev = input_device_index()
                    try:
                        qdev = sd.query_devices(dev if dev is not None else sd.default.device[0])
                        max_ch = int(qdev["max_input_channels"])
                    except Exception:  # noqa: BLE001
                        max_ch = 1
                    stream = sd.InputStream(
                        samplerate=sr,
                        channels=2 if max_ch >= 2 else 1,
                        dtype="float32",
                        blocksize=frame,
                        device=dev,
                        callback=callback,
                    )
                    stream.start()
                    with self._stream_lock:
                        self._stream = stream
                except Exception as exc:  # noqa: BLE001
                    print(f"[marc] wake stream open failed: {exc}", flush=True)
                    time.sleep(0.5)
                    continue

                while not self._stop.is_set() and not self._paused.is_set():
                    now = time.time()
                    if now - self._last_debug_at > 15.0 and self._max_score_seen > 0:
                        print(
                            f"[marc] wake oww peak={self._max_score_seen:.2f} "
                            f"(need >={self.threshold:.2f})",
                            flush=True,
                        )
                        self._max_score_seen = 0.0
                        self._last_debug_at = now
                    if (
                        not self._stt_busy
                        and not self._paused.is_set()
                        and now - self._last_stt_at >= 1.8
                    ):
                        self._maybe_stt_wake()
                    time.sleep(0.08)

                # Paused or stopping — release mic for command STT
                self._close_stream()
                with self._lock:
                    self._pcm_buf.clear()
        except Exception as exc:  # noqa: BLE001
            print(f"[marc] wake stream failed ({exc}); falling back to STT-only", flush=True)
            self._close_stream()
            self._run_stt_only(sd)

    def _maybe_stt_wake(self) -> None:
        with self._lock:
            frames = list(self._pcm_buf)
        if len(frames) < 8:
            return
        audio = np.concatenate(frames[-20:])  # ~1.6s
        rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
        if rms < 0.02:
            return
        self._stt_busy = True
        self._last_stt_at = time.time()

        def worker() -> None:
            try:
                if self._paused.is_set() or self._stop.is_set():
                    return
                text = self._stt_chunk(audio, _SR)
                if text and _WAKE_PHRASES.search(text):
                    print(f"[marc] wake heard: {text!r}", flush=True)
                    self._fire(f"stt {text!r}")
                # Ignore non-wake transcripts while idle (no spam log)
            finally:
                self._stt_busy = False

        threading.Thread(target=worker, daemon=True, name="marc-wake-stt").start()

    def _run_stt_only(self, sd) -> None:
        sr = _SR
        while not self._stop.is_set():
            if not self._idle_wait():
                return
            try:
                probe = sd.rec(int(0.25 * sr), samplerate=sr, channels=1, dtype="float32")
                sd.wait()
                if self._paused.is_set() or self._stop.is_set():
                    continue
                rms = float(np.sqrt(np.mean(np.square(probe))))
                if rms < 0.03:
                    time.sleep(0.4)
                    continue
                chunk = sd.rec(int(1.5 * sr), samplerate=sr, channels=1, dtype="float32")
                sd.wait()
                if self._paused.is_set() or self._stop.is_set():
                    continue
                text = self._stt_chunk(chunk, sr)
                if text and _WAKE_PHRASES.search(text):
                    print(f"[marc] wake heard: {text!r}", flush=True)
                    self._fire(f"stt {text!r}")
                else:
                    time.sleep(0.5)
            except Exception as exc:  # noqa: BLE001
                print(f"[marc] wake stt error: {exc}", flush=True)
                time.sleep(0.8)

    def _stt_chunk(self, audio: np.ndarray, sr: int) -> str:
        import tempfile
        import wave
        from pathlib import Path

        flat = np.clip(audio.flatten(), -1, 1)
        peak = float(np.max(np.abs(flat))) if flat.size else 0.0
        if 0.01 < peak < 0.35:
            flat = np.clip(flat * (0.45 / peak), -1, 1)
        pcm = (flat * 32767).astype(np.int16)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = Path(f.name)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())
        try:
            import speech_recognition as sr_mod

            r = sr_mod.Recognizer()
            with sr_mod.AudioFile(str(path)) as source:
                audio_data = r.record(source)
            return r.recognize_google(audio_data)
        except Exception:  # noqa: BLE001
            return ""
        finally:
            path.unlink(missing_ok=True)
