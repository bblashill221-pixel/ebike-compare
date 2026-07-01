import { Link, NavLink } from "react-router-dom";
import { Logo } from "./Logo";
import { useData } from "../data/DataProvider";

function navClass({ isActive }: { isActive: boolean }) {
  return `rounded-lg px-3 py-1.5 text-sm font-medium ${
    isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
  }`;
}

export function Header() {
  const { generatedAt } = useData();
  // last data update, always shown in Pacific time (generated_at is UTC); timeZoneName
  // appends PST/PDT so the base zone is explicit regardless of the viewer's locale.
  const updated = generatedAt
    ? new Date(generatedAt).toLocaleString("en-US", {
        year: "2-digit", month: "numeric", day: "numeric",
        hour: "numeric", minute: "2-digit",
        timeZone: "America/Los_Angeles", timeZoneName: "short",
      })
    : null;
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
        <Link to="/" className="flex items-center">
          <Logo className="text-xl" />
        </Link>
        <nav className="ml-auto flex items-center gap-1">
          <NavLink to="/" end className={navClass}>
            Ebikes
          </NavLink>
          <NavLink to="/find" className={navClass}>
            Find My eBike
          </NavLink>
          <NavLink to="/value" className={navClass}>
            Value
          </NavLink>
          <NavLink to="/analysis" className={navClass}>
            Analysis
          </NavLink>
          {/* QA link shows only in dev; in production /qa has no link and is
              gated behind the localStorage `qa` flag. Tree-shaken from prod. */}
          {import.meta.env.DEV && (
            <NavLink to="/qa" className={navClass}>
              QA
            </NavLink>
          )}
        </nav>
        {updated && (
          <span
            className="hidden whitespace-nowrap text-[11px] text-slate-400 sm:inline"
            title={`Data last updated ${updated}`}
          >
            Updated {updated}
          </span>
        )}
      </div>
    </header>
  );
}
