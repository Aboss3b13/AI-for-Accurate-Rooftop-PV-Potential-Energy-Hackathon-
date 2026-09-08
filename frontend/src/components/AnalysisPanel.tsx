import {
  Sun,
  Zap,
  ScanLine,
  AlertCircle,
  LoaderCircle,
  ArrowUpRight,
  Download,
} from "lucide-react";
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
            <dt>Existing PV regions</dt>
            <dd>{stats?.existing_pv_regions ?? "—"}</dd>
          </div>
          <div>
            <dt>Roof area</dt>
            <dd>{stats ? `${stats.roof_area_m2} m²` : "—"}</dd>
          </div>
          <div>
            <dt>Usable area</dt>
            <dd>{stats ? `${stats.usable_area_m2} m²` : "—"}</dd>
          </div>
          <div>
            <dt>Roof covered by new panels</dt>
            <dd>{stats ? `${stats.roof_utilisation}%` : "—"}</dd>
          </div>
          <div>
            <dt>Selected orientation</dt>
            <dd className="capitalize">{stats?.orientation ?? "—"}</dd>
          </div>
          {stats?.annual_energy_kwh != null && (
            <div>
              <dt>Estimated annual energy</dt>
              <dd>{stats.annual_energy_kwh.toLocaleString()} kWh</dd>
            </div>
          )}
        </dl>
        <div className="confidence">
          <div>
            <span>Mean detection confidence</span>
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
      {!result && (
        <div className="workflow-card">
          <span className="eyebrow">A BETTER ESTIMATE IN THREE STEPS</span>
          <div>
            <b>1</b>
            <p>
              Upload an aerial image
              <span>Use a clear, top-down view of one roof.</span>
            </p>
          </div>
          <div>
            <b>2</b>
            <p>
              Trace & calibrate
              <span>Mark the roof and one known distance.</span>
            </p>
          </div>
          <div>
            <b>3</b>
            <p>
              Find your fit
              <span>Review obstacles and compare layouts.</span>
            </p>
          </div>
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
