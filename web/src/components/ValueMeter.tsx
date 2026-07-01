// Value meter pips — merged into the type badge on the card. 4 pips, filled = value level
// (Exceptional ●●●● › Great ●●●○ › Good ●●○○ › Fair ●○○○). More filled = better deal FOR
// its (type × build-tier) peers. Unrated bikes (value_level null) render nothing — never an
// empty ○○○○ meter. Neutral single-hue fill, no traffic-light colors.
const PIP_COUNT: Record<string, number> = { Exceptional: 4, Outstanding: 3, Great: 2, Good: 1 };

export function valuePips(level?: string | null): number {
  return level ? PIP_COUNT[level] ?? 0 : 0;
}

// The value-meter lead Highlight: the level in words ("Exceptional value"), or — when there
// are no pips — why the bike couldn't be scored (incomplete component data, or too few
// comparable bikes). Shown as the first Highlights entry on card + detail.
export function valueHighlightLabel(t?: {
  value_level?: string | null;
  build_tier?: string | null;
}): string {
  if (t?.value_level) return `${t.value_level} value`;
  if (!t?.build_tier) return "Value score unavailable — incomplete specs";
  return "Value score unavailable — too few comparable bikes";
}

export function ValuePips({ level }: { level?: string | null }) {
  const n = valuePips(level);
  if (!n) return null;
  return (
    <span
      className="inline-flex items-center gap-px"
      title={`${level} value`}
      aria-label={`${level} value`}
    >
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className={`h-1 w-1 rounded-full ${i < n ? "bg-brand-600" : "bg-slate-300"}`}
        />
      ))}
    </span>
  );
}
