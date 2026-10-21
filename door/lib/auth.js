const TOKEN = process.env.MARC_TOKEN || "";

export function authorized(request) {
  if (!TOKEN) return false;
  const header = request.headers.get("authorization") || "";
  return header === `Bearer ${TOKEN}`;
}

export function unauthorized() {
  return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
}
