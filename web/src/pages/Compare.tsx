import { useEffect, type ReactNode } from "react";
import { Link, useSearchParams, useNavigate, useLocation } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { useCompare } from "../compare/CompareContext";
import type { Model } from "../types";
import { titleCase, formatPrice, formatNumber } from "../format";
import { useUnits, inToFtIn, type UnitSystem } from "../units";
import { sensorLabel } from "../filterMeta";
import { Price } from "../components/Price";
import { HowEachComparesTable, HowEachComparesByMetric, HowItComparesLegend } from "../components/HowItCompares";
import { CompareTable } from "../components/CompareTable";
import { AffiliateLink } from "../components/AffiliateLink";
import { primaryImage } from "../components/BikeCard";
import { UncommonFeaturesList } from "../components/UncommonFeaturesList";
import { BatteryIcon, BrakeIcon, CheckIcon, FoldIcon, ForkIcon, GearsIcon, MotorIcon, PayloadIcon, RangeIcon, RiderHeightIcon, SpeedIcon, TagIcon, TorqueIcon, WeightIcon } from "../components/icons";

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

type Row = { label: string; icon?: ReactNode; get: (m: Model, u: UnitSystem) => string };
const I = "h-4 w-4";
const T = (m: Model) => (m.analysis?.specs_typed ?? {}) as Record<string, number | string | undefined>;
const n = (v: unknown) => (typeof v === "number" ? v : undefined);

const KEY_SPECS: Row[] = [
  { label: "Price", icon: <TagIcon className={I} />, get: (m) => (m.price ?? m.price_min) != null ? formatPrice(m.price ?? m.price_min) : "—" },
  { label: "Motor", icon: <MotorIcon className={I} />, get: (m) => { const t = T(m); const w = n(t.motor_w); if (w == null) return "—"; const pk = n(t.motor_peak_w); return `${formatNumber(w, 0)} W${pk ? ` (${formatNumber(pk, 0)} W peak)` : ""}`; } },
  { label: "Torque", icon: <TorqueIcon className={I} />, get: (m) => { const v = n(T(m).torque_nm); return v != null ? `${v} Nm` : "—"; } },
  { label: "Battery", icon: <BatteryIcon className={I} />, get: (m) => { const v = n(T(m).battery_wh); return v != null ? `${formatNumber(v, 0)} Wh` : "—"; } },
  { label: "Range", icon: <RangeIcon className={I} />, get: (m, u) => { const t = T(m); const v = n(t.range_mi); if (v == null) return "—"; const lo = n(t.range_min_mi); return lo != null && lo !== v ? `${mi(lo, u).replace(/ \w+$/, "")}–${mi(v, u)}` : mi(v, u); } },
  { label: "Top speed", icon: <SpeedIcon className={I} />, get: (m, u) => { const v = n(T(m).max_speed_mph); return v != null ? mph(v, u) : "—"; } },
  { label: "Weight", icon: <WeightIcon className={I} />, get: (m, u) => { const v = n(T(m).weight_lb); return v != null ? lb(v, u) : "—"; } },
  { label: "Max Payload", icon: <PayloadIcon className={I} />, get: (m, u) => { const v = n(T(m).max_load_lb); return v != null ? lb(v, u) : "—"; } },
  { label: "Drive Type", get: (m) => cap(T(m).drive_type) },
  { label: "Sensor Type", get: (m) => { const s = T(m).sensor_type; return typeof s === "string" && s ? sensorLabel(s) : "—"; } },
  { label: "Brakes", icon: <BrakeIcon className={I} />, get: (m) => cap(T(m).brake_type) },
  { label: "Gears", icon: <GearsIcon className={I} />, get: (m) => { const v = n(T(m).gears); return v != null ? `${v}-speed` : "—"; } },
  { label: "Drivetrain", get: (m) => cap(T(m).drivetrain_type) },
  { label: "Suspension", icon: <ForkIcon className={I} />, get: (m) => cap(T(m).suspension) },
  { label: "Frame", get: (m) => cap(T(m).frame_material) },
  { label: "Display", get: (m) => cap(T(m).display_type) },
  { label: "Height Range", icon: <RiderHeightIcon className={I} />, get: (m, u) => heightRange(T(m), u) },
  { label: "Warranty", icon: <CheckIcon className={I} />, get: (m) => { const v = n(T(m).warranty_years); return v != null ? `${v} yr` : "—"; } },
  { label: "Folding", icon: <FoldIcon className={I} />, get: (m) => (m.folding ? "Yes" : "—") },
  // CAN bus is shown as the Motor's "Protocol" field (in the eBike System breakdown), not here.
];

