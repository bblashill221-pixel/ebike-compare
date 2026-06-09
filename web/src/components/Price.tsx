import type { Model } from "../types";
import { formatPrice } from "../format";

interface Props {
  model: Model;
  size?: "md" | "lg";
  /** Selected-variant price (color/frame); overrides the model's base price. */
  price?: number | null;
  /** Fully out of stock — show a "Sold out" chip in place of any sale chip. */
  soldOut?: boolean;
}

// Sale-aware price: current price (red when discounted) with "Save $N (-N%)" on
// the same line; the original price is not shown. Falls back to a plain price
// when not on sale. When a variant price is passed, the (implied) regular price
// shifts by the same upcharge so the savings stay correct. When sold out, a
// "Sold out" chip takes the chip slot and the discount figures are suppressed.
export function Price({ model, size = "md", price: override, soldOut = false }: Props) {
  const p = model.pricing;
  const base = p?.price ?? model.price ?? model.price_min;
  const price = override ?? base;
  const onSale = !!p?.on_sale && p?.regular_price != null;
  const delta = price != null && base != null ? price - base : 0;
  const regular = onSale ? p!.regular_price! + delta : null;
  const saved = onSale
    ? delta === 0
      ? p!.discount_amount ?? (price != null && regular != null ? regular - price : null)
      : price != null && regular != null
        ? regular - price
        : null
    : null;
  const pct = onSale
    ? delta === 0
      ? p!.discount_pct
      : saved != null && regular
        ? Math.round((saved / regular) * 100)
        : null
    : null;
  const cls = size === "lg" ? "text-2xl" : "text-lg";
  return (
    <span className="inline-flex flex-nowrap items-baseline gap-x-2 whitespace-nowrap">
      <span className={`${cls} font-bold ${onSale ? "text-rose-600" : "text-slate-900"}`}>
        {formatPrice(price, model.currency)}
      </span>
      {soldOut ? (
        <span className="chip bg-slate-800 font-semibold text-white">Sold out</span>
      ) : (
        onSale &&
        (saved != null || pct != null) && (
          <span className="chip bg-rose-100 font-semibold text-rose-700">
            {saved != null && `Save ${formatPrice(saved, model.currency)}`}
            {saved != null && pct != null && " "}
            {pct != null && `(-${pct}%)`}
          </span>
        )
      )}
    </span>
  );
}
