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
  on_sale: "On sale",
  ul_listed: "UL / EN certified",
  awd: "AWD (dual motor)",
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

// Named price presets for the price-filter dropdown. `lo: null` means "down to the
// catalog minimum", `hi: null` means "up to the catalog maximum" (so the top tier
// always covers new, more-expensive bikes). Ranges intentionally overlap.
export type PriceTier = { label: string; lo: number | null; hi: number | null };

export const PRICE_TIERS: PriceTier[] = [
  { label: "All", lo: null, hi: null },
  { label: "Budget", lo: null, hi: 1200 },
  { label: "Value", lo: 1000, hi: 2000 },
  { label: "Mid-range", lo: 2000, hi: 3500 },
  { label: "Premium", lo: 3500, hi: 5500 },
  { label: "High-end", lo: 5500, hi: 9000 },
  { label: "Flagship", lo: 9000, hi: null },
];

/** Concrete [lo, hi] for a tier, resolving the open ends to the catalog bounds. */
export function priceTierRange(t: PriceTier, bLo: number, bHi: number): [number, number] {
  return [t.lo ?? bLo, t.hi ?? bHi];
}

/** The tier whose resolved range equals [lo, hi], if any (else a custom range). */
export function matchPriceTier(lo: number, hi: number, bLo: number, bHi: number): PriceTier | undefined {
  return PRICE_TIERS.find((t) => {
    const [tlo, thi] = priceTierRange(t, bLo, bHi);
    return tlo === lo && thi === hi;
  });
}

/** Human dollar range for a tier: "≤ $1,200", "$1,000–$2,000", "$9,000+". */
export function priceTierRangeText(t: PriceTier, bLo: number, bHi: number): string {
  const fmt = (n: number) => `$${n.toLocaleString()}`;
  const [lo, hi] = priceTierRange(t, bLo, bHi);
  if (t.label === "All") return "All prices";
  if (t.lo == null) return `≤ ${fmt(hi)}`;
  if (t.hi == null) return `${fmt(lo)}+`;
  return `${fmt(lo)}–${fmt(hi)}`;
}
