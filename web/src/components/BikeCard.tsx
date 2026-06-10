import { memo, useEffect } from "react";
import { useColorSelection, defaultColorIndex, colorSoldOut, soldOutColors } from "../colorSelection";
import { useShowSoldOut } from "../soldOut";
import { Link } from "react-router-dom";
import type { Model } from "../types";
import { capitalize, formatNumber } from "../format";
import { colorPrices, variantPrice } from "../pricing";
import { useCompare } from "../compare/CompareContext";
import { Price } from "./Price";
import { AffiliateLink } from "./AffiliateLink";
import { ColorSwatches, upchargeText } from "./ColorSwatches";
import { BatteryIcon, MotorIcon, RangeIcon, RiderHeightIcon, TorqueIcon, WeightIcon } from "./icons";
import { useUnits, inToFtIn } from "../units";

export function primaryImage(m: Model): string | null {
  return m.colors?.find((c) => c.image)?.image ?? null;
}

/** Model name without the redundant tier suffix (the tier badge carries it). */
export function displayName(m: Model): string {
  return m.tier ? m.model.replace(` — ${m.tier}`, "") : m.model;
}

function Spec({
  icon,
  label,
  value,
  tint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tint: string;
}) {
  // Large colorful icon + value; the metric name appears only on hover.
  return (
    <div className="group relative flex flex-col items-center gap-1 text-center">
      <span className={`rounded-xl border p-1 ${tint}`}>{icon}</span>
      <span className="whitespace-nowrap text-[10px] font-semibold tracking-tight text-slate-800">{value}</span>
      <span className="pointer-events-none absolute -top-6 left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100">
        {label}
      </span>
    </div>
  );
}

type ChangeBadge = { key: string; label: string; cls: string };

/** Up to two "what changed today" badges (from diff_changes.py's changed_today),
 * highest-signal first, for the image corner. */
function changeBadges(model: Model): ChangeBadge[] {
  const c = model.changed_today;
  if (!c) return [];
  const d = c.detail ?? {};
  const out: ChangeBadge[] = [];
  if (d.stock?.event === "back_in_stock")
    out.push({ key: "stock", label: "Back in stock", cls: "bg-emerald-600" });
  if (d.price?.direction === "drop")
    out.push({ key: "price", label: d.price.pct != null ? `↓ ${Math.abs(d.price.pct)}%` : "Price drop", cls: "bg-rose-600" });
  if (d.sale?.event === "started") out.push({ key: "sale", label: "Now on sale", cls: "bg-amber-500" });
  else if (d.sale?.event === "deepened") out.push({ key: "sale", label: "Bigger deal", cls: "bg-amber-500" });
  if (d.free_feature && d.free_feature.added.length)
    out.push({ key: "free", label: "New freebie", cls: "bg-violet-600" });
  return out.slice(0, 2);
}

