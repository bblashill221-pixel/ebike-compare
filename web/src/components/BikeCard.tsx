import { Link } from "react-router-dom";
import type { Model } from "../types";
import { formatPrice, formatNumber } from "../format";
import { useCompare } from "../compare/CompareContext";
import { AffiliateLink } from "./AffiliateLink";
import {
  BatteryIcon,
  GearsIcon,
  MotorIcon,
  RangeIcon,
  TorqueIcon,
  WeightIcon,
} from "./icons";

export function primaryImage(m: Model): string | null {
  return m.colors?.find((c) => c.image)?.image ?? null;
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
      <span className={`rounded-xl p-1.5 ${tint}`}>{icon}</span>
      <span className="text-sm font-semibold text-slate-800">{value}</span>
      <span className="pointer-events-none absolute -top-6 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100">
        {label}
      </span>
    </div>
  );
}

export function BikeCard({ model }: { model: Model }) {
  const { has, toggle, isFull } = useCompare();
  const selected = has(model.id);
  const t = model.analysis?.specs_typed ?? {};
  const img = primaryImage(model);
  const price = model.price ?? model.price_min;
  const onSale = model.pricing?.on_sale;

  return (
    <div className="card flex flex-col overflow-hidden transition-shadow hover:shadow-md">
      <Link to={`/bike/${encodeURIComponent(model.id)}`} className="block">
        <div className="aspect-[4/3] w-full overflow-hidden bg-slate-100">
          {img ? (
            <img src={img} alt={model.model} loading="lazy" className="h-full w-full object-contain" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-slate-300">no image</div>
          )}
        </div>
      </Link>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-brand-600">{model.brand}</div>
          <Link to={`/bike/${encodeURIComponent(model.id)}`} className="line-clamp-2 font-semibold text-slate-900 hover:text-brand-700">
            {model.model}
          </Link>
        </div>

        <div className="flex items-baseline gap-2">
          <span className="text-lg font-bold text-slate-900">{formatPrice(price, model.currency)}</span>
          {onSale && <span className="chip bg-rose-100 text-rose-700">On sale</span>}
        </div>

        <div className="grid grid-cols-3 gap-2">
          {t.battery_wh != null && (
            <Spec icon={<BatteryIcon className="h-9 w-9" />} tint="bg-emerald-50" label="Battery" value={`${formatNumber(t.battery_wh)} Wh`} />
          )}
          {t.motor_w != null && (
            <Spec icon={<MotorIcon className="h-9 w-9" />} tint="bg-amber-50" label="Motor" value={`${formatNumber(t.motor_w)} W`} />
          )}
          {t.range_mi != null && (
            <Spec icon={<RangeIcon className="h-9 w-9" />} tint="bg-sky-50" label="Range" value={`${formatNumber(t.range_mi)} mi`} />
          )}
          {t.torque_nm != null && (
            <Spec icon={<TorqueIcon className="h-9 w-9" />} tint="bg-rose-50" label="Torque" value={`${formatNumber(t.torque_nm)} Nm`} />
          )}
          {t.weight_lb != null && (
            <Spec icon={<WeightIcon className="h-9 w-9" />} tint="bg-violet-50" label="Weight" value={`${formatNumber(t.weight_lb)} lb`} />
          )}
          {t.gears != null && (
            <Spec icon={<GearsIcon className="h-9 w-9" />} tint="bg-indigo-50" label="Gears" value={`${formatNumber(t.gears)}`} />
          )}
        </div>

        {model.analysis?.highlights?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {model.analysis.highlights.slice(0, 3).map((h) => (
              <span key={h} className="chip">{h}</span>
            ))}
          </div>
        )}

        <div className="mt-auto flex items-center justify-between gap-2 pt-1">
          <button
            type="button"
            onClick={() => toggle(model.id)}
            disabled={!selected && isFull}
            className={selected ? "btn-primary" : "btn-ghost"}
            title={!selected && isFull ? "Compare list is full (max 4)" : undefined}
          >
            {selected ? "✓ Comparing" : "Compare"}
          </button>
          <AffiliateLink
            brand={model.brand}
            url={model.url}
            className="text-sm font-medium text-brand-700 hover:underline"
          >
            View at {model.brand} →
          </AffiliateLink>
        </div>
      </div>
    </div>
  );
}
