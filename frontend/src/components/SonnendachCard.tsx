import Help from "./Help";
import type { Analysis } from "../types";

const LABELS: Record<string, string> = {
  faces_screened_out: "Faces not worth covering",
  existing_pv: "Already covered by PV",
  roof_obstacles: "Chimneys, windows, structures",
  shaded: "In shade too much of the day",
  margins_and_module_fit: "Edge margins & module fit",
};

/** Official Sonnendach potential against what can actually be installed. */
export default function SonnendachCard({ result }: { result: Analysis }) {
  const s = result.sonnendach;
  if (!s || !s.official_area_m2) return null;
  const official = s.official_annual_energy_kwh;
  const fitted = s.fitted_annual_energy_kwh;
  const useEnergy = official != null && fitted != null;
  const officialValue = useEnergy ? official : s.official_area_m2;
  const fittedValue = useEnergy ? fitted : s.fitted_module_area_m2;
  const unit = useEnergy ? "kWh/year" : "m²";
  const drop = useEnergy ? s.energy_shortfall_percent : s.area_shortfall_percent;
  const width = officialValue ? Math.max(2, (fittedValue / officialValue) * 100) : 0;
  const parts = Object.entries(s.breakdown_m2).filter(([, v]) => v > 0.05);
  const total = parts.reduce((sum, [, v]) => sum + v, 0);
  const format = (n: number) =>
    useEnergy ? Math.round(n).toLocaleString() : n.toFixed(1);

  return (
    <section className="sonnendach-card">
      <div className="sonnendach-head">
        <span className="eyebrow">REALISTIC vs OFFICIAL POTENTIAL</span>
        <Help title="What this compares">
          <b>Sonnendach</b> is Switzerland's official rooftop solar register. It
          rates the whole roof, but it does not subtract the panels already up
          there, the chimneys, the roof windows, or the faces that are shaded or
          badly oriented.
          <br />
          <br />
          The lower bar is what SolarFit can actually place after taking all of
          that away — and the list below says where every square metre went.
        </Help>
      </div>
      <div className="sonnendach-bars">
        <div>
          <span>Sonnendach says</span>
          <div className="bar official">
            <i style={{ width: "100%" }} />
          </div>
          <strong>
            {format(officialValue)} <small>{unit}</small>
          </strong>
        </div>
        <div>
          <span>Actually installable</span>
          <div className="bar fitted">
            <i style={{ width: `${width}%` }} />
          </div>
          <strong>
            {format(fittedValue)} <small>{unit}</small>
          </strong>
        </div>
      </div>
      {drop != null && (
        <p className="sonnendach-delta">
          <b>−{drop.toFixed(0)}%</b> against the official figure
        </p>
      )}
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
