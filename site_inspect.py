#!/usr/bin/env python3
"""
Unified site inspection: ONE report over what every model actually SHOWS on the
site and how well its components parse.

Adds the two dimensions the existing per-field audits miss, and folds the existing
audits in so triage is a single ranked list:
  * RENDER  -- mirror the data-level decisions of the Browse card (BikeCard) and the
               Detail page (BikeDetail) and flag what a user would see as broken,
               empty, or self-contradictory (no image, "-" price, all spec tiles
               blank, a spec group that renders empty, a component whose own fields
               contradict its text).
  * PARSE   -- a fleet-wide component parse-quality sweep: unparsed/under-parsed
               components, run-on `details`, a missing critical field for the kind --
               each with a SUGGESTED fix (re-run the rule parser on the text).
  * FOLD-IN -- read data_audit.json (missing expected fields) and anomalies.json
               (misparse/misclassify) and merge them in -- no check logic duplicated.

  python site_inspect.py                    # static sweep -> report + console
  python site_inspect.py --brand aventon    # restrict to one brand
  python site_inspect.py --limit 50         # first N models
  python site_inspect.py --severity medium  # console shows >= this severity
  python site_inspect.py --render           # ALSO headless-render flagged + a sample
                                            # (needs the web app running; see --base-url)

Read-only over data/current/active/ebike.json (inline component dicts -- interning is
web-payload-only). On-demand; NOT wired into the promote gate.
"""
import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from parse_components import parse_component

HERE = Path(__file__).parent
DATA = HERE / "data"
ACTIVE = DATA / "current" / "active" / "ebike.json"
DATA_AUDIT = DATA / "current" / "data_audit.json"
ANOMALIES = DATA / "current" / "anomalies.json"
REPORT = DATA / "current" / "inspection_report.json"

SEVERITIES = ["high", "medium", "low"]
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}

# Reserved (non-spec) keys on a parsed component dict.
_META = {"_kind", "details", "catalog_key", "retail_usd", "by_size"}

# The card's 9 at-a-glance spec tiles (BikeCard). If EVERY one is empty the card is
# a wall of "-".
TILE_FIELDS = [
    ("battery_wh",), ("motor_w", "motor_peak_w"), ("torque_nm",), ("max_speed_mph",),
    ("range_mi",), ("weight_lb",), ("fit_height_min_in", "fit_height_max_in"),
    ("max_load_lb",), ("sensor_type",),
]

# The kind's defining field(s): present if ANY listed key is set. Only checked on the
# PRIMARY field for that kind (see PRIMARY_FIELD) -- a brand often splits a component
# across rows (Motor / Motor Torque / Motor Power; Brake / Brake Rotor), and those
# sub-rows legitimately lack the primary field.
CRITICAL = {
    "motor": ("power_w", "peak_w"),
    "battery": ("capacity_wh", "total_capacity_wh"),
    "brake": ("actuation", "kind"),
    "tire": ("width_in",),
    "fork": ("travel_mm", "type"),          # type "rigid" legitimately has no travel
    "derailleur": ("speeds", "manufacturer"),
    "cassette": ("speeds", "cog_range"),
    "display": ("type", "manufacturer"),
    "charger": ("amps_a", "output_v"),
    "shock": ("type", "manufacturer"),
}
# Field name (position prefix stripped) that holds the PRIMARY instance of a kind --
# so a critical-field check doesn't fire on a decomposed sub-row.
PRIMARY_FIELD = {
    "motor": {"motor"}, "battery": {"battery"}, "brake": {"brake", "brakes"},
    "tire": {"tire", "tires"}, "fork": {"fork"}, "derailleur": {"derailleur"},
    "cassette": {"cassette"}, "display": {"display"}, "charger": {"charger"},
    "shock": {"shock", "rear_shock"},
}

# High-precision self-contradiction checks: a structured field's value contradicted by
# the component's own `details` text (the class of bug fixed on the Vanpowers fork +
# the Levo hub/mid mis-parse). {kind: [(field, {value: contradicting_regex})]}.
CONFLICTS = {
    "fork": [("type", {"coil": r"\bair\b", "air": r"\bcoil\b"})],
    "brake": [("actuation", {"hydraulic": r"\bmechanical\b|\bcable[\s-]?actuat",
                             "mechanical": r"\bhydraulic\b"})],
    "motor": [("placement", {"mid": r"\bhub[\s-]?(?:motor|drive)\b",
                             "hub": r"\bmid[\s-]?drive\b"})],
}

