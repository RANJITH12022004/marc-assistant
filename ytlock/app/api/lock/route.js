import { deviceOk, handle, readPublic } from "../../../lib/store";

export const dynamic = "force-dynamic";

function pinFrom(request, body) {
  const header = request.headers.get("x-ytlock-pin") || "";
  const query = request.nextUrl.searchParams.get("pin") || "";
  return String((body && body.pin) || header || query || "").trim();
}

function isPublic(request) {
  return !deviceOk(request.headers.get("x-ytlock-device") || "");
}

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
}

export async function GET(request) {
  try {
    const publicAccess = isPublic(request);
    const data = await readPublic(pinFrom(request, null), { publicAccess });
    return json(data, data.ok ? 200 : 401);
  } catch {
    return json({ ok: false, error: "store" }, 503);
  }
}

export async function POST(request) {
  try {
    const body = await request.json().catch(() => ({}));
    const publicAccess = isPublic(request);
    const data = await handle(
      {
        action: body.action,
        pin: pinFrom(request, body),
        minutes: body.minutes,
        tv: body.tv,
      },
      { publicAccess },
    );
    if (!data.ok && data.error === "pin") return json(data, 401);
    return json(data);
  } catch {
    return json({ ok: false, error: "store" }, 503);
  }
}
