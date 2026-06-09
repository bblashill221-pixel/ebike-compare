import type { CSSProperties } from "react";
import type { ColorOption } from "../types";
import { formatPrice } from "../format";

function swatchStyle(c: ColorOption): CSSProperties {
  if (c.hex) return { background: c.hex };
  const img = c.swatch_image || c.image;
  if (img) {
    return { backgroundImage: `url(${img})`, backgroundSize: "cover", backgroundPosition: "center" };
  }
  return { background: "linear-gradient(135deg,#e2e8f0,#94a3b8)" };
}

interface Props {
  colors: ColorOption[];
  selected: number;
  onSelect: (index: number) => void;
  size?: string;
  /** Per-color price aligned with `colors`; shows "+$N" when colors differ in price. */
  prices?: (number | null)[];
  /** Baseline for the "+$N" deltas; defaults to the cheapest entry in `prices`. */
  basePrice?: number | null;
  currency?: string;
  /** Render the "[selected color]" text after the swatches (callers that place
   *  the label elsewhere — e.g. under the card image — pass false). */
  showLabel?: boolean;
  /** Lowercased color names to omit from the swatch row (e.g. sold-out colors
   *  hidden when "Sold out" is filtered off). Indices are unchanged. */
  hidden?: Set<string>;
}

/** "+$N" upcharge of color `i` over the cheapest colorway, or "". */
export function upchargeText(
  prices: (number | null)[] | undefined,
  basePrice: number | null | undefined,
  currency: string | undefined,
  i: number,
): string {
  const known = (prices ?? []).filter((p): p is number => p != null);
  const base = basePrice ?? (known.length && new Set(known).size > 1 ? Math.min(...known) : null);
  const p = prices?.[i];
  if (base == null || p == null || p <= base) return "";
  return ` +${formatPrice(p - base, currency)}`;
}

// Color/image circles shown right after the model name. The selected color gets an
// outer ring; hovering reveals the color name. Selecting drives the displayed photo.
// When colorways are priced differently, the upcharge over the cheapest color is
// shown next to the name ("+$100").
export function ColorSwatches({ colors, selected, onSelect, size = "h-5 w-5", prices, basePrice, currency, showLabel = true, hidden }: Props) {
  if (!colors?.length) return null;
  const upcharge = (i: number): string => upchargeText(prices, basePrice, currency, i);
  return (
    <div className="flex flex-nowrap items-center gap-2">
      {colors.map((c, i) =>
        hidden?.has((c.name ?? "").toLowerCase()) ? null : (
        <button
          key={`${c.name}-${i}`}
          type="button"
          onClick={() => onSelect(i)}
          aria-label={`Color: ${c.name}${upcharge(i)}`}
          aria-pressed={i === selected}
          className={`group relative rounded-full transition-shadow ${
            i === selected
              ? "ring-2 ring-brand-600 ring-offset-2"
              : "ring-1 ring-slate-300 hover:ring-slate-400"
          }`}
        >
          <span className={`block ${size} rounded-full`} style={swatchStyle(c)} />
          <span className="pointer-events-none absolute -top-7 left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100">
            {c.name}
            {upcharge(i)}
          </span>
        </button>
        ),
      )}
      {showLabel && colors[selected]?.name && (
        <span className="truncate text-xs text-slate-500">
          [{colors[selected].name}
          {upcharge(selected) && <span className="font-semibold text-rose-600">{upcharge(selected)}</span>}]
        </span>
      )}
    </div>
  );
}
