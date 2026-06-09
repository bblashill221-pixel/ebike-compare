// Per-variant pricing derived from purchase configurations. Some bikes charge
// more for certain colorways or option choices (e.g. Prodigy V2 step-over vs
// step-through frames); search/sort always uses the lowest price.
import type { Model, Configuration } from "./types";

const COLOR_KEYS = new Set(["color", "colour"]);

function cfgColor(c: Configuration): string | undefined {
  if (c.color?.name) return c.color.name;
  for (const [k, v] of Object.entries(c.options ?? {})) {
    if (COLOR_KEYS.has(k.toLowerCase())) return v;
  }
  return undefined;
}

export interface VariantDim {
  key: string;
  label: string;
  values: string[];
}

/** Non-color option dimensions whose values carry different prices (e.g. frame type). */
export function variantDims(m: Model): VariantDim[] {
  const seen = new Map<string, Set<string>>();
  for (const c of m.configurations ?? []) {
    for (const [k, v] of Object.entries(c.options ?? {})) {
      if (COLOR_KEYS.has(k.toLowerCase())) continue;
      if (!seen.has(k)) seen.set(k, new Set());
      seen.get(k)!.add(v);
    }
  }
  return [...seen.entries()]
    .filter(([key, vals]) => {
      if (vals.size < 2) return false;
      const prices = [...vals]
        .map((v) => variantPrice(m, undefined, { [key]: v }))
        .filter((p): p is number => p != null);
      return new Set(prices).size > 1;
    })
    .map(([key, vals]) => ({
      key,
      label: key.replace(/[-_]+/g, " ").replace(/^\w/, (ch) => ch.toUpperCase()),
      values: [...vals],
    }));
}

/** Min config price matching the given color (if any) and option selections. */
export function variantPrice(
  m: Model,
  colorName?: string,
  dims?: Record<string, string>,
): number | null {
  let best: number | null = null;
  for (const c of m.configurations ?? []) {
    if (c.price == null) continue;
    if (colorName && cfgColor(c) !== colorName) continue;
    if (dims && Object.entries(dims).some(([k, v]) => c.options?.[k] !== v)) continue;
    if (best == null || c.price < best) best = c.price;
  }
  return best;
}

/**
 * Price of each entry in model.colors (null when unknown), aligned by index.
 * Pass `dims` to price colors within a specific option selection.
 */
export function colorPrices(
  m: Model,
  dims?: Record<string, string>,
): (number | null)[] | undefined {
  if (!m.colors?.length) return undefined;
  const prices = m.colors.map((c) => variantPrice(m, c.name, dims));
  return prices.some((p) => p != null) ? prices : undefined;
}

/** Option values of the cheapest configuration — the default variant selection. */
export function defaultDims(m: Model): Record<string, string> {
  const dims = variantDims(m);
  if (!dims.length) return {};
  let best: Configuration | undefined;
  for (const c of m.configurations ?? []) {
    if (c.price == null) continue;
    if (!best || c.price < best.price!) best = c;
  }
  const out: Record<string, string> = {};
  for (const d of dims) {
    const v = best?.options?.[d.key];
    if (v != null) out[d.key] = v;
  }
  return out;
}

/** Lowest purchasable price independent of color/configuration. */
export function lowestPrice(m: Model): number | null {
  const candidates = [m.price ?? m.price_min];
  for (const c of m.configurations ?? []) {
    if (c.price != null) candidates.push(c.price);
  }
  const nums = candidates.filter((v): v is number => v != null);
  return nums.length ? Math.min(...nums) : null;
}
