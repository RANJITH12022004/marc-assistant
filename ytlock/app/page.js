"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_LOCK_API || "https://rox.tail9a2eac.ts.net/api/ytlock";
const PRESETS = [
  { label: "15 min", sub: "Lock after a short break", minutes: 15 },
  { label: "30 min", sub: "Half-hour watch window", minutes: 30 },
  { label: "45 min", sub: "Longer session", minutes: 45 },
  { label: "1 hour", sub: "Lock at the hour", minutes: 60 },
];

const css = `
:root {
  color-scheme: light;
  --bg: #f2f2f7;
  --card: #fff;
  --text: #1a1b1f;
  --muted: #8e8e93;
  --label: #464554;
  --line: rgba(0,0,0,.08);
  --violet: #5856d6;
  --violet-deep: #3f3bbd;
  --green: #34c759;
  --red: #ff3b30;
  --fill: rgba(118,118,128,.12);
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); }
.app { min-height: 100dvh; max-width: 430px; margin: 0 auto; padding: 12px 16px calc(96px + env(safe-area-inset-bottom)); }
.pin-wrap { min-height: 100dvh; display: grid; place-items: center; padding: 24px 16px; }
.top { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 6px 2px 14px; }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 22px; letter-spacing: -.02em; }
.brand svg { color: var(--violet); }
.chip { display: inline-flex; align-items: center; gap: 6px; min-height: 28px; padding: 0 10px; border-radius: 999px; background: rgba(52,199,89,.12); color: #248a3d; font-size: 12px; font-weight: 600; }
.chip.off { background: rgba(255,59,48,.12); color: var(--red); }
.card { background: var(--card); border: 0.5px solid var(--line); border-radius: 22px; padding: 18px; box-shadow: 0 10px 30px rgba(0,0,0,.04); }
.device { margin: 0 0 14px; }
.device h1 { margin: 0; font-size: 28px; line-height: 34px; letter-spacing: -.015em; }
.device p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
.status { text-align: center; padding: 8px 8px 4px; }
.ring { width: 118px; height: 118px; margin: 0 auto 10px; border-radius: 50%; border: 0; display: grid; place-items: center; background: rgba(52,199,89,.12); color: var(--green); box-shadow: 0 0 0 8px rgba(52,199,89,.08); cursor: pointer; }
.ring.lock { background: rgba(255,59,48,.12); color: var(--red); box-shadow: 0 0 0 8px rgba(255,59,48,.08); }
.tap { margin: 0; color: var(--muted); font-size: 12px; font-weight: 600; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 16px 0 0; }
.stat { background: rgba(118,118,128,.08); border-radius: 16px; padding: 12px; text-align: left; }
.stat b { display: block; font-size: 22px; letter-spacing: -.02em; }
.stat span { color: var(--muted); font-size: 12px; font-weight: 600; }
button, input, select { font: inherit; }
button { min-height: 50px; border: 0; border-radius: 16px; padding: 12px 14px; font-size: 17px; font-weight: 600; cursor: pointer; }
button:disabled { opacity: .45; cursor: default; }
.btn-lock { width: 100%; background: var(--red); color: #fff; margin-top: 14px; }
.btn-unlock { width: 100%; background: var(--green); color: #fff; margin-top: 14px; }
.btn-primary { background: var(--violet); color: #fff; width: 100%; }
.btn-quiet { background: var(--fill); color: var(--violet-deep); min-height: 44px; font-size: 15px; }
.kicker { color: var(--muted); font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; margin: 22px 4px 10px; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tile { min-height: 88px; text-align: left; background: var(--card); border: 0.5px solid var(--line); border-radius: 18px; padding: 14px; display: grid; align-content: center; gap: 4px; }
.tile b { font-size: 15px; }
.tile span { color: var(--muted); font-size: 12px; font-weight: 500; }
.hero { padding: 4px 2px 12px; }
.hero h1 { margin: 4px 0 6px; font-size: 28px; line-height: 34px; letter-spacing: -.015em; }
.hero p, .sub { margin: 0; color: var(--label); font-size: 15px; line-height: 20px; }
.field { margin: 0 0 14px; }
.field label { display: block; font-size: 13px; font-weight: 600; margin: 0 0 8px; }
.row { display: grid; grid-template-columns: minmax(0,1fr) 96px 88px; gap: 8px; }
input, select { width: 100%; min-height: 44px; border: 0; border-radius: 12px; background: var(--fill); color: var(--text); padding: 10px 12px; }
input:focus, select:focus { outline: 2px solid rgba(88,86,214,.28); }
.hint { margin: 8px 0 0; color: var(--muted); font-size: 13px; line-height: 18px; }
.err { min-height: 1.2em; margin: 12px 4px 0; color: var(--red); font-size: 13px; }
.switch-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 2px 0 12px; }
.switch { width: 51px; height: 31px; border-radius: 999px; border: 0; background: #e9e9eb; position: relative; min-height: 31px; padding: 0; flex: 0 0 auto; }
.switch.on { background: var(--violet); }
.switch i { position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 50%; background: #fff; box-shadow: 0 2px 6px rgba(0,0,0,.18); transition: left .16s ease; }
.switch.on i { left: 22px; }
.list { overflow: hidden; padding: 6px 16px; }
.item { display: flex; justify-content: space-between; gap: 12px; padding: 16px 2px; border-top: 0.5px solid var(--line); }
.item:first-child { border-top: 0; }
.item span:last-child { color: var(--muted); font-weight: 500; text-align: right; }
.live { margin: 0 0 8px; color: var(--green); font-size: 12px; font-weight: 700; }
.clock { width: 160px; height: 160px; margin: 8px auto 12px; border-radius: 50%; display: grid; place-items: center; background: conic-gradient(var(--violet) var(--pct, 0%), rgba(88,86,214,.12) 0); }
.clock span { width: 128px; height: 128px; border-radius: 50%; background: #fff; display: grid; place-items: center; font-size: 28px; font-weight: 700; letter-spacing: -.03em; }
.nav { position: fixed; left: 50%; bottom: 0; transform: translateX(-50%); width: min(430px, 100%); display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 0; padding: 6px 8px calc(8px + env(safe-area-inset-bottom)); background: rgba(255,255,255,.82); backdrop-filter: blur(20px) saturate(180%); border-top: 0.5px solid var(--line); }
.nav button { min-height: 52px; background: transparent; color: var(--muted); font-size: 10px; font-weight: 600; letter-spacing: .02em; display: grid; place-items: center; gap: 2px; padding: 4px; }
.nav button.on { color: var(--violet); }
.install { display: none; margin-top: 12px; }
.install.show { display: block; }
`;

