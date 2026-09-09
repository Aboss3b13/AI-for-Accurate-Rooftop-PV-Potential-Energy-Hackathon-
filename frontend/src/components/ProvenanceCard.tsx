import { useState } from "react";
import { ChevronDown } from "lucide-react";
import Help from "./Help";
import type { Analysis } from "../types";

const KIND_LABEL: Record<string, string> = {
  measured: "Measured",
  calculated: "Calculated",
  inferred: "Inferred from the photo",
  supplied: "You marked it",
};

/** Where every number came from, and how strongly it is known. */
export default function ProvenanceCard({ result }: { result: Analysis }) {
  const [open, setOpen] = useState(false);
  const rows = result.data_provenance;
  if (!rows?.length) return null;
  const counts = rows.reduce<Record<string, number>>((acc, r) => {
    acc[r.kind] = (acc[r.kind] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <section className="provenance-card">
      <button
        className="provenance-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="eyebrow">WHERE THESE NUMBERS COME FROM</span>
        <span className="provenance-tally">
          {counts.measured ?? 0} measured · {counts.calculated ?? 0} calculated ·{" "}
          {counts.inferred ?? 0} inferred
        </span>
        <ChevronDown size={15} className={open ? "flip" : ""} />
      </button>
      {!open && (
        <p className="provenance-lead">
          Most of this roof is not predicted. It is read from Swiss federal
          records and worked out geometrically.
          <Help title="Why that matters">
            Roof shape, orientation and annual irradiation are published
            measurements. Sun position and shading are geometry. Only two things
            nobody records — <b>where</b> an existing array sits, and where a
            flush roof window is — are inferred from the aerial photo, because
            they cannot be observed any other way.
          </Help>
        </p>
      )}
      {open && (
        <ul className="provenance-list">
          {rows.map((row) => (
            <li key={row.fact} className={`kind-${row.kind}`}>
              <div>
                <strong>{row.fact}</strong>
                <em>{KIND_LABEL[row.kind] ?? row.kind}</em>
              </div>
              <span>{row.source}</span>
              {row.detail && <small>{row.detail}</small>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
