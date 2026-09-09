import { useState } from "react";
import { ChevronDown } from "lucide-react";
import Help from "./Help";
import type { MapCapture } from "../mapTypes";

/** Why each candidate roof face was kept or dropped. */
export default function RoofSelectionCard({ capture }: { capture: MapCapture }) {
  const [open, setOpen] = useState(false);
  const selection = capture.roof_selection;
  if (!selection?.candidates?.length) return null;
  const dropped = selection.rejected_sharing_building_id ?? 0;
  return (
    <section className="selection-card">
      <button
        className="provenance-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="eyebrow">WHICH ROOF WAS SELECTED</span>
        <span className="provenance-tally">
          {selection.accepted ?? 0} kept · {selection.rejected ?? 0} dropped
        </span>
        <ChevronDown size={15} className={open ? "flip" : ""} />
      </button>
      {!open && dropped > 0 && (
        <p className="provenance-lead">
          {dropped} polygon{dropped === 1 ? "" : "s"} carry this building&rsquo;s
          official identifier but are not attached to the roof you clicked.
          <Help title="Why that matters">
            Sonnendach&rsquo;s <b>building_id</b> groups records, not structures.
            Two roofs either side of a courtyard can share one. SolarFit starts
            at the face under your click and keeps only faces joined to it by a
            real shared edge — checked against measured surface height where
            that is available.
          </Help>
        </p>
      )}
      {open && (
        <>
          <div className="vintage-row">
            <span>
              Join tolerance <b>{selection.tolerance_m} m</b>
            </span>
            <span>
              Checked against <b>{selection.physical_check}</b>
            </span>
          </div>
          <ul className="selection-list">
            {selection.candidates.map((face) => (
              <li key={face.id} className={face.accepted ? "kept" : "dropped"}>
                <div>
                  <strong>{face.id}</strong>
                  <em>{face.accepted ? "kept" : "dropped"}</em>
                  {face.contains_click && <em className="clicked">clicked</em>}
                </div>
                <span>{face.reason}</span>
                <small>
                  building_id {face.building_id ?? "—"}
                  {face.egid ? ` · EGID ${face.egid}` : ""}
                </small>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
