import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { ColorSwatches, upchargeText } from "../components/ColorSwatches";
import { useColorSelection, defaultColorIndex, colorSoldOut, soldOutColors } from "../colorSelection";
import { useShowSoldOut } from "../soldOut";
import { useCompare } from "../compare/CompareContext";
import { formatPrice, titleCase, colorChipStyle, fieldLabel } from "../format";
import { useUnits, inToFtIn } from "../units";
import { colorPrices, defaultDims, lowestPrice, variantPrice } from "../pricing";
import { VariantPicker } from "../components/VariantPicker";
import { Price } from "../components/Price";
import { ScorePanel } from "../components/ScorePanel";
import { SpecTable } from "../components/SpecTable";
import { DistributionPlot } from "../components/DistributionPlot";
import { AffiliateLink } from "../components/AffiliateLink";
import { displayName, primaryImage } from "../components/BikeCard";
import { BatteryIcon, MotorIcon, RangeIcon, RiderHeightIcon, TorqueIcon, WeightIcon } from "../components/icons";

const GROUP_ORDER = [
  "general_info",
  "ebike_system",
  "water_resistance",
  "frameset",
  "drivetrain",
  "brakes",
  "wheelset",
  "cockpit",
  "geometry",
  // NB included_accessories is deliberately not a spec group here — the
  // dedicated Accessories card below renders it (free first, then the brand's
  // paid add-ons with prices).
];

const PERCENTILE_FIELDS: {
  field: string;
  label: string;
  unit?: string;
  icon?: React.ReactNode;
}[] = [
  { field: "price", label: "Price", unit: "$" },
  { field: "battery_wh", label: "Battery", unit: " Wh", icon: <BatteryIcon /> },
  { field: "motor_w", label: "Motor", unit: " W", icon: <MotorIcon /> },
  { field: "torque_nm", label: "Torque", unit: " Nm", icon: <TorqueIcon /> },
  { field: "range_mi", label: "Range", unit: " mi", icon: <RangeIcon /> },
  { field: "weight_lb", label: "Weight", unit: " lb", icon: <WeightIcon /> },
];

// Per-frame-size geometry: normalize structures each per-size attribute as a
// {sizeLabel: value} map (e.g. {"17\"": "432mm", "19\"": "470mm"}); a single
// shared figure stays a string. Build one row per attribute, aligned to `sizes`.
function geometryRows(geo: Record<string, unknown>, sizes: string[]) {
  const rows: { label: string; vals: string[]; span: boolean }[] = [];
  for (const [k, v] of Object.entries(geo)) {
    const label = fieldLabel(k).label;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const dict = v as Record<string, unknown>;
      const vals = sizes.map((sz) => (dict[sz] == null ? "" : String(dict[sz])));
      if (vals.some(Boolean)) rows.push({ label, vals, span: false });
    } else if (typeof v === "string" && /\d/.test(v)) {
      rows.push({ label, vals: [v.trim()], span: true }); // shared across sizes
    }
  }
  return rows;
}

function geoTableHasRows(geo: Record<string, unknown>, sizes: string[]): boolean {
  return geometryRows(geo, sizes).length > 0;
}

