#!/usr/bin/env python3
"""Watch TV Lock state and enable/disable YouTube on the TV over ADB."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

HOME = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
MARC = HOME / ".marc"


def _file(name: str, env: str, default: str = "") -> str:
    if os.environ.get(env):
        return os.environ[env].strip()
    path = MARC / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return default


def _data_dir() -> Path:
    if os.name != "nt" and Path("/home/rox/marc").is_dir():
        return Path("/home/rox/marc")
    return MARC


_DEFAULT_API = "http://127.0.0.1:8090" if os.name != "nt" else "http://127.0.0.1:8093"
API = _file("ytlock_url", "YTLOCK_URL", _DEFAULT_API).rstrip("/")
DEVICE = _file("ytlock_device", "YTLOCK_DEVICE")
PIN = _file("ytlock_pin", "YTLOCK_PIN")


def _secret() -> str:
    if os.environ.get("MARC_TOKEN"):
        return os.environ["MARC_TOKEN"].strip()
    for path in (Path("/home/rox/marc/secret"), MARC / "secret"):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text
    return ""


TOKEN = _secret()
ADB = os.environ.get("YTLOCK_ADB") or ("adb" if os.name != "nt" else r"C:\Users\ranjith\Downloads\platform-tools\adb.exe")
SERIAL_PATH = _data_dir() / "ytlock_tv_serial"
SERIAL = (
    os.environ.get("YTLOCK_TV")
    or _file("ytlock_tv_serial", "", "")
    or (SERIAL_PATH.read_text(encoding="utf-8").strip() if SERIAL_PATH.is_file() else "")
    or "192.168.68.100:5555"
)
DIRECT = os.environ.get("YTLOCK_DIRECT", "1" if os.name != "nt" else "").strip() in {"1", "true", "yes"}
PACKAGES = [
    "com.google.android.youtube.tv",
    "com.google.android.youtube.tvmusic",
]
_SCAN_PORTS = [5555, *range(37000, 44000)]


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if DEVICE:
        headers["X-Ytlock-Device"] = DEVICE
    elif PIN:
        headers["X-Ytlock-Pin"] = PIN
    elif TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    return headers


def _endpoint() -> str:
    if API.rstrip("/").endswith("/api/lock") or API.rstrip("/").endswith("/ytlock"):
        return API
    if "vercel.app" in API:
        return API.rstrip("/") + "/api/lock"
    return API.rstrip("/") + "/ytlock"


def _host() -> str:
    return SERIAL.split(":", 1)[0]


def _adb(*args: str, timeout: int = 12) -> subprocess.CompletedProcess:
    cmd = [ADB, "-s", SERIAL, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _save_serial(serial: str) -> None:
    global SERIAL
    SERIAL = serial
    try:
        SERIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        SERIAL_PATH.write_text(serial, encoding="utf-8")
    except OSError:
        pass


def _probe_tcp(host: str, port: int) -> int | None:
    sock = socket.socket()
    sock.settimeout(0.2)
    try:
        if sock.connect_ex((host, port)) == 0:
            return port
    finally:
        sock.close()
    return None


def _open_ports(host: str) -> list[int]:
    found: list[int] = []
    with ThreadPoolExecutor(max_workers=200) as pool:
        futs = [pool.submit(_probe_tcp, host, port) for port in _SCAN_PORTS]
        for fut in as_completed(futs):
            hit = fut.result()
            if hit:
                found.append(hit)
    found.sort()
    return found


def _try_connect(serial: str) -> bool:
    subprocess.run([ADB, "connect", serial], capture_output=True, text=True, timeout=8, check=False)
    done = subprocess.run(
        [ADB, "-s", serial, "get-state"],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    return (done.stdout or "").strip() == "device"


def _pin_tcp(host: str) -> str | None:
    """Ask adbd to stay on 5555 until the next reboot. Needs an already-open session."""
    subprocess.run([ADB, "-s", SERIAL, "tcpip", "5555"], capture_output=True, text=True, timeout=8, check=False)
    time.sleep(1)
    pinned = f"{host}:5555"
    if _try_connect(pinned):
        _save_serial(pinned)
        return pinned
    return None


def _connect() -> bool:
    global SERIAL
    if _try_connect(SERIAL):
        return True
    host = _host()
    candidates = [SERIAL]
    for port in _open_ports(host):
        serial = f"{host}:{port}"
        if serial not in candidates:
            candidates.append(serial)
    for serial in candidates:
        if _try_connect(serial):
            _save_serial(serial)
            _pin_tcp(host)
            return True
    return False


def _tv_name() -> str:
    try:
        model = _adb("shell", "getprop", "ro.product.model").stdout.strip() or "TV"
        return model[:40]
    except (OSError, subprocess.SubprocessError):
        return "TV"


def _set_youtube(locked: bool) -> tuple[bool, str]:
    if not _connect():
        return False, "tv is up, but ADB is not listening"
    verb = "disable-user" if locked else "enable"
    extra = ["--user", "0"] if locked else []
    last = "unknown"
    ok = True
    for package in PACKAGES:
        try:
            done = _adb("shell", "pm", verb, *extra, package)
            last = (done.stdout or done.stderr or "").strip()[:80] or verb
            if done.returncode != 0:
                ok = False
        except (OSError, subprocess.SubprocessError) as exc:
            last = str(exc)[:80]
            ok = False
    if locked and ok:
        try:
            _adb("shell", "am", "force-stop", PACKAGES[0])
        except (OSError, subprocess.SubprocessError):
            pass
    return ok, last


def _status() -> dict:
    if DIRECT:
        from ytlock_store import get

        return get("", public=False)
    req = urllib.request.Request(_endpoint(), headers=_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def _report(name: str) -> None:
    if DIRECT:
        from ytlock_store import handle

        try:
            handle({"action": "tv", "tv": name}, public=False)
        except OSError:
            return
        return
    body = json.dumps({"action": "tv", "tv": name}).encode()
    req = urllib.request.Request(_endpoint(), data=body, headers=_headers(), method="POST")
    try:
        urllib.request.urlopen(req, timeout=8).read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return


def main() -> None:
    print("[ytlock-tv] watching", SERIAL, "store" if DIRECT else _endpoint(), flush=True)
    last = None
    while True:
        try:
            data = _status()
            want = bool(data.get("locked"))
            if last is None or want != last:
                ok, msg = _set_youtube(want)
                if not ok:
                    _report("unknown")
                    print("[ytlock-tv]", "retry", "lock" if want else "unlock", msg, flush=True)
                    last = None
                else:
                    name = _tv_name()
                    _report(name)
                    print("[ytlock-tv]", "lock" if want else "unlock", name, msg, flush=True)
                    last = want
        except Exception as exc:  # noqa: BLE001
            print("[ytlock-tv]", type(exc).__name__, str(exc)[:120], flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
