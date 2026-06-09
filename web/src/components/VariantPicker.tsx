import type { Model } from "../types";
import { variantDims, variantPrice } from "../pricing";
import { formatPrice } from "../format";

interface Props {
  model: Model;
  /** Currently selected color name; prices are computed within it. */
  colorName?: string;
  dims: Record<string, string>;
  onChange: (dims: Record<string, string>) => void;
  /** Baseline (the model's lowest price); chips show their upcharge over it. */
  basePrice: number | null;
}

// Selector chips for non-color purchase options that carry their own price —
// e.g. Prodigy V2 step-through vs step-over frames. Each chip shows its
// upcharge over the model's lowest price, given the selected color.
export function VariantPicker({ model, colorName, dims, onChange, basePrice }: Props) {
  const dimensions = variantDims(model);
  if (!dimensions.length) return null;
  return (
    <div className="mt-2 space-y-2">
      {dimensions.map((d) => (
        <div key={d.key} className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">{d.label}</span>
          {d.values.map((v) => {
            const selected = dims[d.key] === v;
            const p = variantPrice(model, colorName, { ...dims, [d.key]: v });
            const delta = p != null && basePrice != null && p > basePrice ? p - basePrice : null;
            return (
              <button
                key={v}
                type="button"
                onClick={() => onChange({ ...dims, [d.key]: v })}
                aria-pressed={selected}
                className={`chip transition-colors ${
                  selected
                    ? "bg-brand-600 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {v}
                {delta != null && (
                  <span className={`ml-1 font-semibold ${selected ? "text-rose-200" : "text-rose-600"}`}>
                    +{formatPrice(delta, model.currency)}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
