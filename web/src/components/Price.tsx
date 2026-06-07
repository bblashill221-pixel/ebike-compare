import type { Model } from "../types";
import { formatPrice } from "../format";

interface Props {
  model: Model;
  size?: "md" | "lg";
}

// Sale-aware price: current price (red when discounted) + struck-through regular
// price + a "-N%" badge. Falls back to a plain price when not on sale.
export function Price({ model, size = "md" }: Props) {
  const p = model.pricing;
  const price = p?.price ?? model.price ?? model.price_min;
  const onSale = !!p?.on_sale && p?.regular_price != null;
  const cls = size === "lg" ? "text-2xl" : "text-lg";
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span className={`${cls} font-bold ${onSale ? "text-rose-600" : "text-slate-900"}`}>
        {formatPrice(price, model.currency)}
      </span>
      {onSale && (
        <>
          <span className="text-sm text-slate-400 line-through">
            {formatPrice(p!.regular_price, model.currency)}
          </span>
          {p!.discount_pct != null && (
            <span className="chip bg-rose-100 font-semibold text-rose-700">
              -{p!.discount_pct}%
            </span>
          )}
        </>
      )}
    </span>
  );
}
