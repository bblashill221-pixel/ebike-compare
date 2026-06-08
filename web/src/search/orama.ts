// Client-side search/filter index over the e-bike models, backed by Orama.
import { create, insertMultiple, search, type AnyOrama } from "@orama/orama";
import type { Model } from "../types";
import { lowestPrice } from "../pricing";
import { isAvailable } from "../soldOut";

// Canonical product-type order, mirroring PRODUCT_TYPES in bike_taxonomy.py.
export const PRODUCT_TYPE_ORDER = [
  "Commuter / Urban",
  "Mountain (eMTB)",
  "Road / Gravel",
  "Cargo",
  "Folding",
  "Cruiser",
  "eMoto",
  "Fat tire",
  "Hybrid / Fitness",
] as const;

export const ENUM_FIELDS = [
  "brand",
  "product_types",
  "frame_style",
  "drive_type",
  "brake_type",
  "frame_material",
  "suspension",
  "sensor_type",
] as const;

export const BOOL_FIELDS = ["on_sale", "ul_listed"] as const;

export const RANGE_FIELDS = [
  "price",
  "battery_wh",
  "motor_w",
  "motor_peak_w",
  "torque_nm",
  "range_mi",
  "weight_lb",
  "gears",
] as const;

export type EnumField = (typeof ENUM_FIELDS)[number];
export type BoolField = (typeof BOOL_FIELDS)[number];
export type RangeField = (typeof RANGE_FIELDS)[number];

const schema = {
  id: "string",
  text: "string",
  brand: "enum",
  product_types: "enum[]",
  frame_style: "enum",
  drive_type: "enum",
  brake_type: "enum",
  frame_material: "enum",
  suspension: "enum",
  sensor_type: "enum",
  on_sale: "boolean",
  ul_listed: "boolean",
  available: "boolean",
  price: "number",
  battery_wh: "number",
  motor_w: "number",
  motor_peak_w: "number",
  torque_nm: "number",
  range_mi: "number",
  weight_lb: "number",
  gears: "number",
  // rider-height fit envelope (inches); see the riderHeightIn filter below
  fit_height_min_in: "number",
  fit_height_max_in: "number",
} as const;

function toDoc(m: Model): Record<string, unknown> {
  const t = m.analysis?.specs_typed ?? {};
  const productTypes = m.product_types?.length
    ? m.product_types
    : m.product_type
      ? [m.product_type]
      : [];
  const text = [
    m.model,
    m.tier ?? "",
    m.brand,
    ...productTypes,
    ...(t.notable_tech ?? []),
    ...(m.analysis?.highlights ?? []),
  ]
    .filter(Boolean)
    .join(" ");
  return {
    id: m.id,
    text,
    brand: m.brand || "unknown",
    product_types: productTypes,
    frame_style: m.frame_style || "unknown",
    drive_type: t.drive_type || "unknown",
    brake_type: t.brake_type || "unknown",
    frame_material: t.frame_material || "unknown",
    suspension: t.suspension || "unknown",
    sensor_type: t.sensor_type || "unknown",
    on_sale: !!m.pricing?.on_sale,
    ul_listed: !!t.ul_listed,
    available: isAvailable(m),
    // lowest purchasable price across colors/configurations
    price: lowestPrice(m) ?? 0,
    battery_wh: t.battery_wh ?? 0,
    motor_w: t.motor_w ?? 0,
    motor_peak_w: t.motor_peak_w ?? 0,
    torque_nm: t.torque_nm ?? 0,
    range_mi: t.range_mi ?? 0,
    weight_lb: t.weight_lb ?? 0,
    gears: t.gears ?? 0,
    // Lenient sentinels: a bike with no published height range gets [0, 9999] so
    // it always satisfies the "fits my height" filter (we never hide a bike just
    // for lacking the data); see runSearch.
    fit_height_min_in: t.fit_height_min_in ?? 0,
    fit_height_max_in: t.fit_height_max_in ?? 9999,
  };
}

export async function buildIndex(models: Model[]): Promise<AnyOrama> {
  const db = create({ schema });
  await insertMultiple(db, models.map(toDoc));
  return db;
}

export interface Filters {
  enums: Partial<Record<EnumField, string[]>>;
  bools: Partial<Record<BoolField, boolean>>;
  ranges: Partial<Record<RangeField, [number, number]>>;
  /** Rider height in inches; keep models whose fit envelope contains it. null = off. */
  riderHeightIn?: number | null;
}

export interface SearchResult {
  ids: string[];
  facets: Record<string, Record<string, number>>;
  count: number;
}

export async function runSearch(
  db: AnyOrama,
  term: string,
  filters: Filters,
  total: number,
  includeSoldOut = true,
): Promise<SearchResult> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const where: Record<string, any> = {};
  for (const f of ENUM_FIELDS) {
    const vals = filters.enums[f];
    // enum[] fields (product_types) take containsAny; plain enums take in
    if (vals && vals.length) where[f] = f === "product_types" ? { containsAny: vals } : { in: vals };
  }
  for (const f of BOOL_FIELDS) {
    if (filters.bools[f]) where[f] = { eq: true };
  }
  // "Sold out" toggle off -> only in-stock models
  if (!includeSoldOut) where.available = { eq: true };
  for (const f of RANGE_FIELDS) {
    const r = filters.ranges[f];
    if (r) where[f] = { between: r };
  }
  // "Fits my height": keep models whose envelope contains H, i.e. min <= H <= max.
  // Expressed with `between` (the operator already used above): min in [0, H] and
  // max in [H, 9999]. Data-less bikes index as [0, 9999] so they always pass.
  if (filters.riderHeightIn != null) {
    const h = filters.riderHeightIn;
    where.fit_height_min_in = { between: [0, h] };
    where.fit_height_max_in = { between: [h, 9999] };
  }

  const res = await search(db, {
    term: term.trim(),
    where,
    limit: Math.max(total, 1),
    facets: Object.fromEntries(
      [...ENUM_FIELDS, ...BOOL_FIELDS].map((f) => [f, {}]),
    ),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);

  const facets: Record<string, Record<string, number>> = {};
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rawFacets = (res as any).facets ?? {};
  for (const [k, v] of Object.entries(rawFacets)) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    facets[k] = (v as any).values ?? {};
  }

  return {
    ids: res.hits.map((h) => String((h.document as { id: string }).id)),
    facets,
    count: res.count,
  };
}
