export type Point = [number, number];
export type Mode = "conservative" | "recommended" | "maximum";
export type Kind = "existing_pv" | "chimney" | "skylight" | "other_obstacle";
export type MarkedObject = {
  polygon: Point[];
  kind: Kind;
  source?: "manual" | "map" | "elevation" | "image";
  /** Metres this superstructure rises above its roof face, when measured. */
  height_m?: number | null;
};
export type Detection = MarkedObject & {
  confidence: number | null;
  source: string;
};
export type Geometry = {
  type: string;
  coordinates: any;
  geometries?: Geometry[];
};
export type Panel = {
  width: number;
  height: number;
  power: number;
  gap: number;
};
export type Analysis = {
  roof: Geometry;
  existing_pv: Detection[];
  obstacles: Detection[];
  usable_area: Geometry;
  excluded_area: Geometry;
  proposed_panels: Point[][];
  warnings: string[];
  mode: Mode;
  model: {
    available: boolean;
    model: string;
    device: string;
    classes: string[];
  };
  confidence: {
    existing_pv: number | null;
    obstacles: number | null;
    mean_detection: number | null;
    uncertain_objects: number;
    note: string;
  };
  statistics: {
    existing_pv_regions: number;
    additional_panel_count: number;
    additional_kwp: number;
    annual_energy_kwh: number | null;
    roof_area_m2: number;
    usable_area_m2: number;
    roof_utilisation: number;
    pixels_per_metre: number;
    approximate: boolean;
    orientation: string;
    elapsed_ms: number;
  };
};
