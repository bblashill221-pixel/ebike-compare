import type { CSSProperties } from "react";
import type { ColorOption } from "../types";

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
}

// Color/image circles shown right after the model name. The selected color gets an
// outer ring; hovering reveals the color name. Selecting drives the displayed photo.
export function ColorSwatches({ colors, selected, onSelect, size = "h-5 w-5" }: Props) {
  if (!colors?.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {colors.map((c, i) => (
        <button
          key={`${c.name}-${i}`}
          type="button"
          onClick={() => onSelect(i)}
          aria-label={`Color: ${c.name}`}
          aria-pressed={i === selected}
          className={`group relative rounded-full transition-shadow ${
            i === selected
              ? "ring-2 ring-brand-600 ring-offset-2"
              : "ring-1 ring-slate-300 hover:ring-slate-400"
          }`}
        >
          <span className={`block ${size} rounded-full`} style={swatchStyle(c)} />
          <span className="pointer-events-none absolute -top-7 left-1/2 z-20 -translate-x-1/2 whitespace-nowrap rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100">
            {c.name}
          </span>
        </button>
      ))}
    </div>
  );
}