DETAILS_RUNON = 100   # chars; a `details` longer than this likely hides structure


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


# ------------------------------- render mirrors --------------------------------

def lowest_price(m):
    """Port of web/src/pricing.ts lowestPrice: cheapest of the base price and every
    configuration price; None when nothing is purchasable (card shows '-')."""
    cands = [m.get("price") if m.get("price") is not None else m.get("price_min")]
    for c in m.get("configurations") or []:
        if c.get("price") is not None:
            cands.append(c["price"])
    nums = [v for v in cands if isinstance(v, (int, float))]
    return min(nums) if nums else None


def has_image(m):
    return any((c or {}).get("image") for c in (m.get("colors") or []))


def iter_components(m):
    """Yield (group, field, comp_dict) for every parsed component on a model."""
    for group, fields in (m.get("specs") or {}).items():
        if not isinstance(fields, dict):
            continue
        for field, v in fields.items():
            if isinstance(v, dict) and "_kind" in v:
                yield group, field, v


def structural_fields(comp):
    return [k for k in comp if k not in _META]


def suggest(field, comp, brand):
    """Re-run the rule parser on the component's `details` text; suggest any structured
    fields it pulls out that aren't already present. This is the 'parsing could be done
    better' hint -- a local, offline, rule-based extraction (no API)."""
    txt = comp.get("details")
    if not isinstance(txt, str) or not txt.strip():
        return None
    try:
        parsed = parse_component(field, txt, brand)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    extra = {k: v for k, v in parsed.items()
             if k not in _META and k not in comp and v not in (None, "", [], {})}
    return extra or None


# --------------------------------- checks --------------------------------------

def check_card(m, finds):
    if not has_image(m):
        finds.append(("card", "medium", "no image on any color (card shows 'no image')"))
    if lowest_price(m) is None:
        finds.append(("card", "high", "no purchasable price (card price renders '-')"))
    t = (m.get("analysis") or {}).get("specs_typed") or {}
    if not any(t.get(k) not in (None, "", [], {}) for tile in TILE_FIELDS for k in tile):
        finds.append(("card", "high", "every spec tile is empty (card is a wall of '-')"))
    if not m.get("product_type"):
        finds.append(("card", "medium", "no product_type (no type chip)"))
    if not ((m.get("analysis") or {}).get("standouts")):
        finds.append(("card", "low", "no standouts/highlights"))


def check_detail(m, finds):
    # a spec group that survives to the detail page but carries no renderable content
    for group, fields in (m.get("specs") or {}).items():
        if group in ("geometry", "general_info") or not isinstance(fields, dict):
            continue
        renderable = False
        for v in fields.values():
            if isinstance(v, dict) and structural_fields(v):
                renderable = True
            elif isinstance(v, dict) and (v.get("details") or "").strip():
                renderable = True
            elif not isinstance(v, dict) and str(v or "").strip():
                renderable = True
        if not renderable and fields:
            finds.append(("detail", "low", f"spec group '{group}' renders empty"))
    # percentile section: a metric with no cohort stat just hides (info only)
    # (left out of the flagged set to avoid noise; covered by data_audit coverage.)


def _primary(field, kind):
    base = re.sub(r"^(front|rear|left|right)_", "", field.lower())
    return base in PRIMARY_FIELD.get(kind, {kind})


def _has_crit(c, kind):
    crit = CRITICAL.get(kind)
    return not crit or any(c.get(k) not in (None, "", [], {}) for k in crit)


