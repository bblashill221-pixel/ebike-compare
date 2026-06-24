import { memo, useEffect, useRef, useState } from "react";
import { useColorSelection, defaultColorIndex, colorSoldOut, soldOutColors } from "../colorSelection";
import { useShowSoldOut } from "../soldOut";
import { Link } from "react-router-dom";
import type { Model } from "../types";
import { capitalize, formatNumber, colorChipStyle, formatPrice } from "../format";
import { colorPrices, variantPrice } from "../pricing";
import { useCompare } from "../compare/CompareContext";
import { Price } from "./Price";
import { AffiliateLink } from "./AffiliateLink";
import { ColorSwatches, upchargeText } from "./ColorSwatches";
import { BatteryIcon, MotorIcon, PayloadIcon, RangeIcon, RiderHeightIcon, SensorIcon, SpeedIcon, TorqueIcon, WeightIcon, CheckIcon, BuildingIcon } from "./icons";
import { HighlightsList } from "./HighlightsList";
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
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tint?: string; // accepted for call-site compatibility; tiles are now uniform neutral
}) {
  // Neutral tile, uniform brand-blue icon (the descendant override beats each icon's
  // own colour class), value below; the metric name appears only on hover.
  return (
    <div className="group relative flex flex-col items-center gap-0.5 rounded-lg border border-slate-200 py-2 text-center">
      <span className="[&_*]:!text-brand-600">{icon}</span>
      <span className="whitespace-nowrap text-[10px] font-semibold tracking-tight text-slate-800">{value}</span>
      <span className="pointer-events-none absolute -top-6 left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100">
        {label}
      </span>
    </div>
  );
}

