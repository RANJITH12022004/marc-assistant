"use client";

import { useEffect, useRef, useState } from "react";

const AMBER = "#E8B15A";
const RED = "#FF453A";
const WHITE = "#F5F5F7";
const START = (150 * Math.PI) / 180;
const SWEEP = (240 * Math.PI) / 180;

function clamp(value) {
  return Math.max(0, Math.min(1, value));
}

function Dial({ fraction, value, caption, satellite }) {
  const canvasRef = useRef(null);
  const shown = useRef(0);
  const velocity = useRef(0);
  const target = useRef(0);
  const rising = useRef(true);
  const held = useRef(false);

  useEffect(() => {
    const next = clamp(fraction || 0);
    if (!held.current) {
      shown.current = 0;
      velocity.current = 0;
      held.current = true;
    }
    const delta = next - shown.current;
    rising.current = delta >= 0;
    target.current = next;
    if (Math.abs(delta) >= 0.003) velocity.current += delta * 6;
  }, [fraction]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    let frame = 0;
    let last = 0;
    const draw = (now) => {
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
      last = now;
      const stiff = rising.current ? 340 : 72;
      const damp = rising.current ? 13.5 : 8.5;
      velocity.current += (stiff * (target.current - shown.current) - damp * velocity.current) * dt;
      shown.current += velocity.current * dt;
      if (Math.abs(target.current - shown.current) < 0.008 && Math.abs(velocity.current) < 0.03) {
        shown.current = target.current;
        velocity.current = 0;
      }
      paint(canvas, shown.current, value, caption, satellite);
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [value, caption, satellite]);

  return <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />;
}

function paint(canvas, shown, value, caption, satellite) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(rect.width * ratio));
  const height = Math.max(1, Math.floor(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);
  const size = Math.min(width, height) * 0.92;
  const cx = width / 2;
  const cy = height / 2;
  const radius = size / 2;
  const draw = clamp(shown);
  const hot = draw >= 0.82;
  const lit = hot ? RED : AMBER;
  ctx.strokeStyle = WHITE;
  ctx.lineWidth = Math.max(2 * ratio, radius * 0.035);
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.96, 0, Math.PI * 2);
  ctx.stroke();
  const bandR = radius * 0.78;
  ctx.strokeStyle = "rgba(255,69,58,0.45)";
  ctx.lineWidth = Math.max(3 * ratio, radius * 0.08);
  ctx.beginPath();
  ctx.arc(cx, cy, bandR, START + SWEEP * 0.82, START + SWEEP, false);
  ctx.stroke();
  for (let i = 0; i <= 12; i += 1) {
    const t = i / 12;
    const ang = START + SWEEP * t;
    ctx.strokeStyle = t >= 0.82 ? RED : "rgba(232,177,90,0.45)";
    ctx.lineWidth = Math.max(1.2 * ratio, radius * 0.02);
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(ang) * radius * 0.86, cy + Math.sin(ang) * radius * 0.86);
    ctx.lineTo(cx + Math.cos(ang) * radius * 0.93, cy + Math.sin(ang) * radius * 0.93);
    ctx.stroke();
  }
  if (draw > 0.004) {
    ctx.strokeStyle = lit;
    ctx.lineWidth = Math.max(2.5 * ratio, radius * (satellite ? 0.055 : 0.07));
    ctx.lineCap = "butt";
    ctx.beginPath();
    ctx.arc(cx, cy, bandR, START, START + SWEEP * draw, false);
    ctx.stroke();
  }
  const ang = START + SWEEP * draw;
  const reach = radius * (satellite ? 0.7 : 0.76);
  const tail = radius * 0.12;
  const cos = Math.cos(ang);
  const sin = Math.sin(ang);
  ctx.strokeStyle = WHITE;
  ctx.lineWidth = Math.max(2 * ratio, radius * 0.028);
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(cx - cos * tail, cy - sin * tail);
  ctx.lineTo(cx + cos * reach, cy + sin * reach);
  ctx.stroke();
  ctx.strokeStyle = lit;
  ctx.lineWidth = Math.max(2.4 * ratio, radius * 0.038);
  ctx.beginPath();
  ctx.moveTo(cx + cos * reach * 0.72, cy + sin * reach * 0.72);
  ctx.lineTo(cx + cos * reach, cy + sin * reach);
  ctx.stroke();
  ctx.fillStyle = WHITE;
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.048, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#101010";
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.024, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = WHITE;
  ctx.font = `700 ${radius * (satellite ? 0.26 : 0.34)}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(value || "—", cx, cy - radius * 0.04);
  ctx.fillStyle = AMBER;
  ctx.font = `500 ${radius * 0.11}px sans-serif`;
  ctx.fillText(caption || "", cx, cy + radius * 0.18);
}

function rateLabel(bps) {
  if (bps >= 1000000) return `${(bps / 1000000).toFixed(1)} MB/s`;
  if (bps >= 1000) return `${Math.round(bps / 1000)} KB/s`;
  return `${bps} B/s`;
}

function linkFraction(bps, connected) {
  if (!connected) return 0;
  if (bps <= 0) return 0.07;
  return Math.max(0.07, Math.min(1, Math.log10(1 + bps) / Math.log10(1 + 1500000)));
}

function pct(value) {
  return `${Math.round(value)}%`;
}

function size(bytes) {
  if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(1)} GB`;
  return `${Math.round(bytes / 1048576)} MB`;
}

