import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { useCompare } from "../compare/CompareContext";
import type { Model } from "../types";
import { titleCase, formatPrice, formatNumber } from "../format";
import { useUnits, inToFtIn, type UnitSystem } from "../units";
import { sensorLabel } from "../filterMeta";
import { Price } from "../components/Price";
import { SCORE_ORDER } from "../components/ScoreBars";
import { CompareTable } from "../components/CompareTable";
import { AffiliateLink } from "../components/AffiliateLink";
import { primaryImage } from "../components/BikeCard";
import { UncommonFeaturesList } from "../components/UncommonFeaturesList";

// ----- key spec rows (the at-a-glance comparison; deliberately curated, not every
// parsed component — e.g. pedals/grips live only in the detailed tables below) -----
const KM = 1.60934;
const KG = 0.453592;
const mi = (n: number, u: UnitSystem) => (u === "metric" ? `${Math.round(n * KM)} km` : `${formatNumber(n, 0)} mi`);
const mph = (n: number, u: UnitSystem) => (u === "metric" ? `${Math.round(n * KM)} km/h` : `${formatNumber(n, 0)} mph`);
const lb = (n: number, u: UnitSystem) => (u === "metric" ? `${Math.round(n * KG)} kg` : `${formatNumber(n, 0)} lb`);
const cap = (s: unknown) => (typeof s === "string" && s ? titleCase(s) : "—");

function heightRange(t: Record<string, unknown>, u: UnitSystem): string {
  const inMin = t.fit_height_min_in as number | undefined, inMax = t.fit_height_max_in as number | undefined;
  if (inMin == null || inMax == null) return "—";
  const mmMin = t.fit_height_min_mm as number | undefined, mmMax = t.fit_height_max_mm as number | undefined;
  if (u === "metric" && mmMin != null && mmMax != null) return `${Math.round(mmMin / 10)}–${Math.round(mmMax / 10)} cm`;
  const f = (n: number) => `${inToFtIn(n).ft}'${inToFtIn(n).in}"`;
  return `${f(inMin)}–${f(inMax)}`;
}

type Row = { label: string; get: (m: Model, u: UnitSystem) => string };
const T = (m: Model) => (m.analysis?.specs_typed ?? {}) as Record<string, number | string | undefined>;
const n = (v: unknown) => (typeof v === "number" ? v : undefined);

const KEY_SPECS: Row[] = [
  { label: "Price", get: (m) => (m.price ?? m.price_min) != null ? formatPrice(m.price ?? m.price_min) : "—" },
  { label: "Motor", get: (m) => { const t = T(m); const w = n(t.motor_w); if (w == null) return "—"; const pk = n(t.motor_peak_w); return `${formatNumber(w, 0)} W${pk ? ` (${formatNumber(pk, 0)} W peak)` : ""}`; } },
  { label: "Torque", get: (m) => { const v = n(T(m).torque_nm); return v != null ? `${v} Nm` : "—"; } },
  { label: "Battery", get: (m) => { const v = n(T(m).battery_wh); return v != null ? `${formatNumber(v, 0)} Wh` : "—"; } },
  { label: "Range", get: (m, u) => { const t = T(m); const v = n(t.range_mi); if (v == null) return "—"; const lo = n(t.range_min_mi); return lo != null && lo !== v ? `${mi(lo, u).replace(/ \w+$/, "")}–${mi(v, u)}` : mi(v, u); } },
  { label: "Top speed", get: (m, u) => { const v = n(T(m).max_speed_mph); return v != null ? mph(v, u) : "—"; } },
  { label: "Weight", get: (m, u) => { const v = n(T(m).weight_lb); return v != null ? lb(v, u) : "—"; } },
  { label: "Max Payload", get: (m, u) => { const v = n(T(m).max_load_lb); return v != null ? lb(v, u) : "—"; } },
  { label: "Drive Type", get: (m) => cap(T(m).drive_type) },
  { label: "Sensor Type", get: (m) => { const s = T(m).sensor_type; return typeof s === "string" && s ? sensorLabel(s) : "—"; } },
  { label: "Brakes", get: (m) => cap(T(m).brake_type) },
  { label: "Gears", get: (m) => { const v = n(T(m).gears); return v != null ? `${v}-speed` : "—"; } },
  { label: "Drivetrain", get: (m) => cap(T(m).drivetrain_type) },
  { label: "Suspension", get: (m) => cap(T(m).suspension) },
  { label: "Frame", get: (m) => cap(T(m).frame_material) },
  { label: "Display", get: (m) => cap(T(m).display_type) },
  { label: "Height Range", get: (m, u) => heightRange(T(m), u) },
  { label: "Warranty", get: (m) => { const v = n(T(m).warranty_years); return v != null ? `${v} yr` : "—"; } },
  { label: "Folding", get: (m) => (m.folding ? "Yes" : "—") },
  // CAN bus is shown as the Motor's "Protocol" field (in the eBike System breakdown), not here.
];