function toMinutes(raw, unit) {
  const n = Number.parseInt(String(raw || "").trim(), 10);
  if (!Number.isFinite(n) || n < 1) return 0;
  return Math.min(unit === "hr" ? n * 60 : n, 24 * 60);
}

function remainText(until) {
  const left = Math.max(0, Number(until || 0) - Math.floor(Date.now() / 1000));
  if (!left) return "Off";
  const m = Math.ceil(left / 60);
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${m} min`;
}

function remainPct(until) {
  const left = Math.max(0, Number(until || 0) - Math.floor(Date.now() / 1000));
  if (!left) return 0;
  return Math.min(100, Math.round((left / (4 * 3600)) * 100));
}

function LockMark() {
  return (
    <svg width="42" height="42" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M8 11V8a4 4 0 1 1 8 0v3" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <rect x="6" y="11" width="12" height="9" rx="2.2" fill="currentColor" />
    </svg>
  );
}

function Icon({ d }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d={d} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Page() {
  const [tab, setTab] = useState("control");
  const [appErr, setAppErr] = useState("");
  const [view, setView] = useState(null);
  const [install, setInstall] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lockAmt, setLockAmt] = useState("");
  const [lockUnit, setLockUnit] = useState("min");
  const [unlockAmt, setUnlockAmt] = useState("");
  const [unlockUnit, setUnlockUnit] = useState("min");
  const [lockAt, setLockAt] = useState("21:00");
  const [unlockAt, setUnlockAt] = useState("07:00");
  const [schedOn, setSchedOn] = useState(false);
  const [, setTick] = useState(0);

  useEffect(() => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
    const onPrompt = (event) => {
      event.preventDefault();
      window.__ytlockInstall = event;
      setInstall(true);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  async function call(body, method) {
    const headers = { "Content-Type": "application/json" };
    const opts = { method: method || (body ? "POST" : "GET"), headers, cache: "no-store" };
    if (body) opts.body = JSON.stringify(body);
    const response = await fetch(API, opts);
    return response.json();
  }

  function paint(data) {
    setView(data);
    setAppErr("");
    const sched = data?.schedule || {};
    setSchedOn(Boolean(sched.enabled));
    if (sched.lock_at) setLockAt(sched.lock_at);
    if (sched.unlock_at) setUnlockAt(sched.unlock_at);
  }

  async function refresh() {
    try {
      const data = await call(null, "GET");
      if (data && data.ok) paint(data);
      else setAppErr("Can't reach the home server.");
    } catch {
      setAppErr("Can't reach the home server.");
    }
  }

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, 5000);
    const clock = setInterval(() => setTick((n) => n + 1), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(clock);
    };
  }, []);

  async function act(body) {
    setAppErr("");
    setBusy(true);
    try {
      const data = await call(body);
      if (!data.ok) {
        const message =
          data.error === "minutes"
            ? "Enter a time first"
            : data.error === "schedule"
              ? "Set a lock or unlock time"
              : data.error || "Could not update";
        setAppErr(message);
        return;
      }
      paint(data);
    } catch {
      setAppErr("Can't reach TV Lock");
    } finally {
      setBusy(false);
    }
  }

  function startCustom(kind) {
    const amount = kind === "lock" ? lockAmt : unlockAmt;
    const unit = kind === "lock" ? lockUnit : unlockUnit;
    const minutes = toMinutes(amount, unit);
    if (!minutes) {
      setAppErr("Enter a time first");
      return;
    }
    act({ action: kind === "lock" ? "lock_after" : "unlock_after", minutes, unit });
  }

  async function addToPhone() {
    const prompt = window.__ytlockInstall;
    if (!prompt) return;
    prompt.prompt();
    await prompt.userChoice;
    window.__ytlockInstall = null;
    setInstall(false);
  }

  const locked = Boolean(view?.locked);
  const tv = view?.tv && view.tv !== "unknown" ? view.tv : "Living room TV";
  const helper = Boolean(view?.helper);
  const until = Number(view?.until || 0);
  const counting = until > Math.floor(Date.now() / 1000);
  const then = view?.then || "";

  return (
    <div className="app">
      <style>{css}</style>
      <div className="top">
        <div className="brand">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M8 11V8a4 4 0 1 1 8 0v3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <rect x="6" y="11" width="12" height="9" rx="2" fill="currentColor" />
          </svg>
          TV Lock
        </div>
        <span className={"chip" + (helper ? "" : " off")}>{helper ? "TV · Connected" : "Helper offline"}</span>
      </div>

      {tab === "control" && (
        <>
          <div className="device">
            <h1>{tv}</h1>
            <p>YouTube on this TV only</p>
          </div>
          <div className="card status">
            <button
              className={"ring" + (locked ? " lock" : "")}
              type="button"
              disabled={busy}
              onClick={() => act({ action: locked ? "unlock" : "lock" })}
              aria-label={locked ? "Unlock YouTube" : "Lock YouTube"}
            >
              <LockMark />
            </button>
            <p className="tap">Tap to {locked ? "unlock" : "lock"}</p>
            <div className="stats">
              <div className="stat">
                <span>{then === "unlock" ? "Unlocks in" : "Locks in"}</span>
                <b>{remainText(until)}</b>
              </div>
              <div className="stat">
                <span>YouTube</span>
                <b>{locked ? "Blocked" : "On"}</b>
              </div>
            </div>
            {locked ? (
              <button className="btn-unlock" type="button" disabled={busy} onClick={() => act({ action: "unlock" })}>
                Instant Unlock
              </button>
            ) : (
              <button className="btn-lock" type="button" disabled={busy} onClick={() => act({ action: "lock" })}>
                Instant Lock TV
              </button>
            )}
          </div>
          <p className="kicker">Quick lock after</p>
          <div className="actions">
            {PRESETS.slice(0, 2).map((item) => (
              <button
                key={item.label}
                className="tile"
                type="button"
                disabled={busy}
                onClick={() => act({ action: "lock_after", minutes: item.minutes })}
              >
                <b>{item.label}</b>
                <span>{item.sub}</span>
              </button>
            ))}
          </div>
        </>
      )}

      {tab === "timers" && (
        <>
          <div className="hero">
            <p className="live">{counting ? "ACTIVE COUNTDOWN" : "NO TIMER"}</p>
            <h1>{counting ? (then === "unlock" ? "Unlocks later" : "Locks later") : "Set a timer"}</h1>
            <p>{view?.label || "YouTube stays on, then locks when the time ends."}</p>
          </div>
          <div className="card" style={{ textAlign: "center" }}>
            <div className="clock" style={{ ["--pct"]: `${remainPct(until)}%` }}>
              <span>{remainText(until)}</span>
            </div>
            <p className="hint">{counting ? "Timer is running on the home server." : "Pick a preset or enter your own time."}</p>
          </div>
          <p className="kicker">Pause quick timers</p>
          <div className="card list">
            {PRESETS.map((item) => (
              <div className="item" key={item.label}>
                <div>
                  <div style={{ fontWeight: 600 }}>{item.label}</div>
                  <p className="hint" style={{ margin: 0 }}>
                    {item.sub}
                  </p>
                </div>
                <button
                  className="btn-quiet"
                  type="button"
                  disabled={busy}
                  onClick={() => act({ action: "lock_after", minutes: item.minutes })}
                >
                  Start
                </button>
              </div>
            ))}
          </div>
          <p className="kicker">Custom duration</p>
          <div className="card">
            <div className="field">
              <label htmlFor="lock-after">Lock after</label>
              <div className="row">
                <input
                  id="lock-after"
                  type="number"
                  min="1"
                  max={lockUnit === "hr" ? 24 : 1440}
                  inputMode="numeric"
                  placeholder="Time"
                  value={lockAmt}
                  onChange={(event) => setLockAmt(event.target.value)}
                />
                <select value={lockUnit} onChange={(event) => setLockUnit(event.target.value)} aria-label="Lock after unit">
                  <option value="min">min</option>
                  <option value="hr">hours</option>
                </select>
                <button className="btn-quiet" type="button" disabled={busy} onClick={() => startCustom("lock")}>
                  Set
                </button>
              </div>
            </div>
            <div className="field">
              <label htmlFor="unlock-after">Unlock after</label>
              <div className="row">
                <input
                  id="unlock-after"
                  type="number"
                  min="1"
                  max={unlockUnit === "hr" ? 24 : 1440}
                  inputMode="numeric"
                  placeholder="Time"
                  value={unlockAmt}
                  onChange={(event) => setUnlockAmt(event.target.value)}
                />
                <select value={unlockUnit} onChange={(event) => setUnlockUnit(event.target.value)} aria-label="Unlock after unit">
                  <option value="min">min</option>
                  <option value="hr">hours</option>
                </select>
                <button className="btn-quiet" type="button" disabled={busy} onClick={() => startCustom("unlock")}>
                  Set
                </button>
              </div>
              <p className="hint">Unlock after locks now, then turns YouTube back on.</p>
            </div>
          </div>
        </>
      )}

      {tab === "schedule" && (
        <>
          <div className="hero">
            <p className="live">AUTOMATION ENGINE</p>
            <h1>Schedules</h1>
            <p>Lock and unlock at the same times every day. Uses the home server clock.</p>
          </div>
          <div className="card">
            <div className="switch-row">
              <div>
                <div style={{ fontWeight: 700 }}>Automated lock schedule</div>
                <p className="hint" style={{ margin: "4px 0 0" }}>
                  {schedOn ? "Rules run every day on this TV." : "Turn on to use lock-at and unlock-at."}
                </p>
              </div>
              <button
                className={"switch" + (schedOn ? " on" : "")}
                type="button"
                aria-pressed={schedOn}
                onClick={() => {
                  const next = !schedOn;
                  setSchedOn(next);
                  act({ action: "schedule", enabled: next, lock_at: lockAt, unlock_at: unlockAt });
                }}
              >
                <i />
              </button>
            </div>
            <div className="field">
              <label htmlFor="lock-at">Lock at</label>
              <input id="lock-at" type="time" value={lockAt} onChange={(event) => setLockAt(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="unlock-at">Unlock at</label>
              <input id="unlock-at" type="time" value={unlockAt} onChange={(event) => setUnlockAt(event.target.value)} />
            </div>
            <button
              className="btn-primary"
              type="button"
              disabled={busy}
              onClick={() => act({ action: "schedule", enabled: true, lock_at: lockAt, unlock_at: unlockAt })}
            >
              Save daily schedule
            </button>
            <p className="hint">Weekly per-day rules and usage graphs are not on this TV. One daily lock and unlock is what the helper can run.</p>
          </div>
        </>
      )}

      {tab === "device" && (
        <>
          <div className="hero">
            <p className="live">PAIRED DISPLAY</p>
            <h1>This TV</h1>
            <p>One set. YouTube on or off. Shorts cannot be blocked on their own.</p>
          </div>
          <div className="card list">
            <div className="item">
              <div>
                <div style={{ fontWeight: 700 }}>{tv}</div>
                <p className="hint" style={{ margin: 0 }}>
                  {helper ? "Helper connected" : "Waiting for the TV"}
                </p>
              </div>
              <span>{locked ? "Locked" : "Unlocked"}</span>
            </div>
            <div className="item">
              <span>YouTube TV</span>
              <span>{locked ? "Blocked" : "Allowed"}</span>
            </div>
            <div className="item">
              <span>Daily schedule</span>
              <span>{schedOn ? `${lockAt} → ${unlockAt}` : "Off"}</span>
            </div>
          </div>
        </>
      )}

      {install ? (
        <button className="btn-quiet" type="button" onClick={addToPhone} style={{ width: "100%", marginTop: 12 }}>
          Install on this phone
        </button>
      ) : null}
      <p className="err">{appErr}</p>
      <nav className="nav">
        <button className={tab === "control" ? "on" : ""} type="button" onClick={() => setTab("control")}>
          <Icon d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z" />
          Control
        </button>
        <button className={tab === "timers" ? "on" : ""} type="button" onClick={() => setTab("timers")}>
          <Icon d="M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" />
          Timers
        </button>
        <button className={tab === "schedule" ? "on" : ""} type="button" onClick={() => setTab("schedule")}>
          <Icon d="M7 3v3M17 3v3M4 9h16M6 5h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z" />
          Schedule
        </button>
        <button className={tab === "device" ? "on" : ""} type="button" onClick={() => setTab("device")}>
          <Icon d="M8 4h8a2 2 0 0 1 2 2v9H6V6a2 2 0 0 1 2-2Zm-3 13h14v2H5v-2Z" />
          TV
        </button>
      </nav>
    </div>
  );
}
