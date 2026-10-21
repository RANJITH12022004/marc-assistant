"""Jarvis/Edith voice loop: IdleWake → command listen → follow-up only when needed."""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

# Quieter Qt DPI logs on Windows
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")


def run_voice(
    seconds: float = 6.0,
    no_laya: bool = True,
    use_hotkey: bool = False,
    tray: bool = False,
    stt_prefer: str = "google",
    island: bool = True,
    listen_gap: float = 0.15,
    empty_sleep_after: int = 3,
    followup_seconds: float = 12.0,
    wake_threshold: float = 0.25,
    wake_word: str = "jarvis",
    debug_turns: bool = False,
) -> int:
    from orchestrator import MarcOrchestrator
    from orchestrator.persona import ready_line, wake_greeting
    from orchestrator.session import SessionState
    from voice import SpeechToText, TextToSpeech
    from voice.junk import is_junk_transcript

    session = SessionState()
    tts = TextToSpeech()
    stt = SpeechToText(prefer=stt_prefer)

    ctrl = {
        "abort": False,
        "quit": False,
        "wake": False,
        "force_idle": False,
        "speaking": False,
        "barge": False,
    }
    ctrl_lock = threading.Lock()
    listen_cancel = threading.Event()
    phase = {"mode": "idle"}

    island_ui = None
    if island:
        try:
            from ui.island import DynamicIsland

            island_ui = DynamicIsland()
            island_ui.start()
        except Exception as exc:  # noqa: BLE001
            print(f"[marc] island failed: {exc}")
            island_ui = None

    wake_listener = None

    def pause_wake() -> None:
        if wake_listener:
            try:
                wake_listener.pause()
            except Exception:  # noqa: BLE001
                pass

    def resume_wake() -> None:
        if wake_listener:
            try:
                wake_listener.resume()
            except Exception:  # noqa: BLE001
                pass

    def set_state(state: str, subtitle: str = "") -> None:
        if island_ui:
            island_ui.set(state, subtitle)
        else:
            print(f"[marc] status → {state}" + (f" | {subtitle}" if subtitle else ""))

    def speak(msg: str, *, allow_barge: bool = True) -> None:
        pause_wake()
        with ctrl_lock:
            ctrl["speaking"] = True
            ctrl["abort"] = False
            ctrl["barge"] = False
        set_state("speaking")
        barge_stop = threading.Event()

        def _barge_watch() -> None:
            """Stop TTS if user talks over Marc (energy barge-in)."""
            if not allow_barge:
                return
            try:
                import sounddevice as sd
                import numpy as np

                sr = 16000
                # Skip TTS onset + room reverb so laptop speakers don't false-trigger
                time.sleep(1.2)
                hits = 0
                while not barge_stop.is_set():
                    with ctrl_lock:
                        if not ctrl.get("speaking") or ctrl.get("abort"):
                            return
                    probe = sd.rec(int(0.12 * sr), samplerate=sr, channels=1, dtype="float32")
                    sd.wait()
                    flat = np.asarray(probe, dtype=np.float32).reshape(-1)
                    flat = np.nan_to_num(flat, nan=0.0, posinf=0.0, neginf=0.0)
                    flat = np.clip(flat, -1.0, 1.0)
                    rms = float(np.sqrt(np.mean(np.square(flat)))) if flat.size else 0.0
                    # High bar: speaker bleed is ~0.05–0.10; user close-talk is louder
                    if rms >= 0.16:
                        hits += 1
                    else:
                        hits = 0
                    if hits >= 3:
                        print(f"[marc] barge-in (rms={rms:.3f})", flush=True)
                        with ctrl_lock:
                            ctrl["barge"] = True
                            ctrl["abort"] = True
                        try:
                            tts.stop()
                        except Exception:  # noqa: BLE001
                            pass
                        return
                    time.sleep(0.05)
            except Exception:  # noqa: BLE001
                return

        watcher = threading.Thread(target=_barge_watch, daemon=True, name="marc-barge")
        watcher.start()
        try:
            tts.speak(msg)
        except Exception as exc:  # noqa: BLE001
            print(f"[marc] speak error: {exc}")
        finally:
            barge_stop.set()
            with ctrl_lock:
                ctrl["speaking"] = False
                barged = bool(ctrl.get("barge"))
                ctrl["barge"] = False
            if barged:
                # Stay in command mode — next loop iteration listens
                with ctrl_lock:
                    ctrl["abort"] = False
                    ctrl["force_idle"] = False
                print("[marc] barge-in → listen", flush=True)

    def abort_to_idle() -> None:
        with ctrl_lock:
            ctrl["abort"] = True
            ctrl["force_idle"] = True
        # Preserve pick/slot memory (same as follow-up silence) — only stop TTS
        try:
            tts.stop()
        except Exception:  # noqa: BLE001
            pass
        print("[marc] Esc/abort → IdleWake (keeping results/slots)")

    def request_quit() -> None:
        with ctrl_lock:
            ctrl["quit"] = True
        try:
            tts.stop()
        except Exception:  # noqa: BLE001
            pass
        print("[marc] Quit requested")

    def request_wake() -> None:
        with ctrl_lock:
            ctrl["wake"] = True
            ctrl["force_idle"] = False
            ctrl["abort"] = False
        listen_cancel.clear()
        session.sleeping = False
        print("[marc] Wake signal")

    def request_sleep() -> None:
        """Stop continuous listen and return to IdleWake. Tap again to wake."""
        listen_cancel.set()
        with ctrl_lock:
            ctrl["wake"] = False
            ctrl["abort"] = True
            ctrl["force_idle"] = True
            ctrl["barge"] = False
        session.sleeping = True
        try:
            tts.stop()
        except Exception:  # noqa: BLE001
            pass
        set_state("wake", "tap to wake")
        print("[marc] island tap → sleep (tap again to wake)", flush=True)

    def on_island_click() -> None:
        with ctrl_lock:
            idle = phase["mode"] == "idle" or bool(session.sleeping)
        if idle:
            request_wake()
        else:
            request_sleep()

    orch = MarcOrchestrator(
        preload_laya=False,
        lazy_laya=not no_laya,
        speak_fn=speak,
        session=session,
    )

    if island_ui:
        island_ui.set_click_handler(on_island_click)
        island_ui.set_quit_handler(request_quit)

    # Esc global hook
    try:
        import keyboard

        keyboard.on_press_key("esc", lambda _: abort_to_idle(), suppress=False)
        print("[marc] Esc = abort speak + IdleWake")
    except Exception as exc:  # noqa: BLE001
        try:
            from pynput import keyboard as pk

            def _on_press(key):
                try:
                    if key == pk.Key.esc:
                        abort_to_idle()
                except Exception:  # noqa: BLE001
                    pass

            listener = pk.Listener(on_press=_on_press)
            listener.daemon = True
            listener.start()
            print("[marc] Esc = abort (pynput)")
        except Exception as exc2:  # noqa: BLE001
            print(f"[marc] Esc hook unavailable ({exc} / {exc2})")

    if use_hotkey:
        try:
            from voice import PushToTalk

            PushToTalk(on_trigger=request_wake).start()
            print("[marc] Hotkey Ctrl+Shift+M also wakes.")
        except Exception as exc:  # noqa: BLE001
            print(f"[marc] hotkey failed: {exc}")

    print("[marc] Jarvis mode: wake once → auto-listen after each reply (silence → IdleWake)")
    print("[marc] Wake: 'hey marc' / 'hey jarvis' / tap island to sleep or wake | X=quit | Esc=abort | say sleep to pause")

    # Mic self-check (catch dead/garbled capture early)
    try:
        from voice.audio_io import list_input_devices, pick_live_input, record_mono

        from settings import settings as _settings

        # Prefer settings / env threshold
        try:
            wake_threshold = float(
                wake_threshold
                if wake_threshold is not None
                else getattr(_settings, "wake_threshold", 0.25)
            )
        except Exception:  # noqa: BLE001
            wake_threshold = 0.25

        _probe, _sr, _peak = record_mono(seconds=0.35, target_sr=16000)
        print(f"[marc] mic check peak={_peak:.4f}", flush=True)
        if _peak < 0.0001:
            print(
                "[marc] WARNING: mic looks dead — probing other input devices…",
                flush=True,
            )
            for i, name, ch in list_input_devices():
                print(f"[marc]   input[{i}] {name!r} ch={ch}", flush=True)
            picked = pick_live_input(min_peak=0.0001)
            if picked is not None:
                print(f"[marc] using audio device index {picked}", flush=True)
                _probe, _sr, _peak = record_mono(seconds=0.25, target_sr=16000)
                print(f"[marc] mic check peak={_peak:.4f}", flush=True)
            if _peak < 0.0001:
                print(
                    "[marc] WARNING: mic still dead — set MARC_AUDIO_DEVICE to a listed index, "
                    "or enable Microphone access for desktop apps.",
                    flush=True,
                )
    except Exception as exc:  # noqa: BLE001
        print(f"[marc] mic check failed: {exc}", flush=True)

    # Speak FIRST with mic free — then start wake spotting; load Laya after ready
    set_state("speaking", "starting")
    speak(ready_line(), allow_barge=False)
    time.sleep(0.3)
    if not no_laya:
        try:
            orch.start_laya_background()
        except Exception as exc:  # noqa: BLE001
            print(f"[marc] Laya background start failed: {exc}", flush=True)

    try:
        from voice.wake_listen import WakeListener

        wake_listener = WakeListener(
            on_wake=request_wake,
            threshold=wake_threshold,
            wake_word=wake_word,
        )
        wake_listener.start()  # starts paused
    except Exception as exc:  # noqa: BLE001
        print(f"[marc] wake listener failed: {exc}")
        wake_listener = None

    # Reminder due-checker (toast + TTS)
    def _reminder_loop() -> None:
        while True:
            with ctrl_lock:
                if ctrl["quit"]:
                    return
            try:
                from tools.calendar_tools import due_reminders, windows_toast

                for item in due_reminders():
                    msg = item.get("message") or "Reminder"
                    print(f"[marc] reminder due: {msg}", flush=True)
                    try:
                        windows_toast("Marc", msg)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        speak(f"Reminder: {msg}")
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                print(f"[marc] reminder loop: {exc}", flush=True)
            time.sleep(15)

    threading.Thread(target=_reminder_loop, daemon=True, name="marc-reminders").start()

    # Island heartbeat — log if UI thread died
    def _island_watch() -> None:
        while True:
            with ctrl_lock:
                if ctrl["quit"]:
                    return
            if island_ui is not None:
                alive = getattr(island_ui, "_impl", None) is not None or getattr(
                    island_ui, "_bridge", None
                ) is not None
                if not alive and not getattr(island_ui, "_shutdown", threading.Event()).is_set():
                    # _shutdown is Event — check properly
                    try:
                        if not island_ui._shutdown.is_set():
                            print("[marc] island heartbeat: UI impl missing", flush=True)
                    except Exception:  # noqa: BLE001
                        pass
            time.sleep(30)

    if island_ui is not None:
        threading.Thread(target=_island_watch, daemon=True, name="marc-island-watch").start()

    def one_listen(secs: float, label: str = "listening", silence_ms: Optional[float] = None) -> Optional[str]:
        if listen_cancel.is_set():
            return None
        pause_wake()
        # Brief PortAudio handoff (was 0.35s)
        time.sleep(0.12)
        if listen_cancel.is_set():
            return None
        set_state(label)
        def _record(sec: float, sil: Optional[float] = None):
            return stt.record_and_transcribe_ex(
                seconds=sec, silence_ms=sil, cancel=listen_cancel.is_set
            )
        try:
            text, rms = _record(secs, silence_ms)
        except TypeError:
            # Older STT without silence_ms / cancel
            try:
                text, rms = stt.record_and_transcribe_ex(seconds=secs, silence_ms=silence_ms)
            except TypeError:
                try:
                    text, rms = stt.record_and_transcribe_ex(seconds=secs)
                except AttributeError:
                    try:
                        text = stt.record_and_transcribe(seconds=secs)
                        rms = 999.0
                    except Exception as exc:  # noqa: BLE001
                        print(f"[marc] STT error: {exc}")
                        return None
            except AttributeError:
                try:
                    text = stt.record_and_transcribe(seconds=secs)
                    rms = 999.0
                except Exception as exc:  # noqa: BLE001
                    print(f"[marc] STT error: {exc}")
                    return None
        except AttributeError:
            try:
                text = stt.record_and_transcribe(seconds=secs)
                rms = 999.0
            except Exception as exc:  # noqa: BLE001
                print(f"[marc] STT error: {exc}")
                return None
        except Exception as exc:  # noqa: BLE001
            print(f"[marc] STT error: {exc}")
            return None
        if listen_cancel.is_set():
            return None
        text = (text or "").strip()
        peak = float(getattr(stt, "_last_peak", 0.0) or 0.0)
        # One automatic re-listen when real speech energy but empty transcript
        if not text and peak >= 0.012 and not listen_cancel.is_set():
            print(f"[marc] empty+speech (peak={peak:.3f}) — retry listen", flush=True)
            try:
                text2, rms2 = stt.record_and_transcribe_ex(
                    seconds=min(secs, 6.0),
                    silence_ms=silence_ms,
                    cancel=listen_cancel.is_set,
                )
                text = (text2 or "").strip()
                rms = rms2
                peak = float(getattr(stt, "_last_peak", 0.0) or 0.0)
            except TypeError:
                try:
                    text2, rms2 = stt.record_and_transcribe_ex(seconds=min(secs, 6.0))
                    text = (text2 or "").strip()
                    rms = rms2
                except Exception as exc:  # noqa: BLE001
                    print(f"[marc] STT retry error: {exc}")
            except Exception as exc:  # noqa: BLE001
                print(f"[marc] STT retry error: {exc}")
        print(f"[marc] heard: {text!r} (rms={rms:.0f} peak={peak:.3f})")
        if listen_cancel.is_set():
            return None
        pending = getattr(orch, "_pending", None)
        junk, reason = is_junk_transcript(
            text, rms=rms, allow_confirm=bool(pending), peak=peak
        )
        if junk:
            print(f"[marc] ignore junk ({reason})")
            return None
        return text

    def handle_utterance(text: str) -> bool:
        with ctrl_lock:
            if ctrl["quit"] or ctrl["force_idle"]:
                return False
        set_state("thinking", text[:40])
        set_state("acting", text[:40])
        result = orch.handle(text)
        print(
            f"[{result.source}] intent={result.intent} "
            f"conf={result.confidence:.2f} continue={result.should_continue} "
            f"awaiting={session.awaiting}"
        )
        if debug_turns:
            steps = result.steps_run or []
            tools = ",".join((s.get("tool") or "?") for s in steps[:6])
            print(
                f"[turn] intent={result.intent} conf={result.confidence:.2f} "
                f"src={result.source} await={session.awaiting} "
                f"pending={bool(getattr(orch, '_pending', None))} steps=[{tools}]",
                flush=True,
            )
        time.sleep(min(0.15, listen_gap))
        return result.should_continue

    def wait_for_wake() -> bool:
        """Block in IdleWake until wake/click/Enter. Return False to quit."""
        phase["mode"] = "idle"
        listen_cancel.clear()
        set_state("wake", "tap island or say hey marc")
        session.sleeping = True
        resume_wake()
        print("[marc] IdleWake — tap the island, say 'hey marc', or press Enter")
        with ctrl_lock:
            ctrl["wake"] = False
            ctrl["force_idle"] = False
            ctrl["abort"] = False

        while True:
            with ctrl_lock:
                if ctrl["quit"]:
                    return False
                if ctrl["wake"]:
                    ctrl["wake"] = False
                    break
            try:
                import msvcrt

                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\r", "\n"):
                        break
                    if ch in ("q", "Q"):
                        return False
                    if ch == "\x1b":
                        continue
                time.sleep(0.1)
            except ImportError:
                line = input("[Enter=wake / quit=exit] ").strip().lower()
                if line in ("quit", "exit", "q"):
                    return False
                break

        phase["mode"] = "live"
        session.sleeping = False
        session.empty_listens = 0
        pause_wake()
        speak(wake_greeting(), allow_barge=False)
        time.sleep(listen_gap)
        return True

    try:
        mode = "idle"; phase["mode"] = "idle"

        while True:
            try:
                with ctrl_lock:
                    if ctrl["quit"]:
                        break
                    if ctrl["force_idle"]:
                        ctrl["force_idle"] = False
                        mode = "idle"; phase["mode"] = "idle"

                if mode == "idle":
                    if not wait_for_wake():
                        break
                    mode = "command"
                    continue

                awaiting = str(session.awaiting or "none")
                dictating = awaiting in ("slot:type_text",) or awaiting.startswith("slot:type")
                if dictating:
                    secs = max(followup_seconds, float(os.getenv("MARC_DICTATE_MAX_S", "25")))
                    silence_ms = float(os.getenv("MARC_VAD_DICTATE_SILENCE_MS", "1800"))
                    label = "followup"
                    print(f"[marc] dictate listen max={secs:.0f}s silence={silence_ms:.0f}ms", flush=True)
                elif mode == "followup":
                    secs = followup_seconds
                    silence_ms = None
                    label = "followup"
                else:
                    secs = seconds
                    silence_ms = None
                    label = "listening"
                text = one_listen(secs, label=label, silence_ms=silence_ms)

                with ctrl_lock:
                    if ctrl["quit"]:
                        break
                    if ctrl["force_idle"] or ctrl["abort"]:
                        ctrl["force_idle"] = False
                        ctrl["abort"] = False
                        mode = "idle"; phase["mode"] = "idle"
                        continue

                if not text:
                    if mode == "followup":
                        # Dictate / type slot: need several empties before IdleWake
                        if str(session.awaiting).startswith("slot:type_text"):
                            session.empty_listens += 1
                            if session.empty_listens < empty_sleep_after:
                                continue
                            print("[marc] type-slot silence → IdleWake (keeping slot)")
                            session.empty_listens = 0
                            mode = "idle"; phase["mode"] = "idle"
                            continue
                        # Keep pick/slot memory — user can wake and finish ("open the first")
                        print("[marc] follow-up silence → IdleWake (keeping results)")
                        mode = "idle"; phase["mode"] = "idle"
                        continue
                    session.empty_listens += 1
                    if session.empty_listens >= empty_sleep_after:
                        print("[marc] silence → IdleWake (say hey marc)", flush=True)
                        mode = "idle"; phase["mode"] = "idle"
                        session.empty_listens = 0
                    continue

                session.empty_listens = 0
                cont = handle_utterance(text)

                with ctrl_lock:
                    if ctrl["quit"] or ctrl["force_idle"] or ctrl["abort"]:
                        ctrl["force_idle"] = False
                        ctrl["abort"] = False
                        mode = "idle"; phase["mode"] = "idle"
                        continue

                if not cont:
                    # sleep / stand down → IdleWake only (never quit the process)
                    print("[marc] sleeping → IdleWake (say hey marc)", flush=True)
                    mode = "idle"; phase["mode"] = "idle"
                    continue

                # Auto re-listen after every reply — only IdleWake on sleep / silence / Esc
                if session.awaiting in ("pick_video", "pick_mail", "pick_result", "confirm") or str(
                    session.awaiting
                ).startswith("slot:"):
                    mode = "followup"
                    hint = {
                        "pick_video": "say play the first…",
                        "pick_mail": "say open the first…",
                        "pick_result": "say open the first…",
                        "confirm": "say yes or cancel…",
                        "slot:open_app": "say the app name…",
                        "slot:web_search": "say what to search…",
                        "slot:continue": "finish the command…",
                        "slot:type_text": "say what to type…",
                    }.get(session.awaiting, "listening…")
                    set_state("followup", hint)
                else:
                    mode = "command"
                    set_state("listening", "listening…")
            except Exception as exc:  # noqa: BLE001
                # Never let one bad turn kill the whole voice session
                print(f"[marc] turn error (continuing): {type(exc).__name__}: {exc}", flush=True)
                mode = "command"
                session.empty_listens = 0
                time.sleep(0.3)
                continue

    except KeyboardInterrupt:
        print()
    finally:
        with ctrl_lock:
            do_quit = bool(ctrl.get("quit"))
            ctrl["quit"] = True
        pause_wake()
        set_state("sleeping")
        if wake_listener:
            try:
                wake_listener.stop()
            except Exception:  # noqa: BLE001
                pass
        # Only say Goodbye on real quit (island X) — not on crash/idle
        if do_quit:
            try:
                speak("Goodbye.", allow_barge=False)
            except Exception:  # noqa: BLE001
                pass
        try:
            from tools.browser import get_browser

            get_browser().close()
        except Exception:  # noqa: BLE001
            pass
        if island_ui:
            try:
                island_ui.shutdown()
            except Exception:  # noqa: BLE001
                pass
    return 0
