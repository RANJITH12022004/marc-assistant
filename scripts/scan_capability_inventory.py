#!/usr/bin/env python3
"""Scan this Windows PC for apps Marc can launch; merge into apps.json + inventory report."""
from __future__ import annotations

import json
import re
import winreg
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
APPS_JSON = ROOT / "config" / "apps.json"
HOTKEYS_JSON = ROOT / "config" / "hotkeys.json"
OUT_INVENTORY = ROOT / "data" / "capability_inventory.json"

# Display-name patterns → Marc app key + aliases
KNOWN_APPS: List[Tuple[str, str, List[str]]] = [
    ("chrome", r"google chrome", ["google chrome", "browser"]),
    ("brave", r"brave", ["brave browser"]),
    ("edge", r"microsoft edge", ["microsoft edge", "msedge"]),
    ("firefox", r"mozilla firefox|firefox", ["mozilla firefox"]),
    ("vscode", r"visual studio code|microsoft visual studio code", ["vs code", "code"]),
    ("cursor", r"^cursor$", ["cursor ide", "cursor editor"]),
    ("spotify", r"spotify", ["music", "spotify music"]),
    ("discord", r"discord", ["discord app"]),
    ("zoom", r"zoom", ["zoom meeting", "zoom app"]),
    ("teams", r"microsoft teams|teams", ["ms teams", "microsoft teams"]),
    ("slack", r"slack", ["slack app"]),
    ("whatsapp", r"whatsapp", ["whats app", "whatsapp desktop"]),
    ("telegram", r"telegram", ["telegram desktop"]),
    ("vlc", r"vlc", ["vlc media player", "media player"]),
    ("steam", r"steam", ["steam client"]),
    ("notion", r"notion", ["notion app"]),
    ("obsidian", r"obsidian", ["obsidian notes"]),
    ("word", r"microsoft word", ["ms word", "word"]),
    ("excel", r"microsoft excel", ["ms excel", "excel"]),
    ("powerpoint", r"microsoft powerpoint", ["ms powerpoint", "powerpoint", "ppt"]),
    ("onenote", r"onenote|one note", ["one note"]),
    ("outlook", r"microsoft outlook|outlook", ["outlook mail"]),
    ("photoshop", r"adobe photoshop", ["photoshop", "ps"]),
    ("premiere", r"adobe premiere", ["premiere pro"]),
    ("itunes", r"itunes", ["apple music itunes"]),
    ("onedrive", r"microsoft onedrive|onedrive", ["one drive"]),
    ("paint", r"^paint$|microsoft paint", ["mspaint"]),
    ("calculator", r"windows calculator|calculator", ["calc"]),
    ("notepad", r"^notepad$", ["text editor", "notes"]),
    ("terminal", r"windows terminal|powershell", ["powershell", "cmd", "wt"]),
    ("snipping", r"snipping tool", ["snip", "screen snip"]),
    ("photos", r"microsoft photos|^photos$", ["photos app", "pictures"]),
    ("store", r"microsoft store", ["ms store", "windows store"]),
    ("clock", r"windows clock|^clock$", ["alarms", "timer"]),
    ("maps", r"windows maps|^maps$", ["bing maps"]),
    ("weather", r"msn weather|windows weather|^weather$", ["weather app"]),
    ("calendar", r"windows calendar|^calendar$", ["calendar app"]),
    ("mail", r"mail and calendar|^mail$", ["windows mail"]),
    ("filezilla", r"filezilla", ["ftp"]),
    ("putty", r"putty", ["ssh putty"]),
    ("obs", r"obs studio|^obs$", ["obs streaming", "streamer"]),
    ("blender", r"blender", ["3d blender"]),
    ("gimp", r"gimp", ["gnu image"]),
    ("canva", r"canva", ["canva design"]),
    ("figma", r"figma", ["figma design"]),
    ("github", r"github desktop", ["github desktop"]),
    ("docker", r"docker desktop", ["docker"]),
    ("postman", r"postman", ["postman api"]),
    ("notepadpp", r"notepad\+\+", ["notepad plus plus", "npp"]),
    ("winrar", r"winrar|7-zip|7zip", ["archive", "zip app"]),
    ("acrobat", r"adobe acrobat|acrobat reader", ["pdf reader", "adobe reader"]),
]


def _reg_uninstall_entries() -> List[Dict[str, str]]:
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    found: List[Dict[str, str]] = []
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break
            try:
                sk = winreg.OpenKey(key, sub)
                name, _ = winreg.QueryValueEx(sk, "DisplayName")
                loc = ""
                try:
                    loc, _ = winreg.QueryValueEx(sk, "InstallLocation")
                except OSError:
                    pass
                icon = ""
                try:
                    icon, _ = winreg.QueryValueEx(sk, "DisplayIcon")
                except OSError:
                    pass
                found.append(
                    {
                        "name": str(name),
                        "install_location": str(loc or ""),
                        "display_icon": str(icon or "").split(",")[0].strip('"'),
                    }
                )
                winreg.CloseKey(sk)
            except OSError:
                continue
        winreg.CloseKey(key)
    return found


