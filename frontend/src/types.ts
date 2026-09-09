export type Point = [number, number];
export type Mode = "conservative" | "recommended" | "maximum";
export type Kind = "existing_pv" | "chimney" | "skylight" | "rwa" | "other_obstacle";
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
  planning_constraints?: {
    status: string;
    installer_assumptions_m: Record<string, number>;
    rules: {type: string; distance_m: number; source: string; condition: string; note: string}[];
    not_automatically_verified: string[];
  };
  shaded_area?: Geometry;
  assessment?: {
    status: string; title: string; layout_policy: string;
    physical_panel_capacity: number; proposed_panel_count: number;
    remaining_annual_target_kwh: number | null; annual_target_coverage_percent: number | null;
    demand_note: string; factors: { factor: string; basis: string }[];
  };
  faces?: RoofFace[];
  map_overlay?: { type: "FeatureCollection"; features: { type: "Feature"; geometry: Geometry; properties: { layer: string; face_id: string; irradiation_kwh_m2_year?: number | null } }[] };
  energy_available?: boolean;
  pv_register?: {
    known: boolean;
    plant_count: number;
    total_power_kw: number | null;
    plants: { power_kw: number | null; commissioned: string | null;
              mounting: string | null; address: string | null }[];
    basis: string;
    coverage_note: string;
  };
  vintage?: {
    imagery_year: number | null;
    surface_year: number | null;
    roof_data_updated: string | null;
    register_updated: string | null;
  };
  input_confidence?: { input: string; level: string; note: string }[];
  data_provenance?: {
    fact: string;
    kind: "measured" | "calculated" | "inferred" | "supplied";
    source: string;
    detail: string;
  }[];
  sonnendach?: {
    official_area_m2: number;
    official_annual_energy_kwh: number | null;
    measured_surface_m2: number;
    definition_difference_m2: number | null;
    fitted_module_area_m2: number;
    fitted_annual_energy_kwh: number | null;
    area_shortfall_m2: number | null;
    area_shortfall_percent: number | null;
    energy_shortfall_percent: number | null;
    breakdown_m2: {
      faces_screened_out: number;
      existing_pv: number;
      roof_obstacles: number;
      shaded: number;
      margins_and_module_fit: number;
    };
    basis: string;
  };
  objective_note?: string;
  objective_comparison?: Record<string, { panel_count: number; additional_kwp: number; annual_energy_kwh: number | null }>;
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
    surface_area_m2?: number;
    projected_area_m2?: number;
    fallback_faces?: number;
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

export type RoofFace = {
  dimensions: { length_m: number; width_m: number };
  sunlight: { available: boolean; reason?: string; radius_m?: number;
    coverage_fraction?: number; mean_direct_sun_access?: number | null; winter_direct_sun_access?: number | null };
  assessment: { status: string; reasons: string[]; cautions: string[] };
  physical_panel_count: number;
  id: string;
  geometry_source: string;
  surface_area_m2: number;
  projected_area_m2: number;
  usable_area_m2: number;
  pitch_deg: number | null;
  azimuth_deg: number | null;
  official_pitch_deg: number | null;
  official_azimuth_deg: number | null;
  additional_panel_count: number;
  additional_kwp: number;
  annual_energy_kwh: number | null;
  existing_pv_regions: number;
  obstacle_count: number;
  solar: { irradiation_kwh_m2_year: number | null; suitability_class: number | null; specific_yield_kwh_kwp: number | null; yield_source: string | null };
  diagnostics: Record<string, unknown>;
};
