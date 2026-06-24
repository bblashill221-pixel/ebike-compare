import type { Filters } from "./search/orama";

// Persistent filter-panel selection (localStorage), so filters survive
// navigating to a detail page and fresh visits. Two persistence classes:
//  - the filter panel itself: a Find-My-eBike/query-param link OVERRIDES it
//    (and the override is saved here);
//  - sort / sold-out / units: persisted by their own stores and never touched
//    by query-param changes (explicitly set and unset by the user).
const KEY = "browse-filters";

export function loadStoredFilters(): Filters | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const f = JSON.parse(raw) as Filters;
    return {
      enums: f.enums ?? {},
      bools: f.bools ?? {},
      ranges: f.ranges ?? {},
      riderHeightIn: f.riderHeightIn ?? null,
      priceCeiling: f.priceCeiling ?? null,
    };
  } catch {
    return null;
  }
}

export function saveStoredFilters(f: Filters): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(f));
  } catch {
    /* storage blocked/full: filters still work for this view */
  }
}

// Search text persists like the filter panel: it survives detail-page round-trips
// and fresh visits, and a ?q= link still overrides it for that visit.
const SEARCH_KEY = "browse-search";

export function loadStoredSearch(): string {
  try {
    return localStorage.getItem(SEARCH_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveStoredSearch(q: string): void {
  try {
    localStorage.setItem(SEARCH_KEY, q);
  } catch {
    /* storage blocked: search still works for this view */
  }
}

/** Drop stored enum values that no longer exist in the catalog. */
export function sanitizeFilters(
  f: Filters,
  facetOptions: Record<string, string[]>,
): Filters {
  const enums: Filters["enums"] = {};
  for (const [field, vals] of Object.entries(f.enums)) {
    const known = facetOptions[field];
    const keep = known ? (vals ?? []).filter((v) => known.includes(v)) : vals ?? [];
    if (keep.length) enums[field as keyof Filters["enums"]] = keep;
  }
  return { ...f, enums };
}
