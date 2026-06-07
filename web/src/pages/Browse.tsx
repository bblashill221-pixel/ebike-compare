import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { runSearch, type Filters } from "../search/orama";
import type { Model } from "../types";
import { SearchBar } from "../components/SearchBar";
import { FacetPanel } from "../components/FacetPanel";
import { ResultsGrid } from "../components/ResultsGrid";

const EMPTY_FILTERS: Filters = { enums: {}, bools: {}, ranges: {} };

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
  | "power_desc";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "relevance", label: "Relevance" },
  { key: "price_asc", label: "Price: low → high" },
  { key: "price_desc", label: "Price: high → low" },
  { key: "battery_desc", label: "Battery (Wh) ↓" },
  { key: "range_desc", label: "Range (mi) ↓" },
  { key: "torque_desc", label: "Torque (Nm) ↓" },
  { key: "motor_desc", label: "Motor (W) ↓" },
  { key: "weight_asc", label: "Weight (lb) ↑" },
  { key: "value_desc", label: "Value score ↓" },
  { key: "range_score_desc", label: "Range score ↓" },
  { key: "power_desc", label: "Power score ↓" },
];

const last = Number.NEGATIVE_INFINITY;
const typed = (m: Model, k: string) => (m.analysis?.specs_typed?.[k] as number | undefined);
const score = (m: Model, k: string) => m.analysis?.scores?.[k];

function sortModels(models: Model[], key: SortKey): Model[] {
  if (key === "relevance") return models;
  const arr = [...models];
  const byDesc = (f: (m: Model) => number | undefined) =>
    arr.sort((a, b) => (f(b) ?? last) - (f(a) ?? last));
  switch (key) {
    case "price_asc":
      return arr.sort((a, b) => (a.price ?? Infinity) - (b.price ?? Infinity));
    case "price_desc":
      return arr.sort((a, b) => (b.price ?? last) - (a.price ?? last));
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
  }
}

export function Browse() {
  const { status, error, db, models, byId, facetOptions, rangeBounds } = useData();
  const [params, setParams] = useSearchParams();

  const [term, setTerm] = useState(params.get("q") ?? "");
  const [debounced, setDebounced] = useState(term);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<SortKey>((params.get("sort") as SortKey) ?? "relevance");
  const [ids, setIds] = useState<string[]>([]);
  const [facetCounts, setFacetCounts] = useState<Record<string, Record<string, number>>>({});
  const [drawer, setDrawer] = useState(false);

  // debounce term -> mirror q+sort to the URL
  useEffect(() => {
    const t = setTimeout(() => setDebounced(term), 200);
    return () => clearTimeout(t);
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
    runSearch(db, debounced, filters, models.length).then((res) => {
      if (!alive) return;
      setIds(res.ids);
      setFacetCounts(res.facets);
    });
    return () => {
      alive = false;
    };
  }, [db, debounced, filters, models.length]);

  const results = useMemo(() => {
    const list = ids.map((id) => byId.get(id)).filter((m): m is Model => !!m);
    return sortModels(list, sort);
  }, [ids, byId, sort]);

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
          <div className="card sticky top-20 p-4">{facetPanel}</div>
        </aside>

        <div className="min-w-0 flex-1">
          <div className="mb-3 text-sm text-slate-500">{results.length} results</div>
          <ResultsGrid models={results} />
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
