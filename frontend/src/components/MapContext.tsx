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
  const windows = capture.objects.filter((o) => o.source === "image");
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
        {!!(measured.length || windows.length) && (
          <span>
            {measured.length} raised · {windows.length} windows
            <Help title="What was found on your roof">
              <b>Raised structures</b> — chimneys, dormers and vents — come from
              swisstopo's height model, which measures the roof surface every
              50 cm. Anything standing more than 28 cm proud of its own roof
              face is kept clear.
              <br />
              <br />
              <b>Roof windows</b> lie flush in the pitch, so no height model can
              see them. These are found in the photo instead: glass reflects the
              sky, so a window reads blue against a red or brown roof.
              <br />
              <br />
              That last one is a colour rule, not a trained model. It can miss a
              window in deep shadow and can be fooled by a blue-grey roof, so
              compare the overlay with the image and mark anything missed.
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