def check_parse(m, finds):
    """Actionable parse-quality only: a finding either (a) is a self-contradiction,
    (b) comes with a concrete suggested fix the rule parser can extract from `details`,
    or (c) is a high-value (CRITICAL-kind) component left with no structure at all."""
    brand = m.get("brand")
    sib = defaultdict(list)
    comps = list(iter_components(m))
    for _, _, c in comps:
        sib[c["_kind"]].append(c)
    for group, field, c in comps:
        kind = c["_kind"]
        det = c.get("details") or ""
        sf = structural_fields(c)
        loc = f"{kind} [{group}.{field}]"

        # (a) self-contradiction -- a visibly wrong value vs the component's own text
        low = det.lower()
        for f, rules in CONFLICTS.get(kind, []):
            val = c.get(f)
            rx = rules.get(val) if isinstance(val, str) else None
            if rx and re.search(rx, low):
                finds.append(("parse", "medium",
                              f"{loc}: {f}='{val}' contradicts details \"{det[:60]}\""))

        # decide whether re-parsing the details is worthwhile for this component
        missing_crit = (kind in CRITICAL and _primary(field, kind) and not _has_crit(c, kind))
        worth = (not sf) or missing_crit or len(det) > DETAILS_RUNON
        sug = suggest(field, c, brand) if worth else None

        # (b) concrete improvement available -> medium if it fills a critical field
        if sug:
            crit = CRITICAL.get(kind, ())
            useful = any(k in crit for k in sug)
            finds.append(("parse", "medium" if useful else "low",
                          f"{loc}: parser can extract {sug} from \"{det[:50]}\"", sug))
        # (c) a high-value component with no structure and nothing extractable
        elif not sf and kind in CRITICAL:
            finds.append(("parse", "low", f"{loc}: unparsed (only _kind+details)"))

        # brand-extraction miss: a sibling instance has a manufacturer, this one doesn't
        if "manufacturer" not in c and sf and any("manufacturer" in s for s in sib[kind]):
            finds.append(("parse", "low", f"{loc}: no manufacturer (a sibling has one)"))


# --------------------------------- fold-in -------------------------------------

def fold_audits(by_id, findings):
    """Merge the existing audits into the same finding stream: each model's own
    `data_audit.missing` (written by audit.py) for missing expected fields, and
    anomalies.json (audit_anomalies.py) for misparse/misclassify. No logic duplicated."""
    fold = 0
    for mid, m in by_id.items():
        for field in (m.get("data_audit") or {}).get("missing", []):
            findings[mid].append(("missing_field", "low", f"missing {field}"))
            fold += 1
    an = load(ANOMALIES, {})
    for a in an.get("anomalies", []):
        mid = a.get("id")
        if mid in by_id:
            findings[mid].append(("anomaly", a.get("severity", "low"),
                                  f"[{a.get('rule')}] {a.get('detail', '')}"))
            fold += 1
    return fold, DATA_AUDIT.exists(), bool(an)


# --------------------------------- render --------------------------------------

async def render_pass(targets, base_url):
    """Headless-render the Browse grid + each target detail route; capture console
    errors and visually-empty renders. Needs the web app served at base_url."""
    import scraper_common  # noqa: F401  (sets LD_LIBRARY_PATH before playwright import)
    from playwright.async_api import async_playwright
    out = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        # land straight on Browse: a bare "/" first-run-redirects to the quiz, but any
        # search string (App.tsx guard) shows the grid -- so use "#/?all".
        try:
            await page.goto(f"{base_url}/#/?all", wait_until="networkidle", timeout=30000)
        except Exception as exc:
            await browser.close()
            return [("render", "high", f"cannot reach web app at {base_url}: {exc}")]
        # browse grid renders cards? (cards are Links to /bike/<id> inside .card divs;
        # the grid appears only after the async data load + Orama index build, so wait.)
        try:
            await page.wait_for_selector("a[href*='/bike/']", timeout=12000)
        except Exception:
            pass
        cards = await page.locator("a[href*='/bike/']").count()
        if cards == 0:
            out.append(("render", "high", "Browse grid rendered 0 cards"))
        for mid in targets:
            errors.clear()
            try:
                await page.goto(f"{base_url}/#/bike/{mid}", wait_until="networkidle", timeout=30000)
                await page.wait_for_selector("h1", timeout=10000)
                body = (await page.locator("body").inner_text()) or ""
            except Exception as exc:
                out.append(("render", "high", f"{mid}: navigation failed: {exc}"))
                continue
            if len(body.strip()) < 200:
                out.append(("render", "high", f"{mid}: detail page rendered nearly empty"))
            if "$" not in body:
                out.append(("render", "medium", f"{mid}: no price visible on detail page"))
            for e in errors[:3]:
                out.append(("render", "medium", f"{mid}: console error: {e[:120]}"))
        await browser.close()
    return out


