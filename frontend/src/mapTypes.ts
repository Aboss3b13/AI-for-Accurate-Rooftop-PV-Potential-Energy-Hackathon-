import { api } from "./http";
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
  address?: { label: string; egid: string | number | null; source: string } | null;
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
export type RoofSelection = {
  candidates: { id: string; accepted: boolean; reason: string;
                building_id: number | null; egid: string | null;
                contains_click: boolean }[];
  accepted?: number;
  rejected?: number;
  rejected_sharing_building_id?: number;
  tolerance_m: number;
  physical_check: string;
};
export type MapCapture = {
  capture_id: string;
  roof_faces: (MapPlane & { roof: Point[]; plane: Record<string, unknown> })[];
  image_base64: string;
  mime_type: string;
  roof: Point[];
  objects: MarkedObject[];
  pixels_per_metre: number;
  angle: number;
  candidates: MapPlane[];
  roof_selection?: RoofSelection;
  building_outline: MapPlane | null;
  selected_roof_id: string | null;
  warnings: string[];
  provenance: MapProvenance;
};
export type MapPick = {
  latitude: number;
  longitude: number;
  roof_id?: string;
  span_m?: number;
  polygon?: { latitude: number; longitude: number }[];
};

export async function prepareMapCapture(
  pick: MapPick,
  signal?: AbortSignal,
): Promise<MapCapture> {
  const response = await api("/api/map/prepare", {
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
