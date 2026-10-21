import { authorized, unauthorized } from "../../../lib/auth";
import { putStatus, readStatus } from "../../../lib/jobs";

export const dynamic = "force-dynamic";

export async function GET(request) {
  if (!authorized(request)) return unauthorized();
  const snap = await readStatus();
  if (!snap || !snap.status) {
    return Response.json({ ok: false, away: true }, { status: 404 });
  }
  return Response.json({ ok: true, age_ms: snap.age_ms, status: snap.status });
}

export async function POST(request) {
  if (!authorized(request)) return unauthorized();
  const body = await request.json();
  await putStatus(body || {});
  return Response.json({ ok: true });
}
