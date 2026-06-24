import type { EnumField, RangeField } from "./search/orama";
import type { BoolField } from "./search/orama";

// Shared filter labels, used by the facet panel and the active-filter pill bar.

export const ENUM_SECTIONS: { field: EnumField; label: string }[] = [
  { field: "product_types", label: "Type" },
  { field: "brand", label: "Brand" },
  { field: "frame_style", label: "Frame style" },
  { field: "drive_type", label: "Drive" },
  { field: "brake_type", label: "Brakes" },
  { field: "frame_material", label: "Frame" },
  { field: "suspension", label: "Suspension" },
];

export const RANGE_SECTIONS: { field: RangeField; label: string }[] = [
  { field: "price", label: "Price ($)" },
  { field: "battery_wh", label: "Battery (Wh)" },
  { field: "motor_w", label: "Motor (W)" },
  { field: "torque_nm", label: "Torque (Nm)" },
  { field: "range_mi", label: "Range" },
  { field: "weight_lb", label: "Weight" },
  { field: "max_load_lb", label: "Max load" },
  { field: "gears", label: "Gears" },
];

export const BOOL_LABELS: Record<BoolField, string> = {
  is_new: "New",
  on_sale: "On Sale",
  ul_listed: "UL / EN certified",
  awd: "AWD (dual motor)",
  folding: "Folding",
  kids: "Exclude Kids Ebikes",
};

// Pedal-assist sensor: a single-select dropdown (default "No Preference" = unset),
// backed by the sensor_type enum slot. "Both" maps to the "torque + cadence" value.
export const SENSOR_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "No Preference" },
  { value: "torque", label: "Torque" },
  { value: "cadence", label: "Cadence" },
  { value: "torque + cadence", label: "Both" },
];

export const sensorLabel = (v: string): string =>
  ({ torque: "Torque", cadence: "Cadence", "torque + cadence": "Both" })[v] ?? v;

// Maximum-budget presets for the price-filter dropdown. The dropdown only sets the
// MAX (the band always starts at the catalog floor); the optional minimum is set by
// dragging the slider's low handle. `max: null` = no ceiling (the full catalog).
export type PriceTier = { label: string; max: number | null };

export const PRICE_TIERS: PriceTier[] = [
  { label: "Any", max: null },
  { label: "Up to $1,200", max: 1200 },
  { label: "Up to $2,000", max: 2000 },
  { label: "Up to $3,500", max: 3500 },
  { label: "Up to $5,500", max: 5500 },
  { label: "Up to $9,000", max: 9000 },
];

/** The tier's max, resolving "no ceiling" to the catalog maximum. */
export function priceTierMax(t: PriceTier, bHi: number): number {
  return t.max ?? bHi;
}

/** The tier whose ceiling equals the current upper bound (matches on MAX only — a
 *  set minimum doesn't change which max preset is shown). */
export function matchPriceTier(hi: number, bHi: number): PriceTier | undefined {
  return PRICE_TIERS.find((t) => priceTierMax(t, bHi) === hi);
}

/** Human label for a max preset: "Any price" / "Up to $4,000". */
export function priceTierLabel(t: PriceTier): string {
  return t.max == null ? "Any price" : `Up to $${t.max.toLocaleString()}`;
}
