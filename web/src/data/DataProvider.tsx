import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { AnyOrama } from "@orama/orama";
import type { Brand, Model, RawData, AnalysisStats, SpecValue } from "../types";
import { buildIndex, ENUM_FIELDS, PRODUCT_TYPE_ORDER, RANGE_FIELDS, type EnumField, type RangeField } from "../search/orama";

interface DataState {
  status: "loading" | "ready" | "error";
  error?: string;
  models: Model[];
  brands: Brand[];
  byId: Map<string, Model>;
  brandByName: Map<string, Brand>;
  analysisStats: AnalysisStats;
  /** Per-primary-type field distributions (cohort the detail page compares within). */
  analysisStatsByType: Record<string, AnalysisStats>;
  disclaimer: string;
  generatedAt: string;
  db: AnyOrama | null;
  facetOptions: Record<EnumField, string[]>;
  rangeBounds: Record<RangeField, [number, number]>;
}

const DataContext = createContext<DataState | null>(null);

function computeRangeBounds(stats: AnalysisStats, models: Model[]): Record<RangeField, [number, number]> {
  const out = {} as Record<RangeField, [number, number]>;
  for (const f of RANGE_FIELDS) {
    const s = stats[f];
    if (s && Number.isFinite(s.min) && Number.isFinite(s.max)) {
      out[f] = [Math.floor(s.min), Math.ceil(s.max)];
    } else {
      // derive from models (price has no stats key under that name in some builds)
      const vals = models
        .map((m) =>
          f === "price"
            ? m.price ?? m.price_min
            : (m.analysis?.specs_typed?.[f] as number | undefined),
        )
        .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
      out[f] = vals.length ? [Math.floor(Math.min(...vals)), Math.ceil(Math.max(...vals))] : [0, 0];
    }
  }
  return out;
}

function computeFacetOptions(models: Model[]): Record<EnumField, string[]> {
  const out = {} as Record<EnumField, string[]>;
  for (const f of ENUM_FIELDS) out[f] = [];
  const sets: Record<EnumField, Set<string>> = {} as Record<EnumField, Set<string>>;
  for (const f of ENUM_FIELDS) sets[f] = new Set();
  for (const m of models) {
    const t = m.analysis?.specs_typed ?? {};
    sets.brand.add(m.brand);
    for (const pt of m.product_types ?? (m.product_type ? [m.product_type] : [])) {
      sets.product_types.add(pt);
    }
    if (m.frame_style) sets.frame_style.add(m.frame_style);
    for (const f of ["drive_type", "brake_type", "frame_material", "suspension", "sensor_type"] as EnumField[]) {
      const v = t[f] as string | undefined;
      if (!v) continue;
      // bare "disc" = a disc brake whose actuation (hydraulic/mechanical) is
      // unknown; not a useful filter option since every brake is a disc brake.
      if (f === "brake_type" && v === "disc") continue;
      sets[f].add(v);
    }
  }
  for (const f of ENUM_FIELDS) out[f] = [...sets[f]].sort();
  // Types read best in the canonical taxonomy order, not alphabetically.
  out.product_types = PRODUCT_TYPE_ORDER.filter((t) => sets.product_types.has(t));
  return out;
}

/** The payload de-dupes parsed components into a doc-level `data.components` table and
 *  stores the entry's string KEY in each model.specs[group][field]. Replace each such key
 *  with the shared table entry — the SAME object per unique component across all models,
 *  so the parsed file holds far fewer objects (the mobile-memory win) and the rest of the
 *  app sees the normal specs shape. Non-component spec values stay inline (plain strings).
 *  No-op on an un-interned payload. Treat shared values as read-only. */
function rehydrateSpecs(data: RawData): void {
  const table = data.components;
  if (!table || typeof table !== "object") return;
  for (const m of data.models) {
    const specs = m.specs as Record<string, Record<string, SpecValue>> | undefined;
    if (!specs) continue;
    for (const group of Object.values(specs)) {
      if (group && typeof group === "object") {
        for (const f of Object.keys(group)) {
          const v = group[f];
          // a ref is a string key present in the components table; literals pass through
          if (typeof v === "string" && Object.prototype.hasOwnProperty.call(table, v)) {
            group[f] = table[v] as SpecValue;
          }
        }
      }
    }
  }
}

export function DataProvider({ children }: { children: ReactNode }) {
  const [raw, setRaw] = useState<RawData | null>(null);
  const [db, setDb] = useState<AnyOrama | null>(null);
  const [status, setStatus] = useState<DataState["status"]>("loading");
  const [error, setError] = useState<string>();

  useEffect(() => {
    let alive = true;
    const base = import.meta.env.BASE_URL || "/";
    fetch(`${base}ebike.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<RawData>;
      })
      .then(async (data) => {
        if (!alive) return;
        rehydrateSpecs(data);
        setRaw(data);
        const index = await buildIndex(data.models);
        if (!alive) return;
        setDb(index);
        setStatus("ready");
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
        setStatus("error");
      });
    return () => {
      alive = false;
    };
  }, []);

  const value = useMemo<DataState>(() => {
    const models = raw?.models ?? [];
    const brands = raw?.brands ?? [];
    return {
      status,
      error,
      models,
      brands,
      byId: new Map(models.map((m) => [m.id, m])),
      brandByName: new Map(brands.map((b) => [b.brand, b])),
      analysisStats: raw?.analysis_stats ?? {},
      analysisStatsByType: raw?.analysis_stats_by_type ?? {},
      disclaimer: raw?.analysis_disclaimer ?? "",
      generatedAt: raw?.generated_at ?? "",
      db,
      facetOptions: computeFacetOptions(models),
      rangeBounds: computeRangeBounds(raw?.analysis_stats ?? {}, models),
    };
  }, [raw, db, status, error]);

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useData(): DataState {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used within DataProvider");
  return ctx;
}
