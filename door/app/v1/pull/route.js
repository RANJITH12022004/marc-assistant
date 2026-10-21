import { authorized, unauthorized } from "../../../lib/auth";
import { pullJob } from "../../../lib/jobs";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function GET(request) {
  if (!authorized(request)) return unauthorized();
  const job = await pullJob(20000);
  if (!job) return new Response(null, { status: 204 });
  return Response.json(job);
}
