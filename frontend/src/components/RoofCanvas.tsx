import { useState } from "react";
import type { Analysis, Geometry, MarkedObject, Point } from "../types";

export type Tool =
  | "view"
  | "roof"
  | "existing_pv"
  | "chimney"
  | "skylight"
  | "rwa"
  | "other_obstacle"
  | "scale";
export const layerNames = {
  roof: "Roof boundary",
  existing: "Existing PV",
  obstacles: "Obstacles",
  safety: "Safety exclusions",
  usable: "Usable area",
  panels: "Proposed panels",
  shade: "Seasonal shade risk",
};
export type Layers = Record<keyof typeof layerNames, boolean>;
const points = (p: Point[]) => p.map((x) => x.join(",")).join(" ");
function path(g: Geometry): string {
  if (g.type === "GeometryCollection")
    return (g.geometries || []).map(path).join(" ");
  if (g.type === "Polygon")
    return g.coordinates
      .map((r: Point[]) => "M" + r.map((p) => p.join(",")).join("L") + "Z")
      .join(" ");
  if (g.type === "MultiPolygon")
    return g.coordinates
      .map((c: any) => path({ type: "Polygon", coordinates: c }))
      .join(" ");
  return "";
}
export default function RoofCanvas({
  url,
  size,
  roof,
  objects,
  draft,
  setDraft,
  tool,
  result,
  layers,
  original,
  onFinish,
  onRoofChange,
  measurement,
  shadowPreview,
}: {
  url: string;
  size: [number, number];
  roof: Point[];
  objects: MarkedObject[];
  draft: Point[];
  setDraft: (p: Point[]) => void;
  tool: Tool;
  result: Analysis | null;
  layers: Layers;
  original: boolean;
  onFinish: (p: Point[]) => void;
  onRoofChange: (p: Point[]) => void;
  measurement: Point[];
  shadowPreview?: { shade: Geometry; unknown: Geometry } | null;
}) {
  const [drag, setDrag] = useState<number | null>(null);
  function location(e: React.PointerEvent<SVGSVGElement>): Point {
    const svg = e.currentTarget;
    const p = svg.createSVGPoint();
    p.x = e.clientX;
    p.y = e.clientY;
    const q = p.matrixTransform(svg.getScreenCTM()!.inverse());
    return [
      Math.max(0, Math.min(size[0], q.x)),
      Math.max(0, Math.min(size[1], q.y)),
    ];
  }
  const radius = Math.max(size[0], size[1]) / 130;
  return (
    <svg
      className={"roof-canvas " + (tool === "view" ? "" : "drawing")}
      viewBox={`0 0 ${size[0]} ${size[1]}`}
      aria-label="Roof image. Choose a drawing tool and click to add vertices."
      onPointerDown={(e) => {
        if (drag !== null || tool === "view") return;
        const p = location(e);
        if (tool === "scale" && draft.length === 1) {
          onFinish([...draft, p]);
          return;
        }
        if (
          tool !== "scale" &&
          draft.length >= 3 &&
          Math.hypot(p[0] - draft[0][0], p[1] - draft[0][1]) < radius * 2
        ) {
          onFinish(draft);
          return;
        }
        setDraft([...draft, p]);
      }}
      onPointerMove={(e) => {
        if (drag !== null) {
          const p = [...roof];
          p[drag] = location(e);
          onRoofChange(p);
        }
      }}
      onPointerUp={() => setDrag(null)}
      onPointerCancel={() => setDrag(null)}
    >
      <image href={url} width={size[0]} height={size[1]} />
      {!original && (
        <>
          {result && layers.safety && (
            <path
              d={path(result.excluded_area)}
              className="safety"
              fillRule="evenodd"
            />
          )}
          {result && layers.usable && (
            <path
              d={path(result.usable_area)}
              className="usable"
              fillRule="evenodd"
            />
          )}
          {!shadowPreview && result?.shaded_area && layers.shade && <path d={path(result.shaded_area)} fill="#8061b8" fillOpacity={0.38} stroke="#644592" strokeWidth={1} fillRule="evenodd" />}
          {shadowPreview && <>
            <path d={path(shadowPreview.shade)} fill="#64309c" fillOpacity={0.55} fillRule="evenodd" />
            <path d={path(shadowPreview.unknown)} fill="#777" fillOpacity={0.45} fillRule="evenodd" />
          </>}
          {layers.existing &&
            (
              result?.existing_pv ||
              objects.filter((o) => o.kind === "existing_pv")
            ).map((o, i) => (
              <polygon
                key={"e" + i}
                points={points(o.polygon)}
                className="existing"
              />
            ))}
          {layers.obstacles &&
            (
              result?.obstacles ||
              objects.filter((o) => o.kind !== "existing_pv")
            ).map((o, i) => (
              <polygon
                key={"o" + i}
                points={points(o.polygon)}
                className="obstacle"
              />
            ))}
          {result &&
            layers.panels &&
            result.proposed_panels.map((p, i) => (
              <polygon key={i} points={points(p)} className="panel" />
            ))}
          {layers.roof && roof.length > 2 && (
            <polygon points={points(roof)} className="roof-line" />
          )}
          {tool === "view" &&
            layers.roof &&
            roof.map((p, i) => (
              <circle
                key={i}
                cx={p[0]}
                cy={p[1]}
                r={radius * 0.65}
                className="vertex"
                onPointerDown={(e) => {
                  e.stopPropagation();
                  e.currentTarget.setPointerCapture(e.pointerId);
                  setDrag(i);
                }}
              />
            ))}
        </>
      )}
      {measurement.length === 2 && (
        <>
          <polyline points={points(measurement)} className="measure-line" />
          {measurement.map((p, i) => (
            <circle key={i} cx={p[0]} cy={p[1]} r={radius * 0.6} fill="#fff" />
          ))}
        </>
      )}
      {draft.length > 0 && (
        <>
          <polyline points={points(draft)} className="draft" />
          {draft.map((p, i) => (
            <circle
              key={i}
              cx={p[0]}
              cy={p[1]}
              r={radius}
              fill={i === 0 ? "#b9ef62" : "white"}
            />
          ))}
        </>
      )}
    </svg>
  );
}