export function Compare() {
  const { byId, status } = useData();
  const { ids: trayIds, toggle } = useCompare();
  const [params] = useSearchParams();
  const [units] = useUnits();

  // Seed the compare tray from ?ids= on first load (shareable URLs).
  const urlIds = (params.get("ids") ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  useEffect(() => {
    if (urlIds.length) {
      urlIds.forEach((id) => {
        if (!trayIds.includes(id)) toggle(id);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (status === "loading") {
    return <Center>Loading…</Center>;
  }

  const ids = (trayIds.length ? trayIds : urlIds).slice(0, 4);
  const models = ids.map((id) => byId.get(id)).filter((m): m is Model => !!m);

  if (models.length < 2) {
    return (
      <Center>
        <div className="max-w-md text-center">
          <p className="mb-3 text-slate-600">
            Add at least two e-bikes to compare. Browse and tap <strong>Compare</strong> on the bikes you’re weighing.
          </p>
          <Link to="/" className="btn-primary">Browse e-bikes</Link>
        </div>
      </Center>
    );
  }

  const cols = `minmax(8rem,10rem) repeat(${models.length}, minmax(0,1fr))`;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <h1 className="text-xl font-bold text-slate-900">Compare {models.length} e-bikes</h1>
      <Link to="/" className="mb-4 mt-1 inline-block text-sm text-brand-600 hover:underline">← Back to browse</Link>

      {/* header + key specs + scores */}
      <div className="card mb-6 overflow-x-auto">
        <div className="min-w-[40rem]">
          {/* model headers — image + brand + name + price all link to the detail page */}
          <div className="grid border-b border-slate-100" style={{ gridTemplateColumns: cols }}>
            <div className="p-3" />
            {models.map((m) => (
              <div key={m.id} className="border-l border-slate-100 p-3">
                <Link
                  to={`/bike/${encodeURIComponent(m.id)}`}
                  className="group block rounded hover:bg-slate-50"
                >
                  {primaryImage(m) ? (
                    <img src={primaryImage(m)!} alt="" className="mb-2 h-20 w-full object-contain" />
                  ) : null}
                  <div className="text-xs font-medium uppercase tracking-wide text-brand-600">{m.brand}</div>
                  <div className="font-bold text-slate-900 group-hover:text-brand-700">{m.model}</div>
                  <div className="mt-1"><Price model={m} /></div>
                </Link>
                <div className="mt-2 flex flex-col gap-1">
                  <AffiliateLink brand={m.brand} url={m.url} className="text-sm font-medium text-brand-700 hover:underline">
                    View at {titleCase(m.brand)} →
                  </AffiliateLink>
                  <button type="button" onClick={() => toggle(m.id)} className="text-left text-xs text-slate-400 hover:text-rose-600">
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
          {/* key specs — a curated at-a-glance comparison; every key is always shown
              (a bike missing that value reads "—"), differences shaded */}
          {KEY_SPECS.map(({ label, get }) => {
            const vals = models.map((m) => get(m, units));
            // hide a row when NONE of the compared bikes have that value (all —/N/A) —
            // e.g. "Folding" won't show when comparing eMTBs. Rows where SOME bikes have
            // it still show (the ones lacking it read "—").
            const has = (v: string) => v !== "—" && v !== "" && v.toUpperCase() !== "N/A";
            if (!vals.some(has)) return null;
            const differ = new Set(vals.filter(has)).size > 1;
            return (
              <div key={label} className="grid border-b border-slate-50" style={{ gridTemplateColumns: cols }}>
                <div className="bg-slate-50/50 p-2 text-sm font-medium text-slate-500">{label}</div>
                {vals.map((v, i) => (
                  <div key={i} className={`border-l border-slate-100 p-2 text-sm text-slate-800 ${differ ? "bg-amber-50/60" : ""}`}>
                    {v}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* Special Features — premium/notable equipment each bike has (above Dimension Scores) */}
      {models.some((m) => (m.analysis?.uncommon_features ?? []).length > 0) && (
        <div className="card mb-4 overflow-x-auto">
          <h3 className="border-b border-slate-100 bg-slate-50 px-4 py-2 font-semibold text-slate-800">Special Features</h3>
          <div className="min-w-[40rem]">
            <div className="grid border-b border-slate-100" style={{ gridTemplateColumns: cols }}>
              <div className="px-4 py-2" />
              {models.map((m) => (
                <div key={m.id} className="truncate border-l border-slate-100 px-4 py-2 text-xs font-bold text-slate-800">{m.model}</div>
              ))}
            </div>
            <div className="grid" style={{ gridTemplateColumns: cols }}>
              <div className="bg-slate-50/50 px-4 py-2" />
              {models.map((m) => (
                <div key={m.id} className="border-l border-slate-100 px-4 py-2">
                  <UncommonFeaturesList features={m.analysis?.uncommon_features} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Dimension Scores — independent comparison ratings (0–100, ranked within type) */}
      <div className="card mb-4 overflow-x-auto">
        <h3 className="border-b border-slate-100 bg-slate-50 px-4 py-2 font-semibold text-slate-800">Dimension Scores</h3>
        <div className="min-w-[40rem]">
          <div className="grid border-b border-slate-100" style={{ gridTemplateColumns: cols }}>
            <div className="p-2" />
            {models.map((m) => (
              <div key={m.id} className="truncate border-l border-slate-100 p-2 text-xs font-bold text-slate-800">{m.model}</div>
            ))}
          </div>
          {SCORE_ORDER.filter((k) => models.some((m) => k in (m.analysis?.scores ?? {}))).map((k) => {
            const vals = models.map((m) => m.analysis?.scores?.[k]);
            const best = Math.max(...vals.map((v) => v ?? -1));
            return (
              <div key={k} className="grid border-b border-slate-50" style={{ gridTemplateColumns: cols }}>
                <div className="bg-slate-50/50 p-2 text-sm font-medium text-slate-500">{titleCase(k)}</div>
                {vals.map((v, i) => (
                  <div key={i} className="border-l border-slate-100 p-2">
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.max(0, Math.min(100, v ?? 0))}%` }} />
                      </div>
                      <span className={`w-7 text-right text-xs tabular-nums ${v != null && v === best && best > 0 ? "font-bold text-emerald-600" : "text-slate-500"}`}>
                        {v != null ? Math.round(v) : "—"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>

      <p className="mb-4 text-xs text-slate-400">
        Scores are independent comparison aids (0–100); the best in each row is highlighted. There is no overall winner — compare on what matters to you. Differing spec rows below are shaded.
      </p>

      <div className="overflow-x-auto">
        <div className="min-w-[40rem]">
          <CompareTable models={models} />
        </div>
      </div>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[50vh] items-center justify-center px-4 text-slate-500">{children}</div>;
}