def _start_menu_exes() -> List[Path]:
    bases = [
        Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs",
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"),
    ]
    exes: List[Path] = []
    for base in bases:
        if not base.exists():
            continue
        for p in base.rglob("*.lnk"):
            # Resolve via COM is heavy; keep .lnk path as hint only
            exes.append(p)
    return exes


def _match_known(name: str) -> Optional[Tuple[str, List[str]]]:
    low = name.lower().strip()
    for key, pat, aliases in KNOWN_APPS:
        if re.search(pat, low, re.I):
            return key, aliases
    return None


def _exe_from_entry(entry: Dict[str, str]) -> Optional[str]:
    icon = entry.get("display_icon") or ""
    if icon.lower().endswith(".exe") and Path(icon).exists():
        return icon
    loc = entry.get("install_location") or ""
    if loc and Path(loc).is_dir():
        # common patterns
        for cand in Path(loc).glob("*.exe"):
            if cand.name.lower() not in ("uninstall.exe", "update.exe", "crashpad_handler.exe"):
                return str(cand)
        for cand in Path(loc).rglob("*.exe"):
            n = cand.name.lower()
            if n in ("uninstall.exe", "update.exe", "crashpad_handler.exe", "setup.exe"):
                continue
            if any(x in n for x in ("chrome", "brave", "code", "spotify", "discord", "zoom", "slack", "whatsapp", "vlc", "steam", "notion", "obsidian", "winword", "excel", "powerpnt", "teams", "outlook", "firefox", "msedge", "cursor", "telegram")):
                return str(cand)
    return None


