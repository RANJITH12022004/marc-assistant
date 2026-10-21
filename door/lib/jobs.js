import { get, put } from "@vercel/blob";

export const OFFLINE = { spoken: "Can't reach Marc", confirm: null, phone_steps: [] };

const BRIDGE = "marc/bridge.txt";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readText(pathname) {
  try {
    const file = await get(pathname, { access: "private" });
    if (!file || !file.stream) return null;
    const text = await new Response(file.stream).text();
    return text || null;
  } catch (err) {
    const message = String(err && err.message ? err.message : err);
    if (message.toLowerCase().includes("not found") || err?.name === "BlobNotFoundError") {
      return null;
    }
    throw err;
  }
}

async function writeText(pathname, text) {
  await put(pathname, text, {
    access: "private",
    addRandomSuffix: false,
    allowOverwrite: true,
    contentType: "application/json",
    cacheControlMaxAge: 0,
  });
}

export async function bridgeAge() {
  const text = await readText(BRIDGE);
  if (!text) return null;
  const beat = Number(text);
  if (!beat) return null;
  return Date.now() - beat;
}

export async function bridgeOnline() {
  const age = await bridgeAge();
  return age != null && age < 30000;
}

export async function enqueue(path, body) {
  const id = crypto.randomUUID();
  await writeText(
    `marc/queue/${id}.json`,
    JSON.stringify({ id, path, body, at: Date.now() }),
  );
  for (let attempt = 0; attempt < 4; attempt++) {
    if (await readText(`marc/claim/${id}.txt`)) return id;
    const ids = await readIds();
    if (!ids.includes(id)) ids.push(id);
    await writeText("marc/next.txt", JSON.stringify(ids));
    const again = await readIds();
    if (again.includes(id) || (await readText(`marc/claim/${id}.txt`))) return id;
    await sleep(40);
  }
  return id;
}

async function readIds() {
  const raw = await readText("marc/next.txt");
  if (!raw) return [];
  try {
    const ids = JSON.parse(raw);
    return Array.isArray(ids) ? ids : [];
  } catch {
    return [];
  }
}

async function oldestJob() {
  const ids = await readIds();
  if (!ids.length) return null;
  const id = ids[0];
  await writeText("marc/next.txt", JSON.stringify(ids.slice(1)));
  if (await readText(`marc/claim/${id}.txt`)) return null;
  await writeText(`marc/claim/${id}.txt`, String(Date.now()));
  const text = await readText(`marc/queue/${id}.json`);
  if (!text) return null;
  return JSON.parse(text);
}

export async function pullJob(waitMs) {
  const deadline = Date.now() + waitMs;
  let touched = 0;
  while (Date.now() < deadline) {
    if (Date.now() - touched > 5000) {
      await writeText(BRIDGE, String(Date.now()));
      touched = Date.now();
    }
    const job = await oldestJob();
    if (job) return job;
    await sleep(400);
  }
  return null;
}

export async function waitResult(id, waitMs) {
  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    const text = await readText(`marc/result/${id}.json`);
    if (text) return JSON.parse(text);
    await sleep(300);
  }
  return null;
}

export async function putResult(id, body) {
  await writeText(`marc/result/${id}.json`, JSON.stringify(body));
}

export async function readResult(id) {
  const text = await readText(`marc/result/${id}.json`);
  return text ? JSON.parse(text) : null;
}

const STATUS = "marc/status.json";

export async function putStatus(body) {
  await writeText(STATUS, JSON.stringify({ at: Date.now(), status: body || {} }));
}

export async function readStatus() {
  const text = await readText(STATUS);
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    const at = Number(parsed.at || 0);
    return { age_ms: at ? Date.now() - at : null, status: parsed.status || null };
  } catch {
    return null;
  }
}
