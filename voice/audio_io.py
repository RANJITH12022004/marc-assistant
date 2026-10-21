"""Reliable mic capture for Marc on Windows (Senary / array mics).

Root issues this fixes:
- sd.rec sometimes returns NaN / huge floats on Senary → fake loud RMS, empty Whisper
- Forcing mono @ 16 kHz on a 44.1 kHz array often garbles speech
- Prefer device-native rate + stereo mixdown, sanitize, then resample to 16 kHz
"""
from __future__ import annotations

import os
import time
from typing import Optional, Tuple

import numpy as np


def input_device_index() -> Optional[int]:
    """Resolve MARC_AUDIO_DEVICE (int index or substring of device name)."""
    import sounddevice as sd

    raw = (os.getenv("MARC_AUDIO_DEVICE") or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    needle = raw.lower()
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if int(d.get("max_input_channels") or 0) < 1:
                continue
            name = str(d.get("name") or "").lower()
            if needle in name:
                return int(i)
    except Exception:  # noqa: BLE001
        pass
    return None


def list_input_devices() -> list:
    """Return [(index, name, max_in_channels), ...] for logging."""
    import sounddevice as sd

    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            ch = int(d.get("max_input_channels") or 0)
            if ch < 1:
                continue
            out.append((i, str(d.get("name") or f"device-{i}"), ch))
    except Exception:  # noqa: BLE001
        pass
    return out


def pick_live_input(min_peak: float = 1e-4, probe_s: float = 0.25) -> Optional[int]:
    """Probe inputs and return the index with the highest peak above min_peak."""
    import sounddevice as sd

    preferred = input_device_index()
    candidates: list[int] = []
    if preferred is not None:
        candidates.append(preferred)
    try:
        default = sd.default.device
        try:
            candidates.append(int(default[0]))
        except Exception:  # noqa: BLE001
            candidates.append(int(default))
    except Exception:  # noqa: BLE001
        pass
    for i, _name, _ch in list_input_devices():
        if i not in candidates:
            candidates.append(i)

    best_idx: Optional[int] = None
    best_peak = 0.0
    for idx in candidates[:8]:
        try:
            _audio, _sr, peak = record_mono(seconds=probe_s, target_sr=16000, device=idx)
            print(f"[marc] mic probe device={idx} peak={peak:.5f}", flush=True)
            if peak > best_peak:
                best_peak = peak
                best_idx = idx
        except Exception as exc:  # noqa: BLE001
            print(f"[marc] mic probe device={idx} failed: {exc}", flush=True)
    if best_idx is not None and best_peak >= min_peak:
        os.environ["MARC_AUDIO_DEVICE"] = str(best_idx)
        return best_idx
    return preferred if preferred is not None else best_idx


def _device_info(device: Optional[int] = None):
    import sounddevice as sd

    idx = device if device is not None else input_device_index()
    if idx is None:
        default = sd.default.device
        try:
            idx = int(default[0])  # _InputOutputPair or (in, out)
        except Exception:  # noqa: BLE001
            idx = int(default)
    info = sd.query_devices(int(idx), kind="input")
    return int(idx), info


def sanitize_audio(audio: np.ndarray) -> np.ndarray:
    """Clip to [-1,1] and zero non-finite samples (Senary PortAudio glitches)."""
    arr = np.asarray(audio, dtype=np.float32)
    bad = ~np.isfinite(arr)
    if bad.any():
        arr = arr.copy()
        arr[bad] = 0.0
    return np.clip(arr, -1.0, 1.0)


def resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    audio = sanitize_audio(audio).reshape(-1)
    if src_sr == dst_sr or audio.size == 0:
        return audio
    try:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(int(src_sr), int(dst_sr))
        out = resample_poly(audio, int(dst_sr) // g, int(src_sr) // g)
        return sanitize_audio(out).reshape(-1)
    except Exception:  # noqa: BLE001
        n = max(1, int(round(len(audio) * float(dst_sr) / float(src_sr))))
        x = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        xi = np.linspace(0.0, 1.0, num=n, endpoint=False)
        return sanitize_audio(np.interp(xi, x, audio.astype(np.float64))).reshape(-1)


def _to_mono(arr: np.ndarray) -> np.ndarray:
    arr = sanitize_audio(arr)
    if arr.ndim == 2 and arr.shape[1] > 1:
        return np.mean(arr, axis=1)
    return arr.reshape(-1)


def record_mono(
    seconds: float = 4.0,
    target_sr: int = 16000,
    device: Optional[int] = None,
    cancel=None,
) -> Tuple[np.ndarray, int, float]:
    """Record mono float32 at target_sr. Returns (audio, sr, peak)."""
    import sounddevice as sd

    idx, info = _device_info(device)
    native_sr = int(info.get("default_samplerate") or target_sr)
    max_ch = int(info.get("max_input_channels") or 1)
    channels = 2 if max_ch >= 2 else 1

    frames = max(1, int(seconds * native_sr))
    # InputStream is more stable than sd.rec on Senary when other streams just closed
    chunks: list[np.ndarray] = []
    try:
        with sd.InputStream(
            samplerate=native_sr,
            channels=channels,
            dtype="float32",
            device=idx,
            blocksize=0,
        ) as stream:
            # brief settle after stream open
            time.sleep(0.05)
            got = 0
            while got < frames:
                if cancel is not None and cancel():
                    break
                need = min(frames - got, native_sr // 5)  # ≤200ms blocks
                data, overflowed = stream.read(need)
                if overflowed:
                    pass
                mono = _to_mono(data)
                chunks.append(mono)
                got += mono.shape[0]
    except Exception:
        # Fallback
        audio = sd.rec(
            frames,
            samplerate=native_sr,
            channels=channels,
            dtype="float32",
            device=idx,
        )
        sd.wait()
        chunks = [_to_mono(audio)]

    mono = np.concatenate(chunks) if chunks else np.zeros(int(0.4 * native_sr), dtype=np.float32)
    mono = sanitize_audio(mono)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if not np.isfinite(peak):
        peak = 0.0
    out = resample(mono, native_sr, target_sr)
    return out, target_sr, peak


def record_vad_mono(
    max_seconds: float = 8.0,
    target_sr: int = 16000,
    silence_ms: float = 700.0,
    speech_peak: float = 0.012,
    device: Optional[int] = None,
    cancel=None,
) -> Tuple[np.ndarray, int, float]:
    """Block-record at native rate with energy VAD; return 16 kHz mono."""
    import sounddevice as sd

    idx, info = _device_info(device)
    native_sr = int(info.get("default_samplerate") or target_sr)
    max_ch = int(info.get("max_input_channels") or 1)
    channels = 2 if max_ch >= 2 else 1
    block_ms = 50.0
    block = max(1, int(native_sr * block_ms / 1000.0))
    chunks: list[np.ndarray] = []
    speech_seen = False
    silent_ms = 0.0
    max_blocks = int(max_seconds / (block_ms / 1000.0))
    peak_all = 0.0

    with sd.InputStream(
        samplerate=native_sr,
        channels=channels,
        dtype="float32",
        device=idx,
        blocksize=block,
    ) as stream:
        time.sleep(0.05)
        for _ in range(max_blocks):
            if cancel is not None and cancel():
                break
            data, _overflowed = stream.read(block)
            mono = _to_mono(data)
            chunks.append(mono.copy())
            peak = float(np.max(np.abs(mono))) if mono.size else 0.0
            if not np.isfinite(peak):
                peak = 0.0
            peak_all = max(peak_all, peak)
            rms = float(np.sqrt(np.mean(mono**2))) if mono.size else 0.0
            if not np.isfinite(rms):
                rms = 0.0
            if peak >= speech_peak or rms >= speech_peak * 0.35:
                speech_seen = True
                silent_ms = 0.0
            elif speech_seen:
                silent_ms += block_ms
                if silent_ms >= silence_ms:
                    break

    if not chunks:
        audio = np.zeros(int(0.4 * native_sr), dtype=np.float32)
    else:
        audio = sanitize_audio(np.concatenate(chunks))
    out = resample(audio, native_sr, target_sr)
    peak_out = float(np.max(np.abs(out))) if out.size else 0.0
    if not np.isfinite(peak_out):
        peak_out = 0.0
    return out, target_sr, max(peak_all, peak_out)