def scan() -> Dict[str, Any]:
    existing = json.loads(APPS_JSON.read_text(encoding="utf-8"))
    entries = _reg_uninstall_entries()
    discovered: Dict[str, Dict[str, Any]] = {}
    raw_matches: List[Dict[str, str]] = []

    for e in entries:
        hit = _match_known(e["name"])
        if not hit:
            continue
        key, aliases = hit
        exe = _exe_from_entry(e)
        raw_matches.append({"name": e["name"], "key": key, "exe": exe or ""})
        if key in existing and existing[key].get("commands"):
            # keep existing if commands already resolve
            cmds = [c for c in existing[key]["commands"] if Path(c).exists() or not c.endswith(".exe")]
            if cmds:
                continue
        if key not in discovered:
            discovered[key] = {
                "aliases": aliases,
                "commands": [exe] if exe else [],
                "shell": key,
                "source": e["name"],
            }
        elif exe and exe not in discovered[key]["commands"]:
            discovered[key]["commands"].insert(0, exe)

    # Always-on URL / shell apps
    builtins = {
        "youtube": {
            "aliases": ["yt", "you tube"],
            "commands": [],
            "url": "https://www.youtube.com",
        },
        "gmail": {
            "aliases": ["mail", "email", "inbox", "google mail"],
            "commands": [],
            "url": "https://mail.google.com",
        },
        "camera": {
            "aliases": ["webcam", "windows camera"],
            "commands": [],
            "shell": "start microsoft.windows.camera:",
        },
        "settings": {
            "aliases": ["windows settings", "system settings"],
            "commands": ["ms-settings:"],
            "shell": "start ms-settings:",
        },
        "explorer": {
            "aliases": ["file explorer", "files", "folder"],
            "commands": ["explorer.exe"],
            "shell": "explorer",
        },
        "notepad": {
            "aliases": ["text editor", "notes", "note pad"],
            "commands": ["notepad.exe"],
            "shell": "notepad",
        },
        "calculator": {
            "aliases": ["calc"],
            "commands": ["calc.exe"],
            "shell": "calc",
        },
        "paint": {
            "aliases": ["mspaint"],
            "commands": ["mspaint.exe"],
            "shell": "mspaint",
        },
        "terminal": {
            "aliases": ["powershell", "cmd", "command prompt", "wt"],
            "commands": ["wt.exe", "powershell.exe"],
            "shell": "wt",
        },
    }

    merged = dict(existing)
    for k, v in builtins.items():
        if k not in merged:
            merged[k] = v
    for k, v in discovered.items():
        if k in merged:
            # merge commands / aliases
            aliases = list(dict.fromkeys((merged[k].get("aliases") or []) + (v.get("aliases") or [])))
            commands = list(dict.fromkeys([c for c in (v.get("commands") or []) + (merged[k].get("commands") or []) if c]))
            merged[k]["aliases"] = aliases
            if commands:
                merged[k]["commands"] = commands
        else:
            merged[k] = {kk: vv for kk, vv in v.items() if kk != "source"}

    hotkeys = json.loads(HOTKEYS_JSON.read_text(encoding="utf-8"))
    extra_hotkeys = {
        "fullscreen": ["f11"],
        "maximize": ["win", "up"],
        "minimize": ["win", "down"],
        "snap left": ["win", "left"],
        "snap right": ["win", "right"],
        "task view": ["win", "tab"],
        "new desktop": ["win", "ctrl", "d"],
        "close desktop": ["win", "ctrl", "f4"],
        "switch desktop left": ["win", "ctrl", "left"],
        "switch desktop right": ["win", "ctrl", "right"],
        "open explorer": ["win", "e"],
        "open settings": ["win", "i"],
        "run dialog": ["win", "r"],
        "show desktop": ["win", "d"],
        "lock": ["win", "l"],
        "emoji": ["win", "."],
        "mute": ["volumemute"],
        "volume up": ["volumeup"],
        "volume down": ["volumedown"],
        "play pause": ["playpause"],
        "next track": ["nexttrack"],
        "previous track": ["prevtrack"],
        "close window": ["alt", "f4"],
        "alt tab": ["alt", "tab"],
        "refresh": ["f5"],
        "find": ["ctrl", "f"],
        "new tab": ["ctrl", "t"],
        "new window": ["ctrl", "n"],
        "close tab": ["ctrl", "w"],
        "address bar": ["ctrl", "l"],
        "screenshot": ["win", "shift", "s"],
        "task manager": ["ctrl", "shift", "esc"],
        "select all": ["ctrl", "a"],
        "copy": ["ctrl", "c"],
        "paste": ["ctrl", "v"],
        "cut": ["ctrl", "x"],
        "undo": ["ctrl", "z"],
        "redo": ["ctrl", "y"],
        "save": ["ctrl", "s"],
        "desktop": ["win", "d"],
        "enter": ["enter"],
        "camera_photo": ["space"],
        "camera_video": ["space"],
        "camera_video_mode": ["tab"],
        "emoji": ["win", "."],
        "fullscreen": ["f11"],
        "maximize": ["win", "up"],
        "minimize": ["win", "down"],
        "snap left": ["win", "left"],
        "snap right": ["win", "right"],
        "task view": ["win", "tab"],
        "new desktop": ["win", "ctrl", "d"],
        "close desktop": ["win", "ctrl", "f4"],
        "switch desktop left": ["win", "ctrl", "left"],
        "switch desktop right": ["win", "ctrl", "right"],
        "open explorer": ["win", "e"],
        "open settings": ["win", "i"],
        "run dialog": ["win", "r"],
        "lock": ["win", "l"],
        "mute": ["volumemute"],
    }
    for k, v in extra_hotkeys.items():
        if k not in hotkeys:
            hotkeys[k] = v

    # Verify which apps have a resolvable launch
    openable = []
    missing_exe = []
    for key, cfg in sorted(merged.items()):
        ok = False
        if cfg.get("url") or (cfg.get("shell") and str(cfg.get("shell", "")).startswith("start ")):
            ok = True
        for c in cfg.get("commands") or []:
            if c.endswith(":") or c in ("notepad.exe", "calc.exe", "mspaint.exe", "explorer.exe", "wt.exe", "powershell.exe"):
                ok = True
                break
            if Path(c).exists():
                ok = True
                break
        if ok:
            openable.append(key)
        else:
            missing_exe.append(key)

    inventory = {
        "openable_apps": openable,
        "apps_missing_exe": missing_exe,
        "app_count": len(merged),
        "hotkey_count": len(hotkeys),
        "sites": ["youtube", "gmail", "google"],
        "site_actions": {
            "youtube": ["search", "home_scrape", "play_nth", "play_title", "pause"],
            "google": ["search", "open_nth_result"],
            "gmail": ["open", "search_ui"],
        },
        "camera_modes": ["photo", "video", "barcode", "record", "stop"],
        "raw_registry_matches": raw_matches[:80],
        "in_scope": [
            "Open/close/focus inventoried apps",
            "OS hotkeys (volume, snap, desktops, screenshot, emoji)",
            "YouTube home feed + search + play Nth/title via Playwright",
            "Google search + open first/Nth result via Playwright",
            "Windows Camera photo/video/barcode/record (best-effort hotkeys)",
        ],
        "out_of_scope": [
            "Arbitrary in-app UI clicks without vision",
            "Reading Gmail message bodies without API",
            "Installing/uninstalling software",
            "Admin-only system changes",
            "Brightness (hardware-dependent)",
        ],
        "notes": (
            "Laya System-1 classifies coarse intents; per-app opens use open_app + apps.json. "
            "Fine-tune expands utterance coverage; runtime still needs apps/hotkeys configs."
        ),
    }
    return {"apps": merged, "hotkeys": hotkeys, "inventory": inventory}


def main() -> int:
    result = scan()
    APPS_JSON.write_text(json.dumps(result["apps"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    HOTKEYS_JSON.write_text(json.dumps(result["hotkeys"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT_INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    OUT_INVENTORY.write_text(json.dumps(result["inventory"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    inv = result["inventory"]
    print(f"apps.json → {len(result['apps'])} apps ({len(inv['openable_apps'])} openable)")
    print(f"hotkeys.json → {len(result['hotkeys'])} actions")
    print(f"inventory → {OUT_INVENTORY}")
    print("openable:", ", ".join(inv["openable_apps"]))
    if inv["apps_missing_exe"]:
        print("missing exe:", ", ".join(inv["apps_missing_exe"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