# --------------------------------- driver --------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brand", help="restrict to one brand")
    ap.add_argument("--limit", type=int, help="first N models")
    ap.add_argument("--severity", choices=SEVERITIES, default="low",
                    help="console shows findings at or above this severity (default low)")
    ap.add_argument("--render", action="store_true",
                    help="also headless-render flagged models + a sample (needs the web app)")
    ap.add_argument("--base-url", default="http://localhost:5173",
                    help="served web app URL for --render (Vite dev default)")
    ap.add_argument("--sample", type=int, default=15, help="extra random models to render")
    args = ap.parse_args()

    doc = load(ACTIVE, None)
    if not doc:
        sys.exit(f"cannot read {ACTIVE} -- run rebuild_offline.sh first")
    models = doc["models"]
    if args.brand:
        models = [m for m in models if m["brand"] == args.brand]
    if args.limit:
        models = models[:args.limit]
    by_id = {m["id"]: m for m in models}

    findings = defaultdict(list)   # id -> [(category, severity, detail[, suggestion])]
    for m in models:
        loc = []
        check_card(m, loc)
        check_detail(m, loc)
        check_parse(m, loc)
        if loc:
            findings[m["id"]].extend(loc)
    folded, had_da, had_an = fold_audits(by_id, findings)

    if args.render:
        flagged = [mid for mid, fs in findings.items()
                   if any(SEV_RANK[f[1]] <= SEV_RANK["medium"] for f in fs)]
        pool = [mid for mid in by_id if mid not in flagged]
        sample = random.sample(pool, min(args.sample, len(pool)))
        targets = (flagged + sample)[:60]
        import asyncio
        for r in asyncio.run(render_pass(targets, args.base_url.rstrip("/"))):
            findings.setdefault("__render__", []).append(r)

    # ---- aggregate ----
    flat = []
    cat_count, sev_count, kind_worklist = Counter(), Counter(), Counter()
    for mid, fs in findings.items():
        m = by_id.get(mid, {})
        for f in fs:
            cat, sev, detail = f[0], f[1], f[2]
            sug = f[3] if len(f) > 3 else None
            cat_count[cat] += 1
            sev_count[sev] += 1
            if cat == "parse":
                km = re.match(r"(\w+) \[", detail)
                if km:
                    kind_worklist[km.group(1)] += 1
            flat.append({"id": mid, "brand": m.get("brand"), "model": m.get("model"),
                         "category": cat, "severity": sev, "detail": detail,
                         **({"suggestion": sug} if sug else {})})
    flat.sort(key=lambda r: (SEV_RANK[r["severity"]], r["category"], r["id"]))

    da = load(DATA_AUDIT, {})
    report = {
        "generated_at": now_iso(),
        "model_count": len(models),
        "models_flagged": len([k for k in findings if k != "__render__"]),
        "folded_in": {"data_audit": had_da, "anomalies": had_an, "folded_rows": folded},
        "fleet_summary": {
            "by_category": dict(cat_count.most_common()),
            "by_severity": {s: sev_count.get(s, 0) for s in SEVERITIES},
            "parse_worklist_by_kind": dict(kind_worklist.most_common()),
            "missing_by_field": (da.get("summary") or {}).get("missing_by_field", {}),
            "coverage": da.get("coverage", {}),
        },
        "findings": flat,
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    # ---- console summary ----
    print(f"\nSITE INSPECTION  ({len(models)} models, {report['models_flagged']} flagged)")
    print(f"  by severity : " + "  ".join(f"{s}={sev_count.get(s,0)}" for s in SEVERITIES))
    print(f"  by category : " + "  ".join(f"{c}={n}" for c, n in cat_count.most_common()))
    if kind_worklist:
        print("\n  parse worklist (components to improve, by kind):")
        for k, n in kind_worklist.most_common(10):
            print(f"     {k:14} {n}")
    if da:
        mbf = (da.get("summary") or {}).get("missing_by_field", {})
        if mbf:
            print("\n  top missing fields across the app:")
            for fld, n in sorted(mbf.items(), key=lambda x: -x[1])[:10]:
                print(f"     {fld:22} {n}")
    cut = SEV_RANK[args.severity]
    shown = [r for r in flat if SEV_RANK[r["severity"]] <= cut]
    print(f"\n  top findings (severity >= {args.severity}, {len(shown)} total):")
    for r in shown[:30]:
        nm = f"{r['brand']}/{r['model']}"[:34]
        print(f"     [{r['severity']:6}] {r['category']:13} {nm:36} {r['detail'][:80]}")
    print(f"\n  full report -> {REPORT}")


if __name__ == "__main__":
    main()
