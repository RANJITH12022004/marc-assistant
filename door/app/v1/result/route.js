import { authorized, unauthorized } from "../../../lib/auth";
import { putResult } from "../../../lib/jobs";

export const dynamic = "force-dynamic";
export const maxDuration = 15;

export async function POST(request) {
  if (!authorized(request)) return unauthorized();
  const payload = await request.json();
  if (!payload || !payload.id) {
    return Response.json({ ok: false, error: "missing id" }, { status: 400 });
  }
  await putResult(payload.id, payload.body ?? {});
  return Response.json({ ok: true });
}
