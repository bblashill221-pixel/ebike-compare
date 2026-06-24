import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { runSearch, type Filters } from "../search/orama";
import type { Model } from "../types";
import { lowestPrice } from "../pricing";
import { SearchBar } from "../components/SearchBar";
import { FacetPanel } from "../components/FacetPanel";
import { ResultsGrid } from "../components/ResultsGrid";
import { ActiveFilters } from "../components/ActiveFilters";
import { useShowSoldOut } from "../soldOut";
import { useUnits } from "../units";
import { filtersFromParams, hasQuizParams, QUIZ_PARAM_KEYS } from "../findMyEbike";
import { loadStoredFilters, saveStoredFilters, sanitizeFilters, loadStoredSearch, saveStoredSearch } from "../filterStorage";

const EMPTY_FILTERS: Filters = { enums: {}, bools: {}, ranges: {}, riderHeightIn: null };

// Scroll position to restore when the user comes back from a detail page.
// Session-scoped so a fresh visit always starts at the top.
const SCROLL_KEY = "browse-scroll-y";

type SortKey =
  | "relevance"
  | "price_asc"
  | "price_desc"
  | "battery_desc"
  | "range_desc"
  | "torque_desc"
  | "motor_desc"
  | "weight_asc"
  | "value_desc"
  | "range_score_desc"
  | "power_desc"
  | "parts_retail_desc";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "relevance", label: "Relevance" },
  { key: "price_asc", label: "Price: low → high" },
  { key: "price_desc", label: "Price: high → low" },
  { key: "battery_desc", label: "Battery (Wh) ↓" },
  { key: "range_desc", label: "Range (mi) ↓" },
  { key: "torque_desc", label: "Torque (Nm) ↓" },
  { key: "motor_desc", label: "Motor (W) ↓" },
  { key: "weight_asc", label: "Weight (lb) ↑" },
  { key: "value_desc", label: "Value (within type) ↓" },
  { key: "range_score_desc", label: "Range score (within type) ↓" },
  { key: "power_desc", label: "Power score (within type) ↓" },
  { key: "parts_retail_desc", label: "Parts value (retail $) ↓" },
];

const last = Number.NEGATIVE_INFINITY;
const typed = (m: Model, k: string) => (m.analysis?.specs_typed?.[k] as number | undefined);
const score = (m: Model, k: string) => m.analysis?.scores?.[k];
const cq = (m: Model, k: string) =>
  (m.analysis?.component_quality?.[k as keyof NonNullable<Model["analysis"]["component_quality"]>] as number | null | undefined) ?? undefined;

function sortModels(models: Model[], key: SortKey): Model[] {
  if (key === "relevance") return models;
  const arr = [...models];
  const byDesc = (f: (m: Model) => number | undefined) =>
    arr.sort((a, b) => (f(b) ?? last) - (f(a) ?? last));
  switch (key) {
    case "price_asc":
      return arr.sort((a, b) => (lowestPrice(a) ?? Infinity) - (lowestPrice(b) ?? Infinity));
    case "price_desc":
      return arr.sort((a, b) => (lowestPrice(b) ?? last) - (lowestPrice(a) ?? last));
    case "battery_desc":
      return byDesc((m) => typed(m, "battery_wh"));
    case "range_desc":
      return byDesc((m) => typed(m, "range_mi"));
    case "torque_desc":
      return byDesc((m) => typed(m, "torque_nm"));
    case "motor_desc":
      return byDesc((m) => typed(m, "motor_w"));
    case "weight_asc":
      return arr.sort((a, b) => (typed(a, "weight_lb") ?? Infinity) - (typed(b, "weight_lb") ?? Infinity));
    case "value_desc":
      return byDesc((m) => score(m, "value"));
    case "range_score_desc":
      return byDesc((m) => score(m, "range"));
    case "power_desc":
      return byDesc((m) => score(m, "power"));
    case "parts_retail_desc":
      return byDesc((m) => cq(m, "component_retail_value_usd"));
  }
}

