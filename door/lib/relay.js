import { authorized, unauthorized } from "./auth";
import { OFFLINE, bridgeOnline, enqueue, waitResult } from "./jobs";

export async function relay(request, path) {
  if (!authorized(request)) return unauthorized();
  let body = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  if (!(await bridgeOnline())) {
    return Response.json(OFFLINE);
  }
  const id = await enqueue(path, body);
  const result = await waitResult(id, 50000);
  if (result) return Response.json(result);
  return Response.json({ pending: true, id }, { status: 202 });
}
