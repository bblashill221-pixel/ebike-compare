import { Link } from "react-router-dom";

// Small but visible affiliate marker shown next to monetized outbound links.
// Visible text (not hover-only) to satisfy the FTC "clear and conspicuous" floor,
// kept intentionally subtle.
export function DisclosureBadge() {
  return (
    <Link
      to="/disclosure"
      title="Some links are affiliate links — learn more"
      className="text-[10px] font-medium uppercase tracking-wide text-slate-400 underline-offset-2 hover:text-slate-600 hover:underline"
    >
      affiliate
    </Link>
  );
}