export function Browse() {
  const { status, error, db, models, byId, facetOptions, rangeBounds } = useData();
  const [params, setParams] = useSearchParams();

  // search text persists like the filters: a ?q= link wins, else the last search
  const [term, setTerm] = useState(params.get("q") ?? loadStoredSearch());
  const [debounced, setDebounced] = useState(term);
  // filter panel state survives detail-page round-trips and fresh visits;
  // a query-param link overrides it (and the override is persisted below)
  const [filters, setFiltersState] = useState<Filters>(
    () => loadStoredFilters() ?? EMPTY_FILTERS,
  );
  const setFilters = (f: Filters) => {
    setFiltersState(f);
    saveStoredFilters(f);
    // a filter change resets the listing to the top. Scrolling the WINDOW (not the
    // filter panel, which is a sticky, internally-scrolled sidebar) leaves the
    // user's place in the filter list untouched. Also disable the one-time scroll
    // restore so it can't yank the page back down when the new results arrive.
    restoredScroll.current = true;
    window.scrollTo(0, 0);
  };
  const [showSoldOut] = useShowSoldOut();
  const [units] = useUnits();
  // sort persists independently (explicitly set; never touched by query params);
  // an explicit ?sort= in a shared link still wins for that visit
  const [sort, setSortState] = useState<SortKey>(
    (params.get("sort") as SortKey) ??
      ((localStorage.getItem("browse-sort") as SortKey) || "relevance"),
  );
  const setSort = (s: SortKey) => {
    setSortState(s);
    try {
      localStorage.setItem("browse-sort", s);
    } catch {
      /* storage blocked */
    }
  };
  const [ids, setIds] = useState<string[]>([]);
  const [facetCounts, setFacetCounts] = useState<Record<string, Record<string, number>>>({});
  const [drawer, setDrawer] = useState(false);

  // Once the catalog is ready: a "Find My eBike" link (?type=…&price_max=…)
  // OVERRIDES the stored filter panel (and the override is persisted), then the
  // params are stripped so they don't linger as the user edits filters. Without
  // params, the stored filters just get sanitized against the live catalog.
  // Sort / sold-out / units are never touched by this — separate persistence.
  // Reactive to `params`, not run-once: a quiz link can arrive as a hash-only
  // navigation while Browse is already mounted (no remount), and must still
  // override. The ref only gates the one-time sanitize of stored filters.
  const hydrated = useRef(false);
  useEffect(() => {
    if (status !== "ready") return;
    if (hasQuizParams(params)) {
      setFilters(filtersFromParams(params, rangeBounds));
      const next = new URLSearchParams(params);
      for (const k of QUIZ_PARAM_KEYS) next.delete(k);
      setParams(next, { replace: true });
    } else if (!hydrated.current) {
      setFiltersState((f) => sanitizeFilters(f, facetOptions));
    }
    hydrated.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, params]);

  // debounce term -> mirror q+sort to the URL; persist the search like the filters
  useEffect(() => {
    const t = setTimeout(() => setDebounced(term), 200);
    return () => clearTimeout(t);
  }, [term]);
  useEffect(() => {
    saveStoredSearch(term);
  }, [term]);
  useEffect(() => {
    const next = new URLSearchParams(params);
    if (term) next.set("q", term);
    else next.delete("q");
    if (sort !== "relevance") next.set("sort", sort);
    else next.delete("sort");
    setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, sort]);

  // run search whenever the index / query / filters change
  useEffect(() => {
    if (!db) return;
    let alive = true;
    runSearch(db, debounced, filters, models.length, showSoldOut, units).then((res) => {
      if (!alive) return;
      setIds(res.ids);
      setFacetCounts(res.facets);
    });
    return () => {
      alive = false;
    };
  }, [db, debounced, filters, models.length, showSoldOut, units]);

  const results = useMemo(() => {
    const list = ids.map((id) => byId.get(id)).filter((m): m is Model => !!m);
    return sortModels(list, sort);
  }, [ids, byId, sort]);

  // Capture the position saved by the previous visit at first render — the
  // unmount save below also fires during StrictMode's simulated remount (with
  // scrollY 0), so storage can't be trusted by the time results arrive.
  const savedScroll = useRef(Number(sessionStorage.getItem(SCROLL_KEY)) || 0);
  // remember where the user was when leaving (e.g. into a bike detail page)...
  useEffect(() => {
    return () => sessionStorage.setItem(SCROLL_KEY, String(window.scrollY));
  }, []);
  // ...and jump back there once, as soon as the grid is tall enough again
  const restoredScroll = useRef(false);
  useEffect(() => {
    if (restoredScroll.current || !results.length) return;
    restoredScroll.current = true;
    if (savedScroll.current > 0) window.scrollTo(0, savedScroll.current);
  }, [results]);

  if (status === "loading") return <CenterMsg>Loading e-bikes…</CenterMsg>;
  if (status === "error") return <CenterMsg>Failed to load data: {error}</CenterMsg>;

  const facetPanel = (
    <FacetPanel
      facetOptions={facetOptions}
      rangeBounds={rangeBounds}
      facetCounts={facetCounts}
      filters={filters}
      setFilters={setFilters}
    />
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <SearchBar value={term} onChange={setTerm} />
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="rounded-lg border-slate-300 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500"
          aria-label="Sort by"
        >
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <button type="button" className="btn-ghost lg:hidden" onClick={() => setDrawer(true)}>
          Filters
        </button>
      </div>

      <div className="flex gap-6">
        <aside className="hidden w-64 shrink-0 lg:block">
          {/* cap at the viewport (below the sticky header) so the panel scrolls internally */}
          <div className="card sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto p-4">{facetPanel}</div>
        </aside>

        <div className="min-w-0 flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-slate-500">
            <span className="shrink-0">{results.length} results</span>
            <ActiveFilters filters={filters} setFilters={setFilters} />
          </div>
          <ResultsGrid models={results} selectedTypes={filters.enums.product_types ?? []} />
        </div>
      </div>

      {/* mobile filter drawer */}
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 w-80 max-w-[85%] overflow-auto bg-white p-4 shadow-xl">
            <div className="mb-3 flex justify-end">
              <button type="button" className="btn-ghost" onClick={() => setDrawer(false)}>
                Done
              </button>
            </div>
            {facetPanel}
          </div>
        </div>
      )}
    </div>
  );
}

function CenterMsg({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[50vh] items-center justify-center text-slate-500">{children}</div>;
}
