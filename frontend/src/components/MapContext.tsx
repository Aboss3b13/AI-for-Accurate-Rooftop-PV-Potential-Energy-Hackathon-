import { MapPin, Check, RotateCcw } from "lucide-react";
import Help from "./Help";
import type { MapCapture, MapPick } from "../mapTypes";

export default function MapContext({
  capture,
  onPick,
  busy,
  edited,
  onReset,
}: {
  capture: MapCapture;
  onPick: (pick: MapPick) => Promise<void>;
  busy: boolean;
  edited: boolean;
  onReset: () => void;
}) {
  const p = capture.provenance;
  const measured = capture.objects.filter((o) => o.source === "elevation");
  return (
    <section className="map-context">
      <div className="map-context-title">
        <span>
          <MapPin size={16} />
          Roof from the map
        </span>
        <strong>
          <Check size={13} />
          Scale calibrated
        </strong>
      </div>
      <div className="map-facts">
        <span>
          {(100 / capture.pixels_per_metre).toFixed(1)} cm / image pixel
        </span>
        <span>{p.crs} · metric capture</span>
        {p.pitch_deg != null && <span>Source roof pitch: {p.pitch_deg}°</span>}
        {!!measured.length && (
          <span>
            {measured.length} roof structures measured
            <Help title="Measured roof structures">
              Chimneys, dormers and vents found in swisstopo's national height
              model, which measures the roof surface every 50 cm. Anything
              standing more than 45 cm proud of a roof face is treated as an
              obstacle and kept clear.
              <br />
              <br />
              It cannot see flush features — a roof window set into the pitch
              is level with it — so mark those yourself. Trees hanging over the
              roof are in the height model too, and will be excluded like any
              other obstruction.
            </Help>
          </span>
        )}
      </div>
      {capture.candidates.length > 1 && (
        <label className="roof-plane-select">
          Roof plane
          <select
            aria-label="Roof plane"
            value={capture.selected_roof_id || ""}
            disabled={busy}
            onChange={(e) =>
              void onPick({
                latitude: p.latitude,
                longitude: p.longitude,
                roof_id: e.target.value,
              })
            }
          >
            {capture.candidates.map((plane, i) => (
              <option key={plane.id} value={plane.id}>
                Plane {plane.plane_number ?? i + 1} ·{" "}
                {plane.projected_area_m2.toFixed(1)} m² ·{" "}
                {plane.pitch_deg ?? "?"}° pitch
              </option>
            ))}
          </select>
        </label>
      )}
      <p>
        {edited
          ? "Boundary adjusted by you."
          : "Official outline imported automatically."}{" "}
        Drag vertices or redraw the roof; mark any missed PV or obstacles, then
        analyse again.
      </p>
      <p>
        Scale is known in the map’s plan view. Roof pitch is source information;
        the current packing calculation remains 2D. Roof records and aerial
        imagery may differ in age.
      </p>
      {capture.warnings.map((w) => (
        <p key={w}>{w}</p>
      ))}
      {edited && capture.roof.length > 2 && (
        <button className="text-button" disabled={busy} onClick={onReset}>
          <RotateCcw size={13} />
          Restore official outline & alignment
        </button>
      )}
    </section>
  );
}
