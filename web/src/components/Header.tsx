import { Link, NavLink } from "react-router-dom";

function navClass({ isActive }: { isActive: boolean }) {
  return `rounded-lg px-3 py-1.5 text-sm font-medium ${
    isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
  }`;
}

export function Header() {
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
        <Link to="/" className="flex items-center gap-2 font-bold text-slate-900">
          <span className="text-xl">⚡</span>
          <span>e-bike compare</span>
        </Link>
        <nav className="ml-auto flex items-center gap-1">
          <NavLink to="/" end className={navClass}>
            Browse
          </NavLink>
          <NavLink to="/analysis" className={navClass}>
            Analysis
          </NavLink>
        </nav>
      </div>
    </header>
  );
}
