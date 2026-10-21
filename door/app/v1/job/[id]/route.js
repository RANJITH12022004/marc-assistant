import { authorized, unauthorized } from "../../../../lib/auth";
import { readResult } from "../../../../lib/jobs";

export const dynamic = "force-dynamic";

export async function GET(request, context) {
  if (!authorized(request)) return unauthorized();
  const { id } = await context.params;
  const result = await readResult(id);
  if (!result) return Response.json({ pending: true, id }, { status: 202 });
  return Response.json(result);
}