// Small icon for a product-type pill: a building for commuter/urban/hybrid types,
// else a tyre-style ring (covers Fat Tire and the rest) in the pill's own colour.
function typeIcon(pt: string, className: string) {
  if (/commut|urban|hybrid|fitness/i.test(pt)) return <BuildingIcon className={className} />;
  return <span className={`inline-block rounded-full border-[2.5px] border-current ${className}`} aria-hidden />;
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

function BikeCardImpl({ model }: { model: Model; selectedTypes?: string[] }) {
  const { has, toggle, isFull } = useCompare();
  const selected = has(model.id);
  // the bundled-accessory list is clamped to 2 lines by default (CSS "…"); clicking expands it
  const [showIncludes, setShowIncludes] = useState(false);
  // the click-to-expand affordance only appears when the clamped list actually overflows
  const incRef = useRef<HTMLDivElement>(null);
  const [incTruncated, setIncTruncated] = useState(false);
  useEffect(() => {
    const el = incRef.current;
    if (!el) return;
    const measure = () => {
      if (showIncludes) return; // only meaningful while the list is clamped
      setIncTruncated(el.scrollHeight > el.clientHeight + 1);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [showIncludes, model.included_accessories]);
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

  // Imperial/metric tiles follow the selected unit system — show ONLY that unit.
  const metric = units === "metric";
  const dist = (n: number) => (metric ? `${tile(n * 1.60934)} km` : `${tile(n)} mi`);
  const spd = (n: number) => (metric ? `${tile(n * 1.60934)} km/h` : `${tile(n)} mph`);
  const wt = (n: number) => (metric ? `${tile(n * 0.453592)} kg` : `${tile(n)} lb`);

  const cPrices = colorPrices(model);
  const colorUp = upchargeText(cPrices, null, model.currency, color);

  // Shipping always gets its own line below the price (an empty line is reserved when
  // it's unknown) so the price block is a uniform height across all cards: free shipping
  // shows in emerald, a known paid cost in muted slate, an unknown cost stays blank.
  const freeShipping = model.shipping_free === true || model.shipping_cost === 0;
  const shippingCost =
    !freeShipping && typeof model.shipping_cost === "number" && model.shipping_cost > 0
      ? model.shipping_cost
      : null;

  // Show whichever motor ratings the source page stated — nominal, peak, or
  // both — never a placeholder for the missing half.
  const hasNom = t.motor_w != null;
  const hasPeak = t.motor_peak_w != null;
  const motorLabel =
    hasNom && hasPeak ? "Motor (nominal/peak)" : hasPeak ? "Motor (peak)" : "Motor";
  // full wattage, no thousands separators (e.g. "750/1000 W", "1500 W")
  const motorValue =
    hasNom && hasPeak
      ? `${tile(t.motor_w!)}/${tile(t.motor_peak_w!)} W`
      : hasNom
        ? `${tile(t.motor_w!)} W`
        : hasPeak
          ? `${tile(t.motor_peak_w!)} W`
          : "—";

  // range shown as "low/high" when a span is stated, else the single figure
  const hasRange = t.range_mi != null;
  const hasRangeLo = t.range_min_mi != null;
  const rangeLabel = hasRangeLo ? "Range (low/high)" : "Range";
  const rangeValue =
    hasRange && hasRangeLo
      ? metric
        ? `${tile(t.range_min_mi! * 1.60934)}/${tile(t.range_mi! * 1.60934)} km`
        : `${tile(t.range_min_mi!)}/${tile(t.range_mi!)} mi`
      : hasRange
        ? dist(t.range_mi!)
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
        {/* current color, over the bottom middle of the image; when a hex is known
            the name is shown in that colour on a contrasting (black/white) chip */}
        {model.colors?.[color]?.name && (() => {
          const chip = colorChipStyle(model.colors[color].hex);
          return (
            <div
              className={`pointer-events-none absolute bottom-2 left-1/2 max-w-[90%] -translate-x-1/2 truncate rounded-full border px-2.5 py-0.5 text-xs shadow-sm ${chip ? "" : "border-slate-300 bg-white/75 text-slate-600 backdrop-blur-sm"}`}
              style={chip ? { color: chip.color, borderColor: chip.color } : undefined}
            >
              {model.colors[color].name}
              {colorUp && <span className="font-semibold text-rose-600">{colorUp}</span>}
            </div>
          );
        })()}
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
          {/* Directly under the name: the eBike type pill, then the Step-Thru/Step-Over
              frame-style option, then any trim/tier. */}
          <div className="flex flex-wrap items-center gap-1.5">
            {(() => {
              const allTypes = model.product_types ?? (model.product_type ? [model.product_type] : []);
              // always show the bike's PRIMARY type (its identity), not whatever type
              // happens to match the active filter — a Cargo bike stays "Cargo" even
              // when browsing the Commuter filter.
              const shown = model.product_type ?? allTypes[0];
              if (!shown) return null;
              return (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-100 px-2.5 py-1 text-xs font-medium text-violet-700">
                  {typeIcon(shown, "h-3.5 w-3.5")}
                  {shown}
                </span>
              );
            })()}
            {model.frame_style && (
              <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                {model.frame_style}
              </span>
            )}
            {model.tier && (
              <span className="chip bg-amber-100 text-amber-800">{model.tier}</span>
            )}
          </div>
        </div>

        <div className="space-y-0.5">
          <Price
            model={model}
            price={variantPrice(model, model.colors?.[color]?.name)}
            soldOut={model.availability?.status === "sold_out" || colorSoldOut(model, color)}
          />
          {/* shipping on the line after the price; a reserved blank line keeps card heights aligned */}
          {freeShipping ? (
            <div className="text-xs font-semibold text-emerald-700">Free Shipping</div>
          ) : shippingCost != null ? (
            <div className="text-xs font-semibold text-slate-500">
              +{formatPrice(shippingCost, model.currency)} shipping
            </div>
          ) : (
            <div className="text-xs font-semibold text-emerald-700">&nbsp;</div>
          )}
        </div>

        {/* TEMP: data-collection triage — lists expected typed fields missing on
            this model (from audit.py / model.data_audit). Hidden when the audit is
            complete (nothing missing). Remove when done. */}
        {model.data_audit && model.data_audit.missing.length > 0 && (
          <div className="rounded border border-dashed border-red-300 bg-red-50 p-1 text-[11px]">
            <div className="flex flex-wrap items-center gap-1">
              <span className="font-semibold text-red-700">⚠ missing:</span>
              {model.data_audit.missing.map((f) => (
                <span key={f} className="chip bg-red-100 text-red-800">{f}</span>
              ))}
            </div>
          </div>
        )}

        {/* spec tiles (3-col grid), always shown ("—" when unknown) */}
        <div className="grid grid-cols-3 gap-1">
          <Spec
            icon={<BatteryIcon className="h-[28px] w-[28px]" />}
            tint="bg-emerald-50 border-emerald-200"
            label="Battery"
            value={t.battery_wh != null ? `${tile(t.battery_wh)} Wh` : "—"}
          />
          <Spec
            icon={<MotorIcon className="h-[28px] w-[28px]" />}
            tint="bg-amber-50 border-amber-200"
            label={motorLabel}
            value={motorValue}
          />
          <Spec
            icon={<TorqueIcon className="h-[28px] w-[28px]" />}
            tint="bg-rose-50 border-rose-200"
            label="Torque"
            value={t.torque_nm != null ? `${tile(t.torque_nm)} Nm` : "—"}
          />
          <Spec
            icon={<SpeedIcon className="h-[28px] w-[28px]" />}
            tint="bg-blue-50 border-blue-200"
            label="Top speed"
            value={t.max_speed_mph != null ? spd(t.max_speed_mph) : "—"}
          />
          <Spec
            icon={<RangeIcon className="h-[28px] w-[28px]" />}
            tint="bg-sky-50 border-sky-200"
            label={rangeLabel}
            value={rangeValue}
          />
          <Spec
            icon={<WeightIcon className="h-[28px] w-[28px]" />}
            tint="bg-violet-50 border-violet-200"
            label="Weight"
            value={t.weight_lb != null ? wt(t.weight_lb) : "—"}
          />
          <Spec
            icon={<RiderHeightIcon className="h-[28px] w-[28px]" />}
            tint="bg-teal-50 border-teal-200"
            label="Height Range"
            value={riderFit ?? "—"}
          />
          <Spec
            icon={<PayloadIcon className="h-[28px] w-[28px]" />}
            tint="bg-orange-50 border-orange-200"
            label="Max Payload"
            value={t.max_load_lb != null ? wt(t.max_load_lb) : "—"}
          />
          <Spec
            icon={<SensorIcon type={t.sensor_type} className="h-[28px] w-[28px]" />}
            tint="bg-slate-50 border-slate-200"
            label="Sensor Type"
            value={
              t.sensor_type === "torque + cadence" ? "Both"
                : t.sensor_type === "torque" ? "Torque"
                : t.sensor_type === "cadence" ? "Cadence"
                : "—"
            }
          />
        </div>

        {/* Highlights: the bike's standouts (top-quartile specs as "label: value" +
            uncommon equipment), star header — shared with the detail page */}
        <HighlightsList standouts={model.analysis?.standouts} />

        {/* Includes: bundled accessories — green-check "Includes:" header on its own
            line, with the accessory list on the line below (mirrors Highlights) */}
        {model.included_accessories && model.included_accessories.length > 0 && (
          <div>
            <div className="mb-0.5 flex items-center gap-1.5">
              <span className="[&_*]:!text-emerald-600"><CheckIcon className="h-3.5 w-3.5" /></span>
              <span className="text-xs font-semibold text-emerald-700">Includes:</span>
            </div>
            <div
              ref={incRef}
              onClick={incTruncated ? () => setShowIncludes((v) => !v) : undefined}
              className={`text-[11px] leading-snug text-slate-600 ${incTruncated ? "cursor-pointer" : ""} ${showIncludes ? "" : "line-clamp-2"}`}
              title={incTruncated ? (showIncludes ? "Show less" : "Show all") : undefined}
            >
              {model.included_accessories.map((a) => a.name).join("  ·  ")}
            </div>
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