function BikeCardImpl({ model }: { model: Model }) {
  const { has, toggle, isFull } = useCompare();
  const selected = has(model.id);
  const t = model.analysis?.specs_typed ?? {};
  const [units] = useUnits();
  // rider-height fit range (enveloped across all frame sizes), in the active unit
  const ftIn = (inch: number) => `${inToFtIn(inch).ft}'${inToFtIn(inch).in}"`;
  const riderFit =
    t.fit_height_min_in != null && t.fit_height_max_in != null
      ? units === "metric" && t.fit_height_min_mm != null && t.fit_height_max_mm != null
        ? `${Math.round(t.fit_height_min_mm / 10)}–${Math.round(t.fit_height_max_mm / 10)} cm`
        : `${ftIn(t.fit_height_min_in)}–${ftIn(t.fit_height_max_in)}`
      : null;
  // selection is shared with the detail page (and persists for the session);
  // a fresh visit defaults to the first in-stock colorway
  const [showSoldOut] = useShowSoldOut();
  const [color, setColor] = useColorSelection(
    model.id,
    model.colors?.length ?? 0,
    defaultColorIndex(model),
  );
  // when sold-out colors are hidden, never sit on one of them
  const sold = soldOutColors(model);
  const availCount = (model.colors ?? []).filter(
    (c) => !sold.has((c.name ?? "").toLowerCase()),
  ).length;
  const hiddenColors = !showSoldOut && availCount > 0 ? sold : undefined;
  useEffect(() => {
    if (hiddenColors && colorSoldOut(model, color)) setColor(defaultColorIndex(model));
  }, [hiddenColors, color, model, setColor]);
  const img = model.colors?.[color]?.image ?? primaryImage(model);

  // spec-tile numbers are shown without thousands separators ("1250", not "1,250")
  const tile = (n: number) => formatNumber(n, 0, false);
  // watts compacted to save room: 1000+ becomes "K" (1100 -> 1.1K, 1500 -> 1.5K,
  // 2000 -> 2K), trailing zeros trimmed; under 1000 shown as-is (750).
  const watt = (n: number) => (n >= 1000 ? `${+(n / 1000).toFixed(2)}K` : tile(n));

  const cPrices = colorPrices(model);
  const colorUp = upchargeText(cPrices, null, model.currency, color);

  // Free shipping sits on the price line; when on sale that line already carries
  // the strikethrough + discount badge, so it drops to its own line below.
  const onSale = !!model.pricing?.on_sale;
  const freeShipping = model.shipping_free === true || model.shipping_cost === 0;

  // Show whichever motor ratings the source page stated — nominal, peak, or
  // both — never a placeholder for the missing half.
  const hasNom = t.motor_w != null;
  const hasPeak = t.motor_peak_w != null;
  const motorLabel =
    hasNom && hasPeak ? "Motor (nominal/peak)" : hasPeak ? "Motor (peak)" : "Motor";
  // when both ratings are 1000W+, share one "kW" unit (1000/1500 -> "1/1.5 kW",
  // 1100/14000 -> "1.1/14 kW"); otherwise keep the per-value compaction in W.
  const kv = (n: number) => `${+(n / 1000).toFixed(2)}`;
  const bothKW = hasNom && hasPeak && t.motor_w! >= 1000 && t.motor_peak_w! >= 1000;
  const motorValue = bothKW
    ? `${kv(t.motor_w!)}/${kv(t.motor_peak_w!)} kW`
    : hasNom && hasPeak
      ? `${watt(t.motor_w!)}/${watt(t.motor_peak_w!)} W`
      : hasNom
        ? `${watt(t.motor_w!)} W`
        : hasPeak
          ? `${watt(t.motor_peak_w!)} W`
          : "—";

  // range shown as "low/high" when a span is stated, else the single figure
  const hasRange = t.range_mi != null;
  const hasRangeLo = t.range_min_mi != null;
  const rangeLabel = hasRangeLo ? "Range (low/high)" : "Range";
  const rangeValue =
    hasRange && hasRangeLo
      ? `${tile(t.range_min_mi!)}/${tile(t.range_mi!)} mi`
      : hasRange
        ? `${tile(t.range_mi!)} mi`
        : "—";

  return (
    // No overflow-hidden on the card root: hover tooltips (color names, spec
    // labels) must be able to escape the card bounds; the image wrapper rounds
    // and clips itself instead.
    <div className="card flex flex-col transition-shadow hover:shadow-md">
      <div className="relative">
        <Link to={`/bike/${encodeURIComponent(model.id)}`} className="block">
          <div className="aspect-[4/3] w-full overflow-hidden rounded-t-xl bg-slate-100">
            {img ? (
              <img src={img} alt={`${model.model} — ${model.colors?.[color]?.name ?? ""}`} loading="lazy" className="h-full w-full object-contain" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-slate-300">no image</div>
            )}
          </div>
        </Link>
        {/* color choice overlays the image's top-left corner */}
        {model.colors && model.colors.length > 0 && (
          <div className="absolute left-2 top-2 rounded-full bg-white/75 px-2 py-1.5 shadow-sm backdrop-blur-sm">
            <ColorSwatches
              colors={model.colors}
              selected={color}
              onSelect={setColor}
              size="h-4 w-4"
              prices={cPrices}
              currency={model.currency}
              showLabel={false}
              hidden={hiddenColors}
            />
          </div>
        )}
        {/* corner badges: an explicit "New" (site new-arrival tag) first, then
            up to one "what changed today" badge */}
        {(() => {
          const newBadge: ChangeBadge[] = model.is_new
            ? [{ key: "new", label: "New", cls: "bg-brand-600" }]
            : [];
          const badges = [...newBadge, ...changeBadges(model)].slice(0, 2);
          return badges.length > 0 ? (
            <div className="pointer-events-none absolute right-2 top-2 flex flex-col items-end gap-1">
              {badges.map((b) => (
                <span
                  key={b.key}
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold text-white shadow-sm ${b.cls}`}
                >
                  {b.label}
                </span>
              ))}
            </div>
          ) : null;
        })()}
        {/* current color, over the bottom middle of the image */}
        {model.colors?.[color]?.name && (
          <div className="pointer-events-none absolute bottom-2 left-1/2 max-w-[90%] -translate-x-1/2 truncate rounded-full bg-white/75 px-2.5 py-0.5 text-xs text-slate-600 shadow-sm backdrop-blur-sm">
            [{model.colors[color].name}
            {colorUp && <span className="font-semibold text-rose-600">{colorUp}</span>}]
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="space-y-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <div className="text-xs font-medium uppercase tracking-wide text-brand-600">{model.brand}</div>
            <AffiliateLink
              brand={model.brand}
              url={model.url}
              className="whitespace-nowrap text-xs font-medium text-brand-700 hover:underline"
            >
              View at {capitalize(model.brand)} →
            </AffiliateLink>
          </div>
          <Link to={`/bike/${encodeURIComponent(model.id)}`} className="line-clamp-2 font-semibold text-slate-900 hover:text-brand-700">
            {displayName(model)}
          </Link>
          {model.tier && (
            <span className="chip bg-amber-100 text-amber-800">{model.tier}</span>
          )}
          {/* TEMP: classification inspection — remove when done. Primary type
              first; extra categories follow. */}
          <div className="flex flex-wrap gap-1 border border-dashed border-fuchsia-300 bg-fuchsia-50 p-1">
            {(model.product_types ?? (model.product_type ? [model.product_type] : ["—"])).map((pt, i) => (
              <span
                key={pt}
                className={`chip ${i === 0 ? "bg-fuchsia-600 text-white" : "bg-fuchsia-100 text-fuchsia-800"}`}
              >
                {pt}
              </span>
            ))}
          </div>
        </div>

        <div className="space-y-0.5">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <Price
              model={model}
              price={variantPrice(model, model.colors?.[color]?.name)}
              soldOut={model.availability?.status === "sold_out" || colorSoldOut(model, color)}
            />
            {freeShipping && !onSale && (
              <span className="text-xs font-semibold text-emerald-700">Free Shipping</span>
            )}
          </div>
          {freeShipping && onSale && (
            <span className="text-xs font-semibold text-emerald-700">Free Shipping</span>
          )}
        </div>

        {/* TEMP: data-collection triage — lists expected typed fields missing on
            this model (from audit.py / model.data_audit). Remove when done. */}
        {model.data_audit && (
          <div className="rounded border border-dashed border-red-300 bg-red-50 p-1 text-[11px]">
            {model.data_audit.missing.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1">
                <span className="font-semibold text-red-700">⚠ missing:</span>
                {model.data_audit.missing.map((f) => (
                  <span key={f} className="chip bg-red-100 text-red-800">{f}</span>
                ))}
              </div>
            ) : (
              <span className="font-medium text-emerald-700">✓ audit complete</span>
            )}
          </div>
        )}

        {/* core spec tiles (+ a rider-height tile when the bike publishes a range) */}
        <div className={`grid gap-2 ${riderFit ? "grid-cols-3" : "grid-cols-5"}`}>
          <Spec
            icon={<BatteryIcon className="h-[26px] w-[26px]" />}
            tint="bg-emerald-50 border-emerald-200"
            label="Battery"
            value={t.battery_wh != null ? `${tile(t.battery_wh)} Wh` : "—"}
          />
          <Spec
            icon={<MotorIcon className="h-[26px] w-[26px]" />}
            tint="bg-amber-50 border-amber-200"
            label={motorLabel}
            value={motorValue}
          />
          <Spec
            icon={<TorqueIcon className="h-[26px] w-[26px]" />}
            tint="bg-rose-50 border-rose-200"
            label="Torque"
            value={t.torque_nm != null ? `${tile(t.torque_nm)} Nm` : "—"}
          />
          <Spec
            icon={<RangeIcon className="h-[26px] w-[26px]" />}
            tint="bg-sky-50 border-sky-200"
            label={rangeLabel}
            value={rangeValue}
          />
          <Spec
            icon={<WeightIcon className="h-[26px] w-[26px]" />}
            tint="bg-violet-50 border-violet-200"
            label="Weight"
            value={t.weight_lb != null ? `${tile(t.weight_lb)} lb` : "—"}
          />
          {riderFit && (
            <Spec
              icon={<RiderHeightIcon className="h-[26px] w-[26px]" />}
              tint="bg-teal-50 border-teal-200"
              label="Rider height"
              value={riderFit}
            />
          )}
        </div>

        {/* uncommon/premium features (regen braking, dropper post, ...) */}
        {model.analysis?.highlights?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {model.analysis.highlights.map((h) => (
              <span key={h} className="chip">{h}</span>
            ))}
          </div>
        )}

        {/* free accessories bundled with the bike */}
        {model.included_accessories && model.included_accessories.length > 0 && (
          <div
            className="line-clamp-1 text-xs text-slate-500"
            title={model.included_accessories.map((a) => a.name).join(", ")}
          >
            <span className="font-medium text-emerald-700">Includes:</span>{" "}
            {model.included_accessories.map((a) => a.name).join(" · ")}
          </div>
        )}

        <div className="mt-auto flex justify-center pt-1">
          <button
            type="button"
            onClick={() => toggle(model.id)}
            disabled={!selected && isFull}
            className={`${selected ? "btn-primary" : "btn-ghost"} !px-2.5 !py-1 !text-xs`}
            title={!selected && isFull ? "Compare list is full (max 4)" : undefined}
          >
            {selected ? "✓ Comparing" : "Compare"}
          </button>
        </div>
      </div>
    </div>
  );
}

// Cards are static for a given model; memoizing lets the grid skip re-rendering
// survivors when the result set changes (e.g. toggling a brand facet).
export const BikeCard = memo(BikeCardImpl);