const isBlank = (v: string) => v === "" || v === "—" || v.toUpperCase() === "N/A";

// Mobile: a spec field as its label + one line per eBike (name — value). Amber tint when they differ.
function MobileSpecRow({ label, icon, models, values }: { label: ReactNode; icon?: ReactNode; models: Model[]; values: string[] }) {
  const differ = new Set(values.filter((v) => !isBlank(v))).size > 1;
  return (
    <div className="px-3 py-2">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-500">
        {icon && <span className="flex w-4 shrink-0 justify-center">{icon}</span>}
        {label}
      </div>
      <div className={`mt-1 space-y-0.5 rounded ${differ ? "bg-amber-50/60 px-2 py-1" : ""}`}>
        {models.map((m, i) => (
          <div key={m.id} className="flex items-start justify-between gap-2 text-sm">
            <span className="min-w-0 flex-1 text-xs font-medium uppercase leading-tight tracking-wide text-slate-400">{m.model}</span>
            <span className="min-w-0 max-w-[52%] shrink-0 break-words text-right font-medium leading-tight text-slate-800">{values[i]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Compare() {
  const { byId, models: allModels, status } = useData();
  const { ids: trayIds, toggle } = useCompare();
  const [params] = useSearchParams();
  const [units] = useUnits();
  const navigate = useNavigate();
  const location = useLocation();
  // Return to wherever the user came from; location.key is "default" only on a direct
  // load with no history to go back to, in which case fall back to the Ebikes list.
  const goBack = () =>
    location.key !== "default" ? navigate(-1) : navigate("/");

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
            Add at least two eBikes to compare. Browse and tap <strong>Compare</strong> on the bikes you’re weighing.
          </p>
          <Link to="/" className="btn-primary">Browse eBikes</Link>
        </div>
      </Center>
    );
  }

  // Always lay out a 4-eBike comparison: real bikes fill from the left, the remaining slots
  // are empty "Add an eBike" placeholders so the grid is constant no matter how many are compared.
  const empties = Math.max(0, 4 - models.length);
  const cols = `minmax(8rem,10rem) repeat(4, minmax(0,1fr))`;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <h1 className="text-xl font-bold text-slate-900">Compare {models.length} eBikes</h1>
      <button onClick={goBack} className="mb-4 mt-1 inline-block text-sm text-brand-600 hover:underline">← Back</button>

      {/* header + key specs + scores */}
      <div className="card mb-6">
       <div className="overflow-x-auto">
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
                    <img src={primaryImage(m)!} alt="" className="mb-2 h-20 w-full object-contain object-left" />
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
            {Array.from({ length: empties }).map((_, i) => (
              <Link key={`add-${i}`} to="/" className="flex items-center justify-center border-l border-dashed border-slate-200 p-3 text-center text-sm text-slate-400 hover:text-brand-600">
                + Add an eBike
              </Link>
            ))}
          </div>
          {/* desktop: Special Features + Key Specs as eBike columns */}
          <div className="hidden md:block">
          {/* Special Features — placed right under the price. It's a single grid row,
              so all columns stretch to the same height and stay aligned even when a bike
              has fewer (or no) special features (those cells read "—"). Shown only when
              at least one compared bike has any. */}
          {models.some((m) => (m.analysis?.uncommon_features ?? []).length > 0) && (
            <div className="grid border-b border-slate-100" style={{ gridTemplateColumns: cols }}>
              <div className="bg-slate-50/50 p-2 text-sm font-medium text-slate-500">Special Features</div>
              {models.map((m) => (
                <div key={m.id} className="border-l border-slate-100 p-2">
                  <UncommonFeaturesList features={m.analysis?.uncommon_features} />
                </div>
              ))}
              {Array.from({ length: empties }).map((_, i) => (
                <div key={`e-${i}`} className="border-l border-slate-100 p-2" />
              ))}
            </div>
          )}
          {/* key specs — a curated at-a-glance comparison; every key is always shown
              (a bike missing that value reads "—"), differences shaded */}
          {KEY_SPECS.map(({ label, icon, get }) => {
            const vals = models.map((m) => get(m, units));
            // hide a row when NONE of the compared bikes have that value (all —/N/A) —
            // e.g. "Folding" won't show when comparing eMTBs. Rows where SOME bikes have
            // it still show (the ones lacking it read "—").
            const has = (v: string) => v !== "—" && v !== "" && v.toUpperCase() !== "N/A";
            if (!vals.some(has)) return null;
            const differ = new Set(vals.filter(has)).size > 1;
            return (
              <div key={label} className="grid border-b border-slate-50" style={{ gridTemplateColumns: cols }}>
                <div className="flex items-center gap-2 bg-slate-50/50 p-2 text-sm font-medium text-slate-500">
                  <span className="flex w-4 shrink-0 justify-center">{icon}</span>
                  {label}
                </div>
                {vals.map((v, i) => (
                  <div key={i} className={`border-l border-slate-100 p-2 text-sm text-slate-800 ${differ ? "bg-amber-50/60" : ""}`}>
                    {v}
                  </div>
                ))}
                {Array.from({ length: empties }).map((_, i) => (
                  <div key={`e-${i}`} className="border-l border-slate-100 p-2" />
                ))}
              </div>
            );
          })}
          </div>
        </div>
       </div>
        {/* mobile: inverted — Special Features + Key Specs, one line per eBike */}
        <div className="divide-y divide-slate-100 border-t border-slate-100 md:hidden">
          {models.some((m) => (m.analysis?.uncommon_features ?? []).length > 0) && (
            <div className="px-3 py-2">
              <div className="text-sm font-medium text-slate-500">Special Features</div>
              <div className="mt-1 space-y-2">
                {models.map((m) => (
                  <div key={m.id}>
                    <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{m.model}</div>
                    <UncommonFeaturesList features={m.analysis?.uncommon_features} />
                  </div>
                ))}
              </div>
            </div>
          )}
          {KEY_SPECS.map(({ label, icon, get }) => {
            const vals = models.map((m) => get(m, units));
            if (!vals.some((v) => !isBlank(v))) return null;
            return <MobileSpecRow key={label} label={label} icon={icon} models={models} values={vals} />;
          })}
        </div>
      </div>

      {/* How each bike compares to its OWN type — ONE combined table: metric names once on the
          left, each model a group of angled columns (Low/Median/High/This eBike/Diff/Rank, or
          Median/This eBike/Diff/Rank when 4 bikes), numbered-bolt rank, grid lines. */}
      <div className="card mb-4 overflow-x-auto p-4">
        <h3 className="mb-3 font-semibold text-slate-800">How Each Compares Within Its Type</h3>
        {/* desktop: one combined table with all bikes side by side */}
        <div className="hidden md:block">
          <HowEachComparesTable models={models} allModels={allModels} units={units} />
        </div>
        {/* mobile: inverted — one card per metric (field name = header), a row per eBike */}
        <div className="md:hidden">
          <HowEachComparesByMetric models={models} allModels={allModels} units={units} />
        </div>
        <HowItComparesLegend badge />
      </div>

      <div className="overflow-x-auto">
        <div className="md:min-w-[40rem]">
          <CompareTable models={models} />
        </div>
      </div>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[50vh] items-center justify-center px-4 text-slate-500">{children}</div>;
}
