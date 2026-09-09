import Help from "./Help";
import type { Analysis } from "../types";

const LABELS: Record<string, string> = {
  faces_screened_out: "Faces excluded by screening",
  existing_pv: "Already covered by PV",
  roof_obstacles: "Chimneys, windows, structures",
  shaded: "In shade too much of the day",
  margins_and_module_fit: "Margins, module fit & sizing limits",
};

/** Official Sonnendach potential against what can actually be installed. */
export default function SonnendachCard({ result }: { result: Analysis }) {
  const s = result.sonnendach;
  if (!s || !s.official_area_m2) return null;
  const parts = Object.entries(s.breakdown_m2).filter(([, v]) => v > 0.05);
  const total = parts.reduce((sum, [, v]) => sum + v, 0);

  return (
    <section className="sonnendach-card">
      <div className="sonnendach-head">
        <span className="eyebrow">REALISTIC vs OFFICIAL POTENTIAL</span>
        <Help title="Different definitions">
          Sonnendach publishes inclined roof area and theoretical yield, including source-model shading.
          SolarFit estimates additional modules after current occupancy and your planning settings.
          This is not a like-for-like accuracy comparison or installation approval.
        </Help>
      </div>
      <div className="sonnendach-bars">
        <div><span>Sonnendach theoretical roof potential</span>
          <strong>{s.official_area_m2.toFixed(1)} <small>m2 roof surface</small></strong>
          <strong>{s.official_annual_energy_kwh?.toLocaleString() ?? "Unknown"} <small>kWh/year (source model)</small></strong>
        </div>
        <div><span>SolarFit additional potential</span>
          <strong>{result.statistics.additional_panel_count} <small>modules / {result.statistics.additional_kwp.toFixed(2)} kWp</small></strong>
          <strong>{s.fitted_annual_energy_kwh?.toLocaleString() ?? "Unknown"} <small>kWh/year (planning estimate)</small></strong>
        </div>
      </div>
      <dl className="sonnendach-breakdown">
        <dt className="sonnendach-why">Where the roof goes</dt>
        {parts.map(([key, value]) => (
          <div key={key}>
            <dt>{LABELS[key] ?? key}</dt>
            <dd>
              <i style={{ width: `${total ? (value / total) * 100 : 0}%` }} />
              <span>{value.toFixed(1)} m²</span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="sonnendach-basis">{s.basis}</p>
    </section>
  );
}
