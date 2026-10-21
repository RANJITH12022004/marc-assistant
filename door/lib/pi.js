const BASES = ["http://192.168.68.109:8090", "http://127.0.0.1:8090"];

export async function piFetch(path, options = {}) {
  const token = process.env.MARC_TOKEN || "";
  if (!token) {
    return Response.json({ ok: false, error: "missing token" }, { status: 500 });
  }
  let last = "offline";
  for (const base of BASES) {
    const started = Date.now();
    try {
      const response = await fetch(base + path, {
        method: options.method || "GET",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: options.body,
        cache: "no-store",
      });
      const data = await response.json();
      if (data && typeof data === "object" && data.rtt_ms == null) {
        data.rtt_ms = Date.now() - started;
      }
      return Response.json(data, { status: response.status });
    } catch (exc) {
      last = exc instanceof Error ? exc.message : "offline";
    }
  }
  return Response.json({ ok: false, error: last }, { status: 502 });
}
