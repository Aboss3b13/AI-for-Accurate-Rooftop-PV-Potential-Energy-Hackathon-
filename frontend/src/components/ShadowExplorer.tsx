import { useEffect, useState } from "react";
import { api } from "../http";
import type { Geometry } from "../types";

export type ShadowPreview = { captureId: string; shade: Geometry; unknown: Geometry };

export default function ShadowExplorer({ captureId, onChange }: {
  captureId: string;
  onChange: (value: ShadowPreview | null) => void;
}) {
  const [enabled, setEnabled] = useState(false);
  const [month, setMonth] = useState(6);
  const [hour, setHour] = useState(12);
  const [status, setStatus] = useState("");
  useEffect(() => {
    onChange(null);
    if (!enabled) return;
    const controller = new AbortController();
    setStatus("Calculating shadows…");
    const timer = setTimeout(async () => {
      try {
        const response = await api(`/api/map/shadow/${encodeURIComponent(captureId)}?month=${month}&hour_utc=${hour}`, { signal: controller.signal });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Shadow preview unavailable.");
        if (controller.signal.aborted) return;
        onChange({ captureId, shade: data.shade, unknown: data.unknown });
        setStatus(`Sun elevation ${data.sun_elevation_deg}°. Purple: shade. Grey: unknown height coverage.`);
      } catch (error) {
        if (!controller.signal.aborted) setStatus(error instanceof Error ? error.message : "Shadow preview unavailable.");
      }
    }, 120);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [captureId, enabled, month, hour, onChange]);
  return <div className="shadow-explorer">
    <label><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> Explore local shadows</label>
    {enabled && <>
      <label>Representative date <select value={month} onChange={e => setMonth(Number(e.target.value))}>
        {Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{new Date(2025, i, 21).toLocaleDateString("en", { month: "long", day: "numeric" })}</option>)}
      </select></label>
      <label>Time {String(Math.floor(hour)).padStart(2, "0")}:{hour % 1 ? "30" : "00"} UTC
        <input type="range" min="0" max="23.5" step="0.5" value={hour} onChange={e => setHour(Number(e.target.value))} />
      </label>
      <small role="status">{status}</small>
      <small>Original surveyed roof; static vegetation and nearby buildings within 120 m. Swiss local time is UTC+1 in winter and UTC+2 in summer. This preview does not change panel placement or annual energy.</small>
    </>}
  </div>;
}
