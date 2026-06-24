// Types for data/current/active/ebike.json (schema_version 1.0).

export interface Availability {
  status: "in_stock" | "sold_out" | "unknown";
  in_stock: boolean | null;
  /** Per-axis option values that are sold out ({ Color: ["Black"], Size: [...] }). */
  sold_out_options: Record<string, string[]>;
}

export interface Accessory {
  name: string;
  price: number | null;
  regular_price?: number | null;
  on_sale?: boolean;
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

/** A purchasable variant (size/color/battery combo) with its own price. */
export interface Configuration {
  options?: Record<string, string>;
  price: number | null;
  sku?: string;
  available?: boolean;
  color?: ColorOption | null;
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
  /** Low end of a stated range span; shown as "low/high" with range_mi when set. */
  range_min_mi?: number;
  weight_lb?: number;
  /** The bike's max payload / total-weight limit (lb). */
  max_load_lb?: number;
  /** Rear-rack max load capacity (lb). */
  rack_load_lb?: number;
  brake_type?: string;
  drivetrain_type?: string;
  gears?: number;
  suspension?: string;
  frame_material?: string;
  sensor_type?: string;
  /** All-wheel drive: two drive motors (front + rear). */
  awd?: boolean | null;
  /** Supported e-bike classes incl. convertible modes (e.g. [1, 2, 3]). */
  classes?: number[] | null;
  /** Top assisted speed: site-stated, else class-implied (C3 28, C1/2 20). */
  max_speed_mph?: number | null;
  /** True when the bike advertises a custom/user-adjustable speed mode. */
  custom_speed_mode?: boolean | null;
  display_type?: string;
  water_resistance?: string;
  ul_listed?: boolean;
  warranty_years?: number;
  connectivity?: string[];
  notable_tech?: string[];
  /** True for kids-only models. */
  kids?: boolean;
  /** Rider-height fit envelope across all frame sizes, in inches and mm; set together. */
  fit_height_min_in?: number;
  fit_height_max_in?: number;
  fit_height_min_mm?: number;
  fit_height_max_mm?: number;
  [k: string]: unknown;
}

export interface Analysis {
  specs_typed: SpecsTyped;
  /** Cohort-relative ranks (vs the bike's primary-type peers). */
  percentiles: Record<string, number>;
  /** Per-dimension 0–100, each ranked within the primary-type cohort:
   *  power, torque, range, battery, price, value, feature. No overall score. */
  scores: Record<string, number>;
  /** The bike's own features that are rarest among its same-type peers. */
  feature_notable?: string[];
  /** The most-specific product type — the cohort the scores are ranked within. */
  primary_type?: string;
  highlights: string[];
  /** What makes this bike stand out from its type peers: top-quartile magnitude specs
   *  (with the figure as `value`) + equipment uncommon in the cohort (`value` empty). */
  standouts?: { label: string; value?: string }[];
  /** Curated premium/notable equipment the bike has (security, OTA, regen, premium
   *  components, …) — shown in the "Uncommon Features" card; replaces the Feature score. */
  uncommon_features?: string[];
  /** Part-price facts joined from the component catalog — a brand/spec-aware RETAIL
   *  estimate per part (researched where looked up). A standalone value signal, never
   *  blended into an overall score. */
  component_quality?: {
    parts_identified: number;
    parts_priced: number;
    /** Parts backed by a real price lookup (vs a brand/spec heuristic estimate). */
    parts_researched?: number;
    /** Parts contributing to the complete component base (researched or heuristic). */
    parts_costed: number;
    /** Sum of the identified parts' retail value (aftermarket street/replacement). */
    component_retail_value_usd: number | null;
    /** Complete est. component retail cost (incl. core systems costed from typed specs). */
    component_base_value_usd: number | null;
    /** price ÷ component_base_value_usd — lower = more parts per dollar. */
    value_ratio: number | null;
    /** component_base_value_usd ÷ price — parts cost as a fraction of retail price. */
    bom_pct?: number | null;
    /** Every line summing to component_base_value_usd (parsed parts + spec estimates). */
    base_breakdown?: {
      kind: string;
      label: string;
      cost: number;
      /** researched = real lookup; estimate = catalog heuristic; spec_estimate = from typed specs. */
      method: "researched" | "estimate" | "spec_estimate";
    }[];
  };
}

/** A published frame size and the rider range it fits (strings, as scraped). */
export interface FrameSize {
  size?: string;
  height_min?: string;
  height_max?: string;
  inseam_min?: string;
  inseam_max?: string;
}

export interface Model {
  id: string;
  brand: string;
  model: string;
  /** Spec/build tier label when this entry is one price tier of a family. */
  tier?: string | null;
  /** Shared id linking sibling tier entries of the same bike family. */
  family_id?: string | null;
  url: string;
  /** Primary use category (first of product_types). */
  product_type?: string;
  /** Every matching use category, primary first ("Cargo", "Folding", ...). */
  product_types?: string[];
  /** "Step-Thru" | "Step-Over (Mid-Step)" when the frame style is known. */
  frame_style?: string | null;
  /** Whether the bike folds — a feature, not a product type. */
  folding?: boolean;
  /** True only when the brand's site explicitly tags it a new arrival. */
  is_new?: boolean;
  /** Published frame sizes and the count, when the brand offers more than one. */
  frame_sizes?: FrameSize[];
  frame_size_count?: number;
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
  configurations?: Configuration[];
  /** Stock summary from per-configuration availability flags. */
  availability?: Availability;
  /** The $0 items bundled with the bike (lights, fenders, racks, ...). */
  included_accessories?: { name: string; price: number }[];
  analysis: Analysis;
  /** TEMP data-triage: expected typed fields missing on this model (from audit.py). */
  data_audit?: { missing: string[] };
  /** What changed vs the previous daily build (from diff_changes.py). */
  changed_today?: {
    types: string[];
    detail?: {
      price?: { from: number; to: number; delta: number; pct: number | null; direction: "drop" | "rise" };
      sale?: { event: "started" | "ended" | "deepened" | "reduced"; from_pct?: number; to_pct?: number; discount_pct?: number | null };
      stock?: { event: "back_in_stock" | "sold_out" };
      free_feature?: { added: string[]; removed: string[] };
    };
  };
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
  analysis_stats_by_type?: Record<string, AnalysisStats>;
  analysis_disclaimer: string;
  /** Shared table of unique parsed components, keyed by `category|manufacturer|model`
   *  (with a `#N` suffix on content collisions). Each model.specs[group][field] that is
   *  a component holds its key here; DataProvider rehydrates them (sharing one object per
   *  unique component) before use. Entries carry `catalog_key` + `retail_usd`. */
  components?: Record<string, SpecValue>;
}
