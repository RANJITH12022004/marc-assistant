#!/usr/bin/env python3
"""Pull jobs from the Vercel door and run them on local marc-api."""
import json
import os
import threading
import time
import urllib.error
import urllib.request

DOOR = os.environ.get("MARC_DOOR_URL", "https://marc-door.vercel.app").rstrip("/")
API = os.environ.get("MARC_API_URL", "http://127.0.0.1:8090").rstrip("/")
SECRET_PATH = os.environ.get("MARC_SECRET", "/home/rox/marc/secret")


def token() -> str:
    if os.environ.get("MARC_TOKEN"):
        return os.environ["MARC_TOKEN"].strip()
    with open(SECRET_PATH, encoding="utf-8") as handle:
        return handle.read().strip()


SECRET = token()


def call(method: str, url: str, body=None, timeout: int = 40):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", "Bearer " + SECRET)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if response.status == 204 or not raw:
                return None
            return json.loads(raw.decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return None
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {url} {exc.code} {detail[:180]}") from exc


def local(path: str, body: dict):
    return call("POST", API + path, body, timeout=110)


def publish_status() -> None:
    while True:
        started = time.time()
        try:
            snap = call("GET", API + "/status", timeout=8)
            if snap:
                call("POST", DOOR + "/v1/status", snap, timeout=15)
        except Exception as exc:
            print(f"[marc-bridge] status {exc}", flush=True)
        time.sleep(max(0.2, 3 - (time.time() - started)))


def main() -> None:
    print(f"[marc-bridge] door {DOOR}", flush=True)
    threading.Thread(target=publish_status, daemon=True).start()
    seen: set[str] = set()
    while True:
        try:
            job = call("GET", DOOR + "/v1/pull", timeout=40)
            if not job or not job.get("id"):
                continue
            job_id = str(job["id"])
            if job_id in seen:
                continue
            seen.add(job_id)
            if len(seen) > 40:
                seen.clear()
                seen.add(job_id)
            path = job.get("path") or "/utterance"
            if path not in {"/utterance", "/confirm"}:
                path = "/utterance"
            try:
                result = local(path, job.get("body") or {})
            except Exception as exc:
                print(f"[marc-bridge] local failed {exc}", flush=True)
                result = {"spoken": "Can't reach Marc", "confirm": None, "phone_steps": []}
            call("POST", DOOR + "/v1/result", {"id": job["id"], "body": result}, timeout=20)
            print(f"[marc-bridge] {path} {job['id']}", flush=True)
        except Exception as exc:
            print(f"[marc-bridge] {exc}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()