function uptime(seconds) {
  const minutes = Math.max(0, seconds) / 60;
  if (minutes < 60) return `${Math.floor(minutes)}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ${Math.floor(minutes % 60)}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

function storeOf(status) {
  const volumes = status.volumes || [];
  let used = 0;
  let total = 0;
  volumes.forEach((volume) => {
    if (volume.count) {
      used += volume.used || 0;
      total += volume.total || 0;
    }
  });
  if (total <= 0 && status.disk) {
    used = status.disk.used || 0;
    total = status.disk.total || 0;
  }
  return { used, total, fraction: total ? used / total : 0 };
}

function machinesOf(data) {
  const listed = Array.isArray(data.machines) ? data.machines.filter(Boolean) : [];
  if (listed.length) return listed.join(" · ");
  if (data.phone_steps && data.phone_steps.length) return "phone";
  if (data.confirm) return "confirm";
  return "laptop";
}

export default function Desk() {
  const [status, setStatus] = useState(null);
  const [lines, setLines] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const scroller = useRef(null);

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const tick = async () => {
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (response.ok) {
          const data = await response.json();
          if (!stop && data && data.cpu_pct != null) setStatus(data);
        }
      } catch {
        /* keep the last reading */
      }
      if (!stop) timer = window.setTimeout(tick, 3000);
    };
    tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [lines]);

  async function send(event) {
    event.preventDefault();
    const said = text.trim();
    if (!said || busy) return;
    setText("");
    setBusy(true);
    setLines((current) => [...current, { who: "you", text: said }, { who: "marc", text: "Thinking", machine: "" }]);
    try {
      const response = await fetch("/api/utterance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: said }),
      });
      const data = await response.json();
      const failed = !response.ok || data.ok === false;
      const spoken = data.spoken || (failed ? data.error || "I need a connection for that." : "Done.");
      setLines((current) => [
        ...current.slice(0, -1),
        {
          who: "marc",
          text: spoken,
          machine: failed ? "" : machinesOf(data),
          confirm: data.confirm || null,
        },
      ]);
    } catch {
      setLines((current) => [...current.slice(0, -1), { who: "marc", text: "I need a connection for that.", machine: "" }]);
    } finally {
      setBusy(false);
    }
  }

  async function answer(token, yes) {
    setLines((current) => current.map((line) => (line.confirm && line.confirm.token === token ? { ...line, confirm: null } : line)));
    try {
      const response = await fetch("/api/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, yes }),
      });
      const data = await response.json();
      setLines((current) => [...current, { who: "marc", text: data.spoken || "Done.", machine: machinesOf(data) }]);
    } catch {
      setLines((current) => [...current, { who: "marc", text: "I need a connection for that.", machine: "" }]);
    }
  }

  const live = status || {};
  const temp = Number(live.temp_c || 0);
  const cpu = Number(live.cpu_pct || 0);
  const mem = live.mem || {};
  const memFrac = mem.total ? mem.used / mem.total : 0;
  const store = storeOf(live);
  const net = live.net || {};
  const flow = Number(net.rx_bps || 0) + Number(net.tx_bps || 0);
  const link = linkFraction(flow, Boolean(status));
  const load = live.load || [];
  const loadText = load.length >= 3 ? load.slice(0, 3).map((n) => Number(n).toFixed(2)).join("  ") : "—";
  const hot = temp >= 80;

  return (
    <main style={{ minHeight: "100vh", display: "grid", gridTemplateColumns: "minmax(0, 1.45fr) minmax(280px, 0.7fr)", background: "#000", color: WHITE, fontFamily: "system-ui, sans-serif" }}>
      <section style={{ padding: "28px 32px 24px", display: "flex", flexDirection: "column", minWidth: 0 }}>
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 28, letterSpacing: 0.4 }}>Marc</div>
            <div style={{ color: AMBER, marginTop: 4 }}>{status ? "Idle" : "Away"}</div>
          </div>
          <div style={{ color: hot ? RED : AMBER }}>{status ? (hot ? "Hot" : "Here") : "Away"}</div>
        </header>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", height: 280, marginTop: 12 }}>
          <Dial fraction={status ? cpu / 100 : 0} value={status ? pct(cpu) : "—"} caption="CPU" />
          <Dial fraction={status ? clamp((temp - 40) / 60) : 0} value={status ? `${Math.round(temp)}°` : "—"} caption="TEMP" />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", height: 180 }}>
          <Dial satellite fraction={memFrac} value={status ? pct(memFrac * 100) : "—"} caption="RAM" />
          <Dial satellite fraction={store.fraction} value={status ? pct(store.fraction * 100) : "—"} caption="STORE" />
          <Dial satellite fraction={link} value={status ? (flow <= 0 ? "Idle" : rateLabel(flow)) : "—"} caption="LINK" />
        </div>
        <p style={{ textAlign: "center", color: "#c8c8cc", lineHeight: 1.6, marginTop: 8, whiteSpace: "pre-line" }}>
          {status
            ? `Load ${loadText}\nUp ${uptime(live.uptime_s || 0)}   ·   ${live.cpu_mhz || 0} MHz   ·   Core ${Number(live.core_v || 0).toFixed(2)} V   ·   Supply ${live.supply || "—"}`
            : "No reading"}
        </p>
      </section>
      <section style={{ borderLeft: "1px solid rgba(232,177,90,0.35)", display: "flex", flexDirection: "column", minHeight: "100vh" }}>
        <div style={{ padding: "22px 20px 8px", color: AMBER, letterSpacing: 0.6 }}>Chat</div>
        <div ref={scroller} style={{ flex: 1, overflow: "auto", padding: "8px 20px 12px" }}>
          {lines.length === 0 ? <p style={{ color: "#8e8e93" }}>Say what should happen on the laptop or the phone.</p> : null}
          {lines.map((line, index) => (
            <div key={`${line.who}-${index}`} style={{ marginBottom: 14 }}>
              <div style={{ color: line.who === "you" ? WHITE : AMBER, whiteSpace: "pre-wrap" }}>{line.text}</div>
              {line.machine ? <div style={{ color: "#8e8e93", fontSize: 12, marginTop: 4 }}>{line.machine}</div> : null}
              {line.confirm ? (
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <button type="button" onClick={() => answer(line.confirm.token, true)} style={buttonStyle}>Yes</button>
                  <button type="button" onClick={() => answer(line.confirm.token, false)} style={buttonStyle}>No</button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
        <form onSubmit={send} style={{ display: "flex", gap: 8, padding: 16 }}>
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Tell Marc"
            style={{ flex: 1, background: "#101010", color: WHITE, border: "1px solid rgba(232,177,90,0.45)", borderRadius: 8, padding: "12px 14px" }}
          />
          <button type="submit" disabled={busy} style={{ ...buttonStyle, opacity: busy ? 0.5 : 1 }}>Send</button>
        </form>
      </section>
    </main>
  );
}

const buttonStyle = {
  background: "transparent",
  color: AMBER,
  border: "1px solid rgba(232,177,90,0.7)",
  borderRadius: 8,
  padding: "10px 14px",
  cursor: "pointer",
};
