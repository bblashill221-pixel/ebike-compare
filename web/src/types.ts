// Types for data/current/active/ebikes_normalized.json (schema_version 1.0).

export interface Accessory {
  name: string;
  price: number | null;
  free: boolean;
  url: string;
}

export interface Brand {
  brand: string;
  source: string;
  logo: string | null;
  model_count: number;
  available_accessories: Accessory[];
}

export type SpecValue =
  | string
  | number
  | boolean
  | null
  | SpecValue[]
  | { [k: string]: SpecValue };

export type SpecGroup = Record<string, SpecValue>;
export type SpecGroups = Record<string, SpecGroup>;

export interface Pricing {
  price: number | null;
  regular_price: number | null;
  on_sale: boolean;
  discount_amount: number | null;
  discount_pct: number | null;
}

export interface ColorOption {
  name: string;
  hex: string | null;
  swatch_image: string | null;
  image: string | null;
}

export interface SpecsTyped {
  battery_wh?: number;
  cell_brand?: string;
  removable_battery?: boolean;
  motor_w?: number;
  motor_peak_w?: number;
  torque_nm?: number;
  drive_type?: string;
  range_mi?: number;
  weight_lb?: number;
  brake_type?: string;
  drivetrain_type?: string;
  gears?: number;
  suspension?: string;
  frame_material?: string;
  sensor_type?: string;
  display_type?: string;
  water_resistance?: string;
  ul_listed?: boolean;
  warranty_years?: number;
  connectivity?: string[];
  notable_tech?: string[];
  [k: string]: unknown;
}

export interface Analysis {
  specs_typed: SpecsTyped;
  percentiles: Record<string, number>;
  scores: Record<string, number>;
  highlights: string[];
}

export interface Model {
  id: string;
  brand: string;
  model: string;
  url: string;
  product_type?: string;
  price: number | null;
  price_min: number | null;
  price_max: number | null;
  currency?: string;
  pricing?: Pricing;
  warranty?: string | null;
  shipping_free?: boolean | null;
  shipping_cost?: number | null;
  spec_count?: number;
  specs: SpecGroups;
  colors?: ColorOption[];
  color_names?: string[];
  configurations?: unknown[];
  analysis: Analysis;
}

export interface StatDist {
  min: number;
  p10: number;
  p50: number;
  p90: number;
  max: number;
  count: number;
}

export type AnalysisStats = Record<string, StatDist>;

export interface RawData {
  schema_version: string;
  generated_at: string;
  brand_count: number;
  model_count: number;
  brands: Brand[];
  models: Model[];
  analysis_stats: AnalysisStats;
  analysis_disclaimer: string;
}
