import { useCallback, useEffect, useState } from "react";
import type { Model } from "./types";

// Per-model color selection shared across views: picking a color on a Browse
// card carries into the detail page and back again. Session-scoped so a fresh
// visit starts on each bike's default colorway.
const KEY = "color-selection";

function load(): Record<string, number> {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || "{}") as Record<string, number>;
  } catch {
    return {};
  }
}

const store: Record<string, number> = load();

/** Lowercased names of the colorways reported sold out for a model. */
export function soldOutColors(model: Model): Set<string> {
  const out = new Set<string>();
  const axes = model.availability?.sold_out_options ?? {};
  for (const [axis, vals] of Object.entries(axes)) {
    if (/colou?rs?/i.test(axis)) for (const v of vals) out.add(v.toLowerCase());
  }
  return out;
}

/** True when the colorway at `index` is one of the model's sold-out colors. */
export function colorSoldOut(model: Model, index: number): boolean {
  const name = model.colors?.[index]?.name;
  return !!name && soldOutColors(model).has(name.toLowerCase());
}

/** Index of the first in-stock colorway (0 when none/all are available). */
export function defaultColorIndex(model: Model): number {
  const colors = model.colors ?? [];
  const sold = soldOutColors(model);
  if (!sold.size) return 0;
  const i = colors.findIndex((c) => !sold.has((c.name ?? "").toLowerCase()));
  return i >= 0 ? i : 0;
}

function stored(id: string | undefined, count: number, fallback: number): number {
  const v = id && store[id] != null ? store[id] : fallback;
  return v >= 0 && v < Math.max(count, 1) ? v : 0;
}

/** [selected color index, setter] for a model, kept in sync across views.
 *  Falls back to `fallback` (the first in-stock color) on a fresh visit. */
export function useColorSelection(
  id: string | undefined,
  count: number,
  fallback = 0,
): [number, (i: number) => void] {
  const [sel, setSel] = useState(() => stored(id, count, fallback));
  // re-read when the route swaps models in place (detail -> sibling detail)
  useEffect(() => {
    setSel(stored(id, count, fallback));
  }, [id, count, fallback]);
  const set = useCallback(
    (i: number) => {
      if (id) {
        store[id] = i;
        try {
          sessionStorage.setItem(KEY, JSON.stringify(store));
        } catch {
          /* storage full/blocked: selection still works for this view */
        }
      }
      setSel(i);
    },
    [id],
  );
  return [sel, set];
}
