import { createHash, timingSafeEqual } from "crypto";
import { get, put } from "@vercel/blob";

const PATH = "ytlock/state.json";

const MAX_MINUTES = 24 * 60;

function blank() {
  return { locked: false, until: 0, then: "", updated: 0, tv: "unknown", pinHash: "" };
}

function minutesOf({ minutes, unit } = {}) {
  const n = Number.parseInt(String(minutes ?? ""), 10);
  if (!Number.isFinite(n) || n < 1) return 0;
  const raw = ["h", "hr", "hour", "hours"].includes(String(unit || "min").trim().toLowerCase()) ? n * 60 : n;
  return Math.min(raw, MAX_MINUTES);
}

function span(remain) {
  const minutes = Math.max(1, Math.ceil(Number(remain || 0) / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins ? `${hours}h ${mins}m` : `${hours}h`;
}

function digest(pin) {
  return createHash("sha256")
    .update("ytlock:" + String(pin || ""))
    .digest("hex");
}

function same(left, right) {
  const a = Buffer.from(String(left || ""));
  const b = Buffer.from(String(right || ""));
  if (!a.length || a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

function envPinHash() {
  const pin = String(process.env.YTLOCK_PIN || "").trim();
  return pin ? digest(pin) : "";
}

export function pinHashOf(state) {
  return String(state?.pinHash || envPinHash() || "");
}

export function needsSetup(state) {
  return !pinHashOf(state);
}

export function pinOk(state, pin) {
  const stored = pinHashOf(state);
  const got = String(pin || "").trim();
  if (!stored || !got) return false;
  if (stored.length === 64 && /^[0-9a-f]+$/i.test(stored)) {
    return same(stored, digest(got));
  }
  return same(stored, got);
}

export function deviceOk(header) {
  return same(process.env.YTLOCK_DEVICE || "", header);
}

async function readText() {
  try {
    const file = await get(PATH, { access: "private" });
    if (!file || !file.stream) return null;
    return (await new Response(file.stream).text()) || null;
  } catch (err) {
    const message = String(err && err.message ? err.message : err).toLowerCase();
    if (message.includes("not found") || err?.name === "BlobNotFoundError") return null;
    throw err;
  }
}

export async function load() {
  const data = blank();
  const raw = await readText();
  if (!raw) return data;
  let loaded = {};
  try {
    loaded = JSON.parse(raw);
  } catch {
    return data;
  }
  if (!loaded || typeof loaded !== "object") return data;
  data.locked = Boolean(loaded.locked);
  data.until = Number(loaded.until || 0) || 0;
  data.updated = Number(loaded.updated || 0) || 0;
  data.tv = String(loaded.tv || "unknown").slice(0, 40);
  data.pinHash = String(loaded.pinHash || "");
  const then = String(loaded.then || "").trim().toLowerCase();
  data.then = then === "lock" || then === "unlock" ? then : "";
  return data;
}

export async function save(state) {
  await put(PATH, JSON.stringify(state), {
    access: "private",
    addRandomSuffix: false,
    allowOverwrite: true,
    contentType: "application/json",
    cacheControlMaxAge: 0,
  });
}

export function expire(state) {
  const until = Number(state.until || 0) || 0;
  if (until && Date.now() / 1000 >= until) {
    const then = String(state.then || "lock").trim().toLowerCase();
    state.locked = then !== "unlock";
    state.until = 0;
    state.then = "";
    state.updated = Math.floor(Date.now() / 1000);
  }
  return state;
}

export async function loadLive() {
  const before = await load();
  const snapshot = JSON.stringify(before);
  const state = expire(before);
  if (JSON.stringify(state) !== snapshot) await save(state);
  return state;
}

export function publicView(state) {
  const until = Number(state.until || 0) || 0;
  const remain = until ? Math.max(0, until - Math.floor(Date.now() / 1000)) : 0;
  const locked = Boolean(state.locked);
  const then = String(state.then || "").trim().toLowerCase();
  let label = "YouTube is unlocked";
  if (remain && then === "unlock") label = `Locked for ${span(remain)}, then unlocks`;
  else if (remain) label = `On for ${span(remain)}, then locks`;
  else if (locked) label = "YouTube is locked on the TV";
  return {
    ok: true,
    locked,
    until,
    then,
    remain_s: remain,
    tv: state.tv || "unknown",
    setup: needsSetup(state),
    label,
  };
}

export async function handle({ action, pin, minutes, unit, tv }, { publicAccess }) {
  let state = await loadLive();
  const verb = String(action || "").trim().toLowerCase();
  if (verb === "setup") {
    if (pinHashOf(state)) return { ok: false, error: "already set" };
    if (String(pin || "").trim().length < 4) return { ok: false, error: "pin too short" };
    state.pinHash = digest(String(pin).trim());
    state.updated = Math.floor(Date.now() / 1000);
    await save(state);
    return { ...publicView(state), setup: false };
  }
  if (publicAccess && !pinOk(state, pin)) {
    return { ok: false, error: "pin", setup: needsSetup(state) };
  }
  if (verb === "lock") {
    state.locked = true;
    state.until = 0;
    state.then = "";
  } else if (verb === "unlock") {
    state.locked = false;
    state.until = 0;
    state.then = "";
  } else if (verb === "timer" || verb === "lock_after") {
    const wait = minutesOf({ minutes, unit });
    if (wait < 1) return { ok: false, error: "minutes" };
    state.locked = false;
    state.until = Math.floor(Date.now() / 1000) + wait * 60;
    state.then = "lock";
  } else if (verb === "unlock_after") {
    const wait = minutesOf({ minutes, unit });
    if (wait < 1) return { ok: false, error: "minutes" };
    state.locked = true;
    state.until = Math.floor(Date.now() / 1000) + wait * 60;
    state.then = "unlock";
  } else if (verb === "tv") {
    state.tv = String(tv || state.tv || "unknown").slice(0, 40);
  } else {
    return publicView(state);
  }
  state.updated = Math.floor(Date.now() / 1000);
  await save(state);
  return publicView(state);
}

export async function readPublic(pin, { publicAccess }) {
  const state = await loadLive();
  if (publicAccess) {
    if (needsSetup(state)) {
      return {
        ok: true,
        setup: true,
        locked: false,
        until: 0,
        remain_s: 0,
        label: "Set a parent PIN",
      };
    }
    if (!pinOk(state, pin)) return { ok: false, error: "pin", setup: false };
  }
  return publicView(state);
}
