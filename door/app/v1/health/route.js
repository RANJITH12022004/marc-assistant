import { authorized, unauthorized } from "../../../lib/auth";
import { bridgeAge } from "../../../lib/jobs";

export const dynamic = "force-dynamic";

export async function GET(request) {
  if (!authorized(request)) return unauthorized();
  const age = await bridgeAge();
  const online = age != null && age < 30000;
  return Response.json({ ok: true, bridge: online, age_ms: age });
}
