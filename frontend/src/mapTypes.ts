import type { Geometry, MarkedObject, Point } from "./types";

export type MapPlane = {
  id: string;
  geometry: Geometry;
  projected_area_m2: number;
  pitch_deg: number | null;
  azimuth_deg: number | null;
  plane_number: number | null;
  building_id: number | null;
  contains_click: boolean;
};
export type MapProvenance = {
  imagery: string;
  roof_source: string | null;
  crs: string;
  bbox: number[];
  image_width: number;
  image_height: number;
  pixels_per_metre: number;
  latitude: number;
  longitude: number;
  feature_id: string | null;
  building_id: number | null;
  pitch_deg: number | null;
  azimuth_deg: number | null;
  roof_data_updated: string | null;
  merged_planes: number;
  roof_area_m2: number | null;
  retrieved_at: string;
  scale_basis: string;
  source_url: string;
};
export type MapCapture = {
  image_base64: string;
  mime_type: string;
  roof: Point[];
  objects: MarkedObject[];
  pixels_per_metre: number;
  angle: number;
  candidates: MapPlane[];
  building_outline: MapPlane | null;
  selected_roof_id: string | null;
  warnings: string[];
  provenance: MapProvenance;
};
export type MapPick = {
  latitude: number;
  longitude: number;
  roof_id?: string;
  capture_only?: boolean;
  span_m?: number;
  polygon?: { latitude: number; longitude: number }[];
};

export async function prepareMapCapture(
  pick: MapPick,
  signal?: AbortSignal,
): Promise<MapCapture> {
  const response = await fetch("/api/map/prepare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pick),
    signal,
  });
  const data = await response.json();
  if (!response.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Choose a location in Switzerland.",
    );
  return data;
}