function GeometryTable({ geo, sizes }: { geo: Record<string, unknown>; sizes: string[] }) {
  const rows = geometryRows(geo, sizes);
  if (!rows.length) return null;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs font-medium text-slate-400">
          <th className="w-2/5 py-1 pr-3" />
          {sizes.map((s) => (
            <th key={s} className="py-1 pr-3">{s}</th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {rows.map((r) => (
          <tr key={r.label} className="align-top">
            <th className="w-2/5 py-1.5 pr-3 text-left font-medium text-slate-500">{r.label}</th>
            {r.span ? (
              <td className="py-1.5 pr-3 text-slate-800" colSpan={sizes.length}>{r.vals[0]}</td>
            ) : (
              r.vals.map((val, i) => (
                <td key={i} className="py-1.5 pr-3 text-slate-800">{val}</td>
              ))
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function BikeDetail() {
  const { id } = useParams();
  const { byId, models, analysisStats, brandByName, status } = useData();
  const { has, toggle, isFull } = useCompare();
  const model = id ? byId.get(decodeURIComponent(id)) : undefined;
  // selection is shared with the browse cards (and persists for the session);
  // a fresh visit defaults to the first in-stock colorway
  const [showSoldOut] = useShowSoldOut();
  const [units] = useUnits();
  const [color, setColor] = useColorSelection(
    model?.id,
    model?.colors?.length ?? 0,
    model ? defaultColorIndex(model) : 0,
  );
  // hide sold-out colors when the "Sold out" filter is off (unless that would
  // leave nothing — a fully sold-out model keeps its swatches)
  const sold = model ? soldOutColors(model) : new Set<string>();
  const availCount = (model?.colors ?? []).filter(
    (c) => !sold.has((c.name ?? "").toLowerCase()),
  ).length;
  const hiddenColors = model && !showSoldOut && availCount > 0 ? sold : undefined;
  useEffect(() => {
    if (model && hiddenColors && colorSoldOut(model, color)) setColor(defaultColorIndex(model));
  }, [hiddenColors, color, model, setColor]);
  // non-color option selections (e.g. frame type); default to the cheapest config
  const [dims, setDims] = useState<Record<string, string>>({});
  // some brands list 100+ paid add-ons; collapsed by default
  const [allAccessories, setAllAccessories] = useState(false);
  useEffect(() => {
    setDims(model ? defaultDims(model) : {});
    // open at the top — without this the page inherits the browse grid's
    // scroll offset (Browse saves its own position and restores it on return)
    window.scrollTo(0, 0);
  }, [model?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (status === "loading") return <Center>Loading…</Center>;
  if (!model) {
    return (
      <Center>
        <div className="text-center">
          <p className="mb-3">That e-bike could not be found.</p>
          <Link to="/" className="btn-primary">Back to browse</Link>
        </div>
      </Center>
    );
  }

  const img = model.colors?.[color]?.image ?? primaryImage(model);
  const cPrices = colorPrices(model, dims);
  const colorUp = upchargeText(cPrices, lowestPrice(model), model.currency, color);
  const productTypes = model.product_types?.length
    ? model.product_types
    : model.product_type
      ? [model.product_type]
      : [];
  const selected = has(model.id);
  const siblings = model.family_id
    ? models.filter((x) => x.family_id === model.family_id && x.id !== model.id)
    : [];
  const t = model.analysis?.specs_typed ?? {};
  // manufacturer's recommended rider-height range, shown in the active unit
  const ftIn = (inch: number) => `${inToFtIn(inch).ft}'${inToFtIn(inch).in}"`;
  const riderFit =
    t.fit_height_min_in != null && t.fit_height_max_in != null
      ? units === "metric" && t.fit_height_min_mm != null && t.fit_height_max_mm != null
        ? `${Math.round(t.fit_height_min_mm / 10)}–${Math.round(t.fit_height_max_mm / 10)} cm`
        : `${ftIn(t.fit_height_min_in)} – ${ftIn(t.fit_height_max_in)}`
      : null;
  // multi-size models: each frame size with its rider-height range when the
  // brand publishes one (range null -> name-only fallback)
  const frameSizes =
    (model.frame_size_count ?? 0) > 1
      ? (model.frame_sizes ?? [])
          .filter((s): s is typeof s & { size: string } => !!s.size)
          .map((s) => ({
            size: s.size,
            range: s.height_min && s.height_max ? `${s.height_min}–${s.height_max}` : null,
          }))
      : [];
  // per-frame-size breakdown, shown indented under the rider-height entry
  const frameSizeBreakdown =
    frameSizes.length > 0 ? (
      <div>
        <div className="font-medium text-slate-600">Frame Sizes</div>
        <div className="flex flex-col gap-y-0.5 pl-3">
          {frameSizes.map((s) => (
            <div key={s.size} className="whitespace-nowrap">
              <span className="font-medium text-slate-600">{s.size}</span>
              {s.range ? ` ${s.range}` : ""}
            </div>
          ))}
        </div>
      </div>
    ) : null;
  const valueOf = (field: string) =>
    field === "price" ? model.price ?? model.price_min : (t[field] as number | undefined);

  const hasGroup = (g: string) => !!model.specs?.[g] && Object.keys(model.specs[g]).length > 0;
  // these sit under the image (left column) instead of the main spec flow
  const SIDE_GROUPS = ["general_info", "geometry"];
  // Rider height + frame-size labels live in Key Aspects (with the Frame Sizes
  // breakdown); drop their duplicate copies from Geometry so the cards don't
  // repeat them. Covers rider_height, user_height_range, approx height, inseam,
  // and bike_size/frame_size label rows.
  const isGeoDup = (k: string) =>
    (/rider|user|approx/i.test(k) && /height/i.test(k)) ||
    /height.?range|inseam/i.test(k) ||
    /^(bike|frame)_?sizes?$/i.test(k);
  const sideGroupData = (g: string) => {
    const src = model.specs?.[g] ?? {};
    if (g === "general_info") return riderFit ? { rider_height: riderFit, ...src } : src;
    if (g === "geometry")
      return Object.fromEntries(Object.entries(src).filter(([k]) => !isGeoDup(k)));
    return src;
  };
  const sideGroups = SIDE_GROUPS.filter((g) => Object.keys(sideGroupData(g)).length > 0);
  const groups = GROUP_ORDER.filter((g) => !SIDE_GROUPS.includes(g) && hasGroup(g));

  // Accessories: the bike's free/bundled items first, then the brand's paid
  // add-ons (deduped against the free list) cheapest first.
  const included = model.included_accessories ?? [];
  const includedNames = new Set(included.map((a) => a.name.toLowerCase()));
  // Model-family matching: an accessory named for ANOTHER of the brand's models
  // (e.g. "Roadster v3 Battery" on a Portola) is hidden; generic/global add-ons
  // (no model name) and this model's own are kept. Family tokens are the model
  // name minus brand/trim words (trailing digits stripped: "Racer1" -> "racer").
  const ACC_STOP = new Set([
    "turbo", "sworks", "works", "specialized", "ride1up", "magician", "the", "and",
    "with", "for", "sl", "comp", "pro", "expert", "evo", "igh", "alloy", "step",
    "through", "thru", "over", "frameset", "carbon", "ltd", "lite", "class", "belt",
    "cvt", "chain", "suspension", "ohlins", "coil", "gen", "edition", "dual", "single",
    "plus", "max", "series", "drt", "evo", "mini",
  ]);
  const famTokens = (name: string): Set<string> => {
    const out = new Set<string>();
    for (let t of (name || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").split(" ")) {
      t = t.replace(/\d+$/, "");
      if (t.length >= 3 && !ACC_STOP.has(t) && !/^\d+$/.test(t)) out.add(t);
    }
    return out;
  };
  const brandFamilies = new Set<string>();
  for (const m of models) {
    if (m.brand === model.brand) for (const t of famTokens(m.model)) brandFamilies.add(t);
  }
  const myFamilies = famTokens(model.model);
  // Some brands have product LINES that aren't catalog model names: Specialized's
  // "Globe" is its cargo sub-brand (the Haul line) and "Tero" is an eMTB line, so a
  // "Globe Passenger Seat" or "Tero Kickstand" is line-specific, not universal. Map
  // such line words to the catalog family they belong to (globe -> haul) so they're
  // hidden on, e.g., a Vado; an unmapped line (tero, not in the catalog) hides on all.
  const LINE_ALIASES: Record<string, Record<string, string>> = {
    specialized: { globe: "haul", tero: "tero" },
  };
  const aliases = LINE_ALIASES[model.brand] ?? {};
  const accFamilies = (name: string): string[] => {
    const fa = [...famTokens(name)].filter((t) => brandFamilies.has(t));
    const low = name.toLowerCase();
    for (const [tok, fam] of Object.entries(aliases)) {
      if (new RegExp(`\\b${tok}\\b`).test(low)) fa.push(fam);
    }
    return [...new Set(fa)];
  };
  const appliesToThisModel = (name: string): boolean => {
    const fa = accFamilies(name);
    // Batteries and replacement parts are inherently model-specific (a "Cafe Cruiser
    // Battery" / "500 Series Replacement Parts" is never universal) -> require a match
    // to THIS model's family; otherwise it's for another (often unlisted) model.
    const modelSpecific = /\bbatter/i.test(name) && !/charger/i.test(name)
      || /replacement\s+parts?/i.test(name);
    if (modelSpecific) return fa.some((t) => myFamilies.has(t));
    return fa.length === 0 || fa.some((t) => myFamilies.has(t));
  };
  const paidAccessories = (brandByName.get(model.brand)?.available_accessories ?? [])
    .filter((a) => !a.free && a.price != null && !includedNames.has(a.name.toLowerCase())
      && appliesToThisModel(a.name))
    .sort((a, b) => (a.price ?? 0) - (b.price ?? 0));

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <Link to="/" className="text-sm text-brand-600 hover:underline">← Back to browse</Link>

      <div className="mt-3 grid gap-6 lg:grid-cols-2">
        {/* no overflow-hidden on the card: the swatch hover tooltips must be
            able to escape; the image wrapper rounds and clips itself instead.
            The overlays anchor to this inner relative wrapper (which hugs the
            image), NOT the card — the grid stretches the card taller than the
            image, which would push a card-anchored pill below the photo. */}
        <div className="space-y-4">
        <div className="card border-slate-100">
          <div className="relative">
            <div className="aspect-[4/3] w-full overflow-hidden rounded-xl bg-slate-100">
              {img ? (
                <img
                  src={img}
                  alt={`${model.model} — ${model.colors?.[color]?.name ?? ""}`}
                  className="h-full w-full object-contain"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-slate-300">no image</div>
              )}
            </div>
            {/* color choice overlays the image's top-left corner, above the photo
                and inset so it never crosses the card border */}
            {model.colors && model.colors.length > 0 && (
              <div className="absolute left-3 top-3 z-10 rounded-full bg-white/75 px-2.5 py-2 shadow-sm backdrop-blur-sm">
                <ColorSwatches
                  colors={model.colors}
                  selected={color}
                  onSelect={setColor}
                  size="h-6 w-6"
                  prices={cPrices}
                  basePrice={lowestPrice(model)}
                  currency={model.currency}
                  showLabel={false}
                  hidden={hiddenColors}
                />
              </div>
            )}
            {/* current color, on top of the bottom middle of the image; when a hex
                is known the name is shown in that colour on a contrasting chip */}
            {model.colors?.[color]?.name && (() => {
              const chip = colorChipStyle(model.colors[color].hex);
              return (
                <div
                  className={`pointer-events-none absolute bottom-3 left-1/2 max-w-[90%] -translate-x-1/2 truncate rounded-full border px-3 py-1 text-sm shadow-sm ${chip ? "" : "border-slate-300 bg-white/75 text-slate-600 backdrop-blur-sm"}`}
                  style={chip ? { color: chip.color, borderColor: chip.color } : undefined}
                >
                  {model.colors[color].name}
                  {colorUp && <span className="font-semibold text-rose-600">{colorUp}</span>}
                </div>
              );
            })()}
          </div>
        </div>
        {sideGroups.map((g) => {
          const isGeneral = g === "general_info";
          // "Key Aspects" leads with the rider-height fit range; Geometry has the
          // duplicate rider-height stripped (see sideGroupData)
          const groupData = sideGroupData(g);
          // Geometry usually differs per frame size; render it as a per-size table
          // (attribute rows × size columns) when the bike has named sizes.
          const sizeLabels = frameSizes.map((s) => s.size);
          const geoTable =
            g === "geometry" && sizeLabels.length > 1 ? (
              <GeometryTable geo={groupData} sizes={sizeLabels} />
            ) : null;
          if (g === "geometry" && sizeLabels.length > 1 && !geoTableHasRows(groupData, sizeLabels))
            return null;
          return (
            <div key={g} className="card p-4">
              <h2 className="mb-2 font-bold text-slate-800">
                {isGeneral ? "Key Aspects" : titleCase(g)}
              </h2>
              {geoTable ?? (
                <SpecTable
                  group={groupData}
                  emphasize
                  subRows={isGeneral && frameSizeBreakdown ? { rider_height: frameSizeBreakdown } : undefined}
                />
              )}
            </div>
          );
        })}
        </div>

        <div className="space-y-4">
          <div>
            <div className="text-sm font-medium uppercase tracking-wide text-brand-600">{model.brand}</div>
            <h1 className="text-2xl font-bold text-slate-900">
              {displayName(model)}
              {model.tier && (
                <span className="chip ml-2 bg-amber-100 align-middle text-amber-800">{model.tier}</span>
              )}
            </h1>
            <VariantPicker
              model={model}
              colorName={model.colors?.[color]?.name}
              dims={dims}
              onChange={setDims}
              basePrice={lowestPrice(model)}
            />
            {productTypes.length > 0 && (
              <div className="mt-1.5 text-sm text-slate-500">{productTypes.join(" · ")}</div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Price
              model={model}
              size="lg"
              price={variantPrice(model, model.colors?.[color]?.name, dims)}
              soldOut={model.availability?.status === "sold_out" || colorSoldOut(model, color)}
            />
            {model.warranty && <span className="chip">{model.warranty}</span>}
            {model.shipping_free && <span className="chip bg-emerald-50 text-emerald-700">Free shipping</span>}
          </div>

          {/* frame sizes show even when the brand publishes no rider-height
              range (e.g. some Cannondale dealer-only models) */}
          {(riderFit || frameSizes.length > 0) && (
            <div className="text-sm text-slate-600">
              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                <RiderHeightIcon className="h-5 w-5" />
                {riderFit ? (
                  <>
                    <span className="font-medium text-slate-700">Fits riders</span> {riderFit}
                  </>
                ) : (
                  <>
                    <span className="font-medium text-slate-700">Frame sizes</span>{" "}
                    <span className="text-slate-400">
                      {frameSizes.map((s) => s.size).join(", ")}
                    </span>
                  </>
                )}
              </div>
            </div>
          )}

          {/* partial stock: list the option values that are unavailable */}
          {model.availability?.status === "in_stock" &&
            Object.keys(model.availability.sold_out_options).length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                <span className="font-semibold">Some options are sold out:</span>{" "}
                {Object.entries(model.availability.sold_out_options)
                  .map(([axis, vals]) => `${axis} — ${vals.join(", ")}`)
                  .join("; ")}
              </div>
            )}

          <div className="flex flex-wrap gap-2">
            <AffiliateLink brand={model.brand} url={model.url} className="btn-primary">
              View at {titleCase(model.brand)} →
            </AffiliateLink>
            <button
              type="button"
              onClick={() => toggle(model.id)}
              disabled={!selected && isFull}
              className={selected ? "btn-primary" : "btn-ghost"}
            >
              {selected ? "✓ Comparing" : "Add to compare"}
            </button>
          </div>

          {siblings.length > 0 && (
            <div className="card p-4">
              <h3 className="mb-2 font-semibold text-slate-800">Other versions of this bike</h3>
              <ul className="space-y-1.5">
                {siblings.map((s) => (
                  <li key={s.id} className="flex items-baseline justify-between gap-3 text-sm">
                    <Link
                      to={`/bike/${encodeURIComponent(s.id)}`}
                      className="font-medium text-brand-700 hover:underline"
                    >
                      {s.tier ?? s.model}
                    </Link>
                    <span className="text-slate-500">{formatPrice(s.price ?? s.price_min, s.currency)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="card p-4">
            <ScorePanel analysis={model.analysis} />
          </div>
        </div>
      </div>

      {/* percentile context */}
      <section className="mt-6 card p-4">
        <h2 className="mb-3 font-semibold text-slate-800">How it compares to the fleet</h2>
        <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          {PERCENTILE_FIELDS.map(({ field, label, unit, icon }) => {
            let stat = analysisStats[field];
            let v = valueOf(field);
            let u = unit;
            if (!stat) return null;
            // show the unit-dependent fields in the selected system (scaling the
            // value and the whole distribution keeps the percentile position).
            if (units === "metric") {
              const conv = field === "range_mi" ? 1.60934 : field === "weight_lb" ? 0.453592 : null;
              if (conv) {
                const sc = (n: number) => n * conv;
                stat = { ...stat, min: sc(stat.min), p10: sc(stat.p10), p50: sc(stat.p50), p90: sc(stat.p90), max: sc(stat.max) };
                if (v != null) v = Math.round(sc(v));
                u = field === "range_mi" ? " km" : " kg";
              }
            }
            return (
              <div key={field}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="flex items-center gap-1.5 font-medium text-slate-700">
                    {icon}
                    {label}
                  </span>
                  <span className="text-slate-500">
                    {v == null ? "—" : u === "$" ? `$${v}` : `${v}${u ?? ""}`}
                  </span>
                </div>
                <DistributionPlot stat={stat} value={v} unit={u} />
              </div>
            );
          })}
        </div>
      </section>

      {/* grouped specs */}
      <section className="mt-6 grid gap-4 md:grid-cols-2">
        {groups.map((g) => (
          <div key={g} className="card p-4">
            <h2 className="mb-2 font-bold text-slate-800">{titleCase(g)}</h2>
            <SpecTable group={model.specs[g]} emphasize hideCaptured />
          </div>
        ))}

        {(included.length > 0 || paidAccessories.length > 0) && (
          <div className="card p-4">
            <h2 className="mb-2 font-semibold text-slate-800">Accessories</h2>
            <ul className="space-y-1.5 text-sm">
              {included.map((a) => (
                <li key={`inc-${a.name}`} className="flex items-baseline justify-between gap-3">
                  <span className="text-slate-700">{a.name}</span>
                  <span className="shrink-0 font-medium text-emerald-600">Included</span>
                </li>
              ))}
              {(allAccessories ? paidAccessories : paidAccessories.slice(0, 10)).map((a, i) => (
                <li key={`add-${a.name}-${i}`} className="flex items-baseline justify-between gap-3">
                  {a.url ? (
                    <AffiliateLink brand={model.brand} url={a.url} showBadge={false} className="truncate text-brand-600 underline decoration-brand-300 underline-offset-2 hover:text-brand-700 hover:decoration-brand-600">
                      {a.name}
                    </AffiliateLink>
                  ) : (
                    <span className="truncate text-slate-700">{a.name}</span>
                  )}
                  {a.on_sale && a.regular_price != null && a.price != null ? (
                    <span className="inline-flex shrink-0 items-baseline gap-1.5 tabular-nums">
                      <span className="text-slate-400 line-through">{formatPrice(a.regular_price, model.currency)}</span>
                      <span className="font-medium text-rose-600">{formatPrice(a.price, model.currency)}</span>
                      <span className="text-xs font-semibold text-rose-700">
                        -{Math.round(((a.regular_price - a.price) / a.regular_price) * 100)}%
                      </span>
                    </span>
                  ) : (
                    <span className="shrink-0 tabular-nums text-slate-500">{formatPrice(a.price, model.currency)}</span>
                  )}
                </li>
              ))}
            </ul>
            {paidAccessories.length > 10 && (
              <button
                type="button"
                onClick={() => setAllAccessories(!allAccessories)}
                className="mt-2 text-xs text-brand-600 hover:underline"
              >
                {allAccessories ? "Show less" : `Show all (${paidAccessories.length})`}
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[50vh] items-center justify-center text-slate-500">{children}</div>;
}
