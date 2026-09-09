import type { Analysis } from "../types";

export default function RoofFaces({ result, selected, onSelect, onEdit, objective, setObjective, limit, setLimit, busy }: {
  result: Analysis; selected: string; onSelect: (id: string) => void; onEdit: () => void;
  objective: "capacity" | "energy"; setObjective: (v: "capacity" | "energy") => void;
  limit: string; setLimit: (v: string) => void; busy: boolean;
}) {
  const faces = result.faces || [];
  const face = faces.find(f => f.id === selected);
  const debug = new URLSearchParams(location.search).has("debug");
  return <section className="map-context surface-inspector">
    <div className="map-context-title"><strong>{faces.length} roof faces · independently fitted</strong>
      <button className="text-button" onClick={onEdit} disabled={busy}>Adjust {face ? "this face" : "roof / obstacles"}</button></div>
    <label className="roof-plane-select">Inspect
      <select value={selected} onChange={e => onSelect(e.target.value)}>
        <option value="">Whole building</option>
        {faces.map((f, i) => <option key={f.id} value={f.id}>Face {i + 1} · {f.additional_panel_count} panels · {f.pitch_deg == null ? "projected 2D" : `${f.pitch_deg.toFixed(1)}° pitch`}</option>)}
      </select>
    </label>
    {face ? <>
      <div className="surface-facts">
        <span><b>{face.surface_area_m2} m²</b>{face.geometry_source === "projected_2d" ? "Projected fallback" : "Roof surface"}</span>
        <span><b>{face.projected_area_m2} m²</b>Top-down area</span>
        <span><b>{face.pitch_deg?.toFixed(1) ?? "Unknown"}{face.pitch_deg != null && "°"}</b>Measured pitch</span>
        <span><b>{face.azimuth_deg?.toFixed(0) ?? "—"}{face.azimuth_deg != null && "°"}</b>Azimuth · north = 0°</span>
        <span><b>{face.usable_area_m2} m²</b>Usable surface</span>
        <span><b>{face.additional_panel_count} / {face.additional_kwp.toFixed(2)} kWp</b>New panels / capacity</span>
        <span><b>{face.existing_pv_regions} / {face.obstacle_count}</b>Existing PV regions / obstacles</span>
        {face.solar.irradiation_kwh_m2_year != null && <span><b>{face.solar.irradiation_kwh_m2_year} kWh/m²/year</b>Official irradiation · suitability {face.solar.suitability_class ?? "unknown"}/5</span>}
        {face.annual_energy_kwh != null && <span><b>{face.annual_energy_kwh.toLocaleString()} kWh/year</b>Estimated new production</span>}
      </div>
      {face.geometry_source === "projected_2d" && <p>3D geometry unavailable or unreliable. This face uses projected geometry. Official pitch: {face.official_pitch_deg ?? "unknown"}°.</p>}
      {face.solar.yield_source && <p>{face.solar.yield_source}</p>}
    </> : <p>{result.statistics.surface_area_m2} m² total roof area · {result.statistics.projected_area_m2} m² projected · {result.statistics.fallback_faces || 0} faces using projected fallback. Select a face here or on the map to inspect it.</p>}
    <div className="surface-objective">
      <span>Optimise for</span>
      <button className={objective === "capacity" ? "selected" : ""} onClick={() => setObjective("capacity")}>Maximum capacity</button>
      <button className={objective === "energy" ? "selected" : ""} disabled={!result.energy_available} onClick={() => setObjective("energy")}>Maximum annual energy</button>
      <label>Panel limit (optional)<input aria-label="Maximum number of new panels" type="number" min="1" max="10000" placeholder="Fill all faces" value={limit} onChange={e => setLimit(e.target.value)} /></label>
    </div>
    <p>{!result.energy_available ? "Annual-energy optimisation needs irradiation for every face or a supplied yield. " : ""}{result.objective_note}</p>
    {!!limit && result.energy_available && <div className="surface-facts">
      {Object.entries(result.objective_comparison || {}).map(([key, c]) => <span key={key}><b>{key === "energy" ? "Annual energy" : "Capacity"}</b>{c.panel_count} panels · {c.additional_kwp.toFixed(2)} kWp · {c.annual_energy_kwh?.toLocaleString()} kWh/year</span>)}
    </div>}
    {debug && <details><summary>Roof-plane diagnostics</summary><pre>{JSON.stringify(face?.diagnostics ?? faces.map(f => ({ id: f.id, ...f.diagnostics })), null, 2)}</pre></details>}
  </section>;
}
