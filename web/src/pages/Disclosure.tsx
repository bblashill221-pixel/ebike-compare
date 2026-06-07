import { Link } from "react-router-dom";

export function Disclosure() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Affiliate disclosure</h1>
      <div className="mt-4 space-y-4 text-sm leading-relaxed text-slate-700">
        <p>
          Some of the outbound links on this site — typically the “View at &lt;brand&gt;”
          buttons that take you to a manufacturer’s product page — are{" "}
          <strong>affiliate links</strong>. If you click one and make a purchase, we may
          earn a commission from that manufacturer’s affiliate program.
        </p>
        <p>
          This comes at <strong>no extra cost to you</strong> — you pay the same price you
          would otherwise. Affiliate links are marked with a small “affiliate” tag next to
          them where they appear.
        </p>
        <p>
          Affiliate relationships do <strong>not</strong> influence which bikes we list,
          how we rank or score them, or the specifications we show. The data is gathered and
          analyzed independently, and we deliberately avoid a single “best overall” score so
          you can judge each bike on the criteria that matter to you.
        </p>
        <p>
          Specifications and prices are parsed from manufacturers’ published data and may be
          out of date or contain errors — always confirm details on the manufacturer’s site
          before buying.
        </p>
      </div>
      <div className="mt-6">
        <Link to="/" className="btn-primary">Back to browse</Link>
      </div>
    </div>
  );
}
