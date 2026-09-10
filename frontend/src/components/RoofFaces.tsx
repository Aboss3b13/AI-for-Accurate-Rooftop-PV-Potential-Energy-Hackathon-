import type { Analysis } from "../types";

export default function RoofFaces({ result, selected, onSelect, onEdit, objective, setObjective, limit, setLimit, busy,
  policy, setPolicy, annualUse, setAnnualUse, existingGeneration, setExistingGeneration }: {
  result: Analysis; selected: string; onSelect: (id: string) => void; onEdit: () => void;
  objective: "capacity" | "energy"; setObjective: (v: "capacity" | "energy") => void;
  limit: string; setLimit: (v: string) => void; busy: boolean;
  policy: "recommended" | "physical"; setPolicy: (v: "recommended" | "physical") => void;
  annualUse: string; setAnnualUse: (v: string) => void;
  existingGeneration: string; setExistingGeneration: (v: string) => void;
}) {
  const faces = result.faces || [];
  const face = faces.find(f => f.id === selected);
  const debug = new URLSearchParams(location.search).has("debug");
  return <section className="map-context surface-inspector">
    {result.assessment && <div className="site-assessment">
      <strong>{result.assessment.title}</strong>
      <p>{result.assessment.proposed_panel_count} proposed modules · {result.assessment.physical_panel_capacity} could fit before suitability screening.</p>
      <p>{result.assessment.demand_note}</p>
      {result.assessment.remaining_annual_target_kwh != null && <p>Remaining annual target: {result.assessment.remaining_annual_target_kwh.toLocaleString()} kWh.
        {result.assessment.annual_target_coverage_percent != null && ` Proposed production: ${result.assessment.annual_target_coverage_percent}% of that annual target.`}</p>}
      <details><summary>What this assessment considers</summary>
        {result.assessment.factors.map(f => <p key={f.factor}><b>{f.factor}:</b> {f.basis}</p>)}
      </details>
    </div>}
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
        <span><b>{face.pitch_deg?.toFixed(1) ?? "Unknown"}{face.pitch_deg != null && "°"}</b>{face.geometry_source === "sonnendach" ? "Official roof pitch" : "DSM-derived pitch"}</span>
        <span><b>{face.azimuth_deg?.toFixed(0) ?? "—"}{face.azimuth_deg != null && "°"}</b>Azimuth · north = 0°</span>
        <span><b>{face.usable_area_m2} m²</b>Usable surface</span>
        <span><b>{face.additional_panel_count} / {face.additional_kwp.toFixed(2)} kWp</b>New panels / capacity</span>
        <span><b>{face.existing_pv_regions} / {face.obstacle_count}</b>Existing PV regions / obstacles</span>
        {face.dimensions && <span><b>{face.dimensions.length_m} × {face.dimensions.width_m} m</b>Surface span · enclosing rectangle</span>}
        {face.sunlight?.mean_direct_sun_access != null && <span><b>{Math.round(face.sunlight.mean_direct_sun_access*100)}% / {Math.round((face.sunlight.winter_direct_sun_access ?? 0)*100)}%</b>Sampled direct-sun access · annual / winter</span>}
        {face.solar.irradiation_kwh_m2_year != null && <span><b>{face.solar.irradiation_kwh_m2_year} kWh/m²/year</b>Official irradiation · suitability {face.solar.suitability_class ?? "unknown"}/5</span>}
        {face.annual_energy_kwh != null && <span><b>{face.annual_energy_kwh.toLocaleString()} kWh/year</b>Estimated new production</span>}
      </div>
      {face.geometry_source === "projected_2d" && <p>3D geometry unavailable or unreliable. This face uses projected geometry. Official pitch: {face.official_pitch_deg ?? "unknown"}°.</p>}
      {face.solar.yield_source && <p>{face.solar.yield_source}</p>}
      {face.assessment && <div className="face-verdict"><b>{face.assessment.status.replaceAll("_", " ")}</b>
        {[...face.assessment.reasons, ...face.assessment.cautions].map(reason => <p key={reason}>{reason}</p>)}
      </div>}
      {face.sunlight?.available && <p>Shade checks use seasonal sun paths and buildings, trees and terrain within {face.sunlight.radius_m} m. Direct-sun access is a geometric screening score, not the percentage of annual electricity retained.</p>}
    </> : <p>{result.statistics.surface_area_m2} m² total roof area · {result.statistics.projected_area_m2} m² projected · {result.statistics.fallback_faces || 0} faces using projected fallback. Select a face here or on the map to inspect it.</p>}
    <div className="surface-objective">
      <label><input type="checkbox" checked={policy === "recommended"} onChange={e => setPolicy(e.target.checked ? "recommended" : "physical")} />Screen for sunlight and practical panel groups</label>
    </div>
    <details className="demand-settings"><summary>Size to electricity use (optional)</summary>
      <div className="surface-objective">
        <label>Annual electricity use (kWh)<input type="number" min="0" max="10000000" value={annualUse} placeholder="Unknown" onChange={e => setAnnualUse(e.target.value)} /></label>
        <label>Existing PV production (kWh/year)<input type="number" min="0" max="10000000" value={existingGeneration} placeholder="0 if none" onChange={e => setExistingGeneration(e.target.value)} /></label>
      </div>
      <p>Enter both values to limit new panels to an annual-energy target. Annual balance does not guarantee self-sufficiency at night or in winter.</p>
    </details>
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
