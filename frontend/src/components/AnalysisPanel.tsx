import {
  Sun,
  Zap,
  ScanLine,
  AlertCircle,
  LoaderCircle,
  ArrowUpRight,
  Download,
} from "lucide-react";
import Help from "./Help";
import type { Analysis, Mode } from "../types";
type Props = {
  result: Analysis | null;
  busy: boolean;
  ready: boolean;
  mode: Mode;
  setMode: (mode: Mode) => void;
  error: string;
  analyse: () => Promise<void>;
  exportJson: () => void;
  model: string;
  comparisons: Partial<Record<Mode, number>>;
};
const MODES: Mode[] = ["conservative", "recommended", "maximum"];
export default function AnalysisPanel({
  result,
  busy,
  ready,
  mode,
  setMode,
  error,
  analyse,
  exportJson,
  model,
  comparisons,
}: Props) {
  const stats = result?.statistics;
  return (
    <aside>
      <div className="result-card">
        <div className="result-top">
          <span className="eyebrow">SOLARFIT ANALYSIS</span>
          <span className="live-pill">
            {busy ? "Processing" : stats ? "Complete" : "Ready when you are"}
          </span>
        </div>
        <h2>Room for more.</h2>
        <p className="muted">Additional capacity, fitted to your roof.</p>
        <div className="hero-stat">
          <span>{stats ? stats.additional_panel_count : "—"}</span>
          <div>
            additional
            <br />
            solar panels
          </div>
          <span className="stat-icon">
            <Sun size={26} />
          </span>
        </div>
        <div className="capacity">
          <Zap size={19} />
          <strong>
            {stats ? stats.additional_kwp.toFixed(2) : "—"} <small>kWp</small>
          </strong>
          <span>additional capacity</span>
          <Help title="kWp">
            Kilowatt-peak is the power the new panels would make at full
            sunshine. It is the number installers quote. A typical Swiss house
            fits somewhere around 5–15 kWp.
          </Help>
        </div>
        <div className="mode-control-head">
          <span>How tightly to pack the panels</span>
          <Help title="Conservative, Recommended, Maximum">
            How much empty space to leave around roof edges, chimneys and
            existing panels. <b>Conservative</b> leaves the most room and gives
            the safest number. <b>Recommended</b> is a sensible first estimate.
            <b> Maximum</b> packs them tightest and needs an installer to confirm
            it is buildable.
          </Help>
        </div>
        <div className="mode-control">
          {MODES.map((m) => (
            <button
              key={m}
              className={mode === m ? "selected" : ""}
              onClick={() => setMode(m)}
            >
              {m === "conservative"
                ? "Conservative"
                : m === "recommended"
                  ? "Recommended"
                  : "Maximum"}
            </button>
          ))}
        </div>
        <p className="mode-note">
          {mode === "conservative"
            ? "More clearance around roof edges and obstacles."
            : mode === "recommended"
              ? "Balanced clearances for a practical first estimate."
              : "Tighter clearances. Requires careful installation review."}
        </p>
        <dl className="metrics">
          <div>
            <dt>
              Existing PV regions
              <Help title="Existing PV regions">
                Areas where the AI found solar panels already installed. Those are left alone — SolarFit only counts panels you could still add.
              </Help>
            </dt>
            <dd>{stats?.existing_pv_regions ?? "—"}</dd>
          </div>
          <div>
            <dt>
              Roof area
              <Help title="Roof area">
                The size of the roof outline as seen from above, in square metres. A pitched roof is slightly larger in reality than this flat, top-down view.
              </Help>
            </dt>
            <dd>{stats ? `${stats.roof_area_m2} m²` : "—"}</dd>
          </div>
          <div>
            <dt>
              Usable area
              <Help title="Usable area">
                What is left of the roof after removing existing panels, chimneys, windows and the safety gap around every edge. Panels can only go here.
              </Help>
            </dt>
            <dd>{stats ? `${stats.usable_area_m2} m²` : "—"}</dd>
          </div>
          <div>
            <dt>
              Roof covered by new panels
              <Help title="Roof covered by new panels">
                How much of the whole roof the proposed panels physically cover. Real roofs rarely exceed about 70–80% because of edges and obstacles.
              </Help>
            </dt>
            <dd>{stats ? `${stats.roof_utilisation}%` : "—"}</dd>
          </div>
          <div>
            <dt>
              Selected orientation
              <Help title="Selected orientation">
                Whether the panels fit better standing up (portrait) or lying flat (landscape). SolarFit tries both and keeps whichever fits more.
              </Help>
            </dt>
            <dd className="capitalize">{stats?.orientation ?? "—"}</dd>
          </div>
          {stats?.annual_energy_kwh != null && (
            <div>
              <dt>
              Estimated annual energy
              <Help title="Estimated annual energy">
                A rough guess at the electricity the new panels would make in a year, in kilowatt-hours. A Swiss household uses roughly 4,500 kWh per year.
              </Help>
            </dt>
              <dd>{stats.annual_energy_kwh.toLocaleString()} kWh</dd>
            </div>
          )}
        </dl>
        <div className="confidence">
          <div>
            <span>
              Mean detection confidence
              <Help title="Detection confidence">
                How sure the AI is about what it found in the photo. Low
                confidence means you should look at the image yourself and mark
                anything it missed. It is not a judgement of whether the roof
                suits solar.
              </Help>
            </span>
            <strong>
              {result?.confidence.mean_detection != null
                ? `${Math.round(result.confidence.mean_detection * 100)}%`
                : "Not available"}
            </strong>
          </div>
          <div className="confidence-track">
            <span
              style={{
                width: `${(result?.confidence.mean_detection || 0) * 100}%`,
              }}
            />
          </div>
          <p>Detection score, not a guarantee of roof suitability.</p>
          {result && (
            <p>
              PV:{" "}
              {result.confidence.existing_pv == null
                ? "unavailable"
                : `${Math.round(result.confidence.existing_pv * 100)}%`}
              {" · "}Obstacles:{" "}
              {result.confidence.obstacles == null
                ? "unavailable"
                : `${Math.round(result.confidence.obstacles * 100)}%`}
            </p>
          )}
        </div>
        {error && (
          <div className="error" role="alert">
            <AlertCircle size={17} />
            {error}
          </div>
        )}
        <button
          className="primary analyse"
          disabled={busy || !ready}
          onClick={() => void analyse()}
        >
          {busy ? (
            <LoaderCircle className="spin" size={19} />
          ) : (
            <ScanLine size={19} />
          )}{" "}
          {busy ? "Analysing roof…" : "Analyse roof"}
          {!busy && <ArrowUpRight size={18} />}
        </button>
        <button className="export" disabled={!result} onClick={exportJson}>
          <Download size={15} />
          Export analysis JSON
        </button>
        <div className="model-status">
          <i />
          {model}
          {stats && <span> · {(stats.elapsed_ms / 1000).toFixed(2)} s</span>}
        </div>
      </div>
      {result && (
        <div className="notice-card">
          <h3>
            <AlertCircle size={17} />
            Know the limits
          </h3>
          {result.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </div>
      )}
      {Object.keys(comparisons).length > 1 && (
        <div className="comparison-card">
          <h3>Layouts explored</h3>
          {MODES.filter((m) => comparisons[m] != null).map((m) => (
            <div key={m}>
              <span className="capitalize">{m}</span>
              <b>{comparisons[m]} panels</b>
            </div>
          ))}
          <small>Counts are from the settings used for each run.</small>
        </div>
      )}
    </aside>
  );
}
