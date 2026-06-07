import { Link } from "react-router-dom";
import { useData } from "../data/DataProvider";

export function Footer() {
  const { disclaimer, generatedAt, models } = useData();
  return (
    <footer className="mt-12 border-t border-slate-200 bg-white">
      <div className="mx-auto max-w-7xl space-y-2 px-4 py-6 text-xs text-slate-500">
        <p>
          <strong className="font-medium text-slate-600">Disclosure:</strong> Some links
          on this site are affiliate links — we may earn a commission if you buy through
          them, at no extra cost to you.{" "}
          <Link to="/disclosure" className="text-brand-600 hover:underline">
            Learn more
          </Link>
          .
        </p>
        {disclaimer && <p className="max-w-3xl">{disclaimer}</p>}
        <p className="text-slate-400">
          {models.length} models{generatedAt ? ` · data generated ${new Date(generatedAt).toLocaleDateString()}` : ""}.
          Specs and prices may be out of date — always confirm on the manufacturer’s site.
        </p>
      </div>
    </footer>
  );
}
