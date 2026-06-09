type Props = { className?: string };

/** Magnifying glass that stands in for the "o" in Compare: a lens + handle,
 * sized to the surrounding text via em units and tinted with the brand color. */
function MagnifierO({ className = "" }: Props) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`inline-block h-[0.82em] w-[0.82em] ${className}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={3.1}
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="10" cy="10" r="6.4" />
      <line x1="14.9" y1="14.9" x2="21" y2="21" />
    </svg>
  );
}

/**
 * "eBike Compare" wordmark — the "o" in Compare is a magnifying glass.
 * Inherits font weight/size from the caller; the lens picks up the brand color.
 */
export function Logo({ className = "" }: Props) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap font-extrabold tracking-tight text-slate-900 ${className}`}
      aria-label="eBike Compare"
    >
      eBike&nbsp;C<MagnifierO className="mx-[0.02em] text-brand-600" />mpare
    </span>
  );
}
