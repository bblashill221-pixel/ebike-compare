#!/usr/bin/env python3
"""
Resolve TWO independent prices for every part in the component catalog:

  * retail_usd    — aftermarket street/replacement value (what a buyer pays to
                    buy that exact part) from US bike-component retailers
                    (Jenson USA, Worldwide Cyclery, Universal Cycles, …) or
                    manufacturer MSRP.
  * wholesale_usd — OEM unit cost proxy from AliExpress/Alibaba (by model, or by
                    the part's spec_class when it carries no model number).

These are two separate facts — analyze.py rolls each up per bike on its own.
There is NO blended/overall score (firm project rule).

Cache-first and staleness-aware, like llm_parse_components.py: a part is only
(re-)priced when it is new or its cached `checked_at` is older than
--max-age-days (default 30) — component prices move slowly, so a monthly refresh
is plenty and keeps the API spend bounded.

  python resolve_component_prices.py plan                 # due parts + cost estimate (offline)
  python resolve_component_prices.py run [--limit N]      # web-assisted lookup via Claude
  python resolve_component_prices.py export -o work.json  # due parts -> file for in-session research
  python resolve_component_prices.py ingest work.json     # ingest researched prices (no API key)
  python resolve_component_prices.py write-catalog        # re-apply cache into the catalog

For model-less parts the retail price falls back to the spec heuristic in
estimate_component_costs.py (reused, not duplicated); wholesale still comes from
the OEM range-by-spec lookup.

Cache: data/curated/component_prices.json  (keyed category|manufacturer|model)
Needs ANTHROPIC_API_KEY only for `run`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from estimate_component_costs import (
    cost_battery, cost_motor, cost_brakes, cost_drivetrain, cost_fork,
    cost_display, cost_tires,
)

DATA = Path(__file__).parent / "data"
CATALOG_PATH = DATA / "component_catalog.json"
CACHE_PATH = DATA / "curated" / "component_prices.json"
MODEL = "claude-opus-4-8"
PARTS_PER_REQUEST = 8
DEFAULT_MAX_AGE_DAYS = 30

RETAIL_SOURCES = ("jensonusa.com", "worldwidecyclery.com", "universalcycles.com",
                  "modernbike.com", "bike-discount.de", "manufacturer MSRP")
WHOLESALE_SOURCES = ("aliexpress.com", "alibaba.com")

# Catalog category -> spec-cost function from estimate_component_costs.py. Reused
# (not re-implemented) for the model-less retail fallback.
_FALLBACK_FN = {
    "battery": cost_battery, "motor": cost_motor, "brakes": cost_brakes,
    "fork": cost_fork, "display": cost_display, "tire": cost_tires,
    "derailleur": cost_drivetrain, "cassette": cost_drivetrain,
    "chain": cost_drivetrain, "crankset": cost_drivetrain, "shifter": cost_drivetrain,
}
# Flat single-part base costs for categories without a spec-cost function (drawn
# from estimate_component_costs.SPEC_DRIVEN's per-bike numbers, scaled to one part).
_FALLBACK_FLAT = {
    "saddle": 45, "seatpost": 45, "seat_post": 45, "stem": 25, "handlebar": 30,
    "grips_bar_tape": 12, "hub": 40, "pedals": 20, "light": 30, "charger": 35,
    "controller": 40, "throttle": 15, "sensor": 35, "wheel": 65, "rims": 35,
    "fenders": 25, "rack": 35, "kickstand": 12,
}


# --------------------------------- IO helpers ---------------------------------

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def load_catalog() -> dict:
    return load_json(CATALOG_PATH, {}).get("components") or {}


def load_cache() -> dict:
    return load_json(CACHE_PATH, {})


def save_cache(cache: dict):
    CACHE_PATH.write_text(json.dumps(cache, indent=1, ensure_ascii=False))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------ due-key selection ------------------------------

def _age_days(checked_at: str | None) -> float | None:
    if not checked_at:
        return None
    try:
        ts = datetime.fromisoformat(checked_at)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0


def is_due(key: str, cache: dict, max_age_days: int) -> bool:
    """New, never-stamped, or stale -> needs (re-)pricing."""
    c = cache.get(key)
    if not c:
        return True
    age = _age_days(c.get("checked_at"))
    return age is None or age >= max_age_days


def due_keys(catalog: dict, cache: dict, max_age_days: int) -> list[str]:
    # only price parts currently used by at least one bike; dropped-out parts
    # keep whatever they had (their cache survives for when they return)
    return [k for k, e in catalog.items()
            if e.get("usage_count", 0) > 0 and is_due(k, cache, max_age_days)]


# ----------------------------- heuristic fallback -----------------------------

def _synth_specs(entry: dict) -> dict:
    """A minimal {label: text} specs dict so estimate_component_costs.cost_*
    (which scan spec labels) work on a single catalog part."""
    bits = [entry.get("spec_class") or "", entry.get("sample_details") or ""]
    for k, v in (entry.get("attributes") or {}).items():
        if k != "_kind" and v not in (None, ""):
            bits.append(f"{k} {v}")
    blob = " ".join(b for b in bits if b)
    return {entry.get("category", "part"): blob}


def heuristic_retail(entry: dict) -> tuple[int | None, str | None]:
    """Estimated single-part retail cost for a model-less part."""
    cat = entry.get("category", "")
    fn = _FALLBACK_FN.get(cat)
    if fn:
        c, note = fn(_synth_specs(entry))
        if c:
            return int(c), note
    if cat in _FALLBACK_FLAT:
        return _FALLBACK_FLAT[cat], f"{cat} base estimate"
    return None, None


# ---------------------------- catalog write-back ----------------------------

def apply_cache_to_catalog(cache: dict) -> int:
    """Fold every cached price into the catalog's aftermarket block. Returns the
    number of catalog entries that ended up with at least one price."""
    doc = load_json(CATALOG_PATH, {})
    comps = doc.get("components") or {}
    for key, c in cache.items():
        e = comps.get(key)
        if not e:
            continue
        am = e.setdefault("aftermarket", {})
        for f in ("retail_usd", "retail_url", "retail_source", "wholesale_usd",
                  "wholesale_url", "wholesale_source", "method", "checked_at", "notes"):
            if c.get(f) is not None:
                am[f] = c[f]
    priced = sum(1 for e in comps.values()
                 if (e.get("aftermarket") or {}).get("retail_usd") is not None
                 or (e.get("aftermarket") or {}).get("wholesale_usd") is not None)
    doc["priced_count"] = priced
    doc["generated_at"] = now_iso()
    CATALOG_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    return priced


def _cache_entry(key: str, entry: dict, *, retail_usd=None, retail_url=None,
                 retail_source=None, wholesale_usd=None, wholesale_url=None,
                 wholesale_source=None, notes=None) -> dict:
    method = "model_lookup" if entry.get("model") else "oem_range_by_spec"
    # model-less retail comes from the spec heuristic
    if retail_usd is None and not entry.get("model"):
        retail_usd, h_note = heuristic_retail(entry)
        if retail_usd is not None:
            retail_source = retail_source or "spec_heuristic"
            notes = " | ".join(x for x in (notes, f"retail≈{h_note}") if x)
    return {
        "category": entry.get("category"), "manufacturer": entry.get("manufacturer"),
        "model": entry.get("model"), "spec_class": entry.get("spec_class"),
        "retail_usd": retail_usd, "retail_url": retail_url, "retail_source": retail_source,
        "wholesale_usd": wholesale_usd, "wholesale_url": wholesale_url,
        "wholesale_source": wholesale_source, "method": method,
        "checked_at": now_iso(), "notes": notes,
    }


# --------------------------------- plan ---------------------------------

def cmd_plan(max_age_days: int):
    catalog, cache = load_catalog(), load_cache()
    due = due_keys(catalog, cache, max_age_days)
    modelled = sum(1 for k in due if catalog[k].get("model"))
    modelless = len(due) - modelled
    reqs = (len(due) + PARTS_PER_REQUEST - 1) // PARTS_PER_REQUEST
    print(f"catalog parts in use: {sum(1 for e in catalog.values() if e.get('usage_count',0)>0)}"
          f" | cached: {len(cache)} | due (>{max_age_days}d/new): {len(due)}")
    print(f"  due model-lookup (retail+wholesale): {modelled}")
    print(f"  due oem-range-by-spec (wholesale; retail=heuristic): {modelless}")
    print(f"  ~{reqs} web-search requests at {PARTS_PER_REQUEST} parts each")
    # rough: per request ~6K in (incl. tool results) + 1.5K out at Opus 4.8 prices
    est = reqs * ((6000 / 1e6 * 5.0) + (1500 / 1e6 * 25.0))
    print(f"  ~cost estimate at {MODEL} prices: ${est:.2f} (excludes web-search tool fees)")
    if due:
        print("\n  sample due parts:")
        for k in due[:6]:
            e = catalog[k]
            print(f"    {k}  ({'model' if e.get('model') else 'spec_class: '+str(e.get('spec_class'))})")


# --------------------------------- export / ingest ---------------------------------

def _work_row(key: str, e: dict) -> dict:
    return {"id": key, "category": e.get("category"),
            "manufacturer": e.get("manufacturer"), "model": e.get("model"),
            "spec_class": e.get("spec_class"), "attributes": e.get("attributes"),
            "sample_details": e.get("sample_details")}


def cmd_export(max_age_days: int, out: str, limit: int | None):
    catalog, cache = load_catalog(), load_cache()
    due = due_keys(catalog, cache, max_age_days)
    if limit:
        due = due[:limit]
    rows = [_work_row(k, catalog[k]) for k in due]
    Path(out).write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"[*] exported {len(rows)} due parts -> {out}")
    print("    fill: id, retail_usd, retail_url, retail_source, wholesale_usd, "
          "wholesale_url, wholesale_source, notes  (omit a price you can't find)")


def cmd_ingest(path: str):
    """Ingest researched prices: a list of dicts keyed by `id` (the catalog key)
    carrying any of retail_*/wholesale_*/notes. Model-less retail auto-fills from
    the heuristic when omitted."""
    catalog, cache = load_catalog(), load_cache()
    data = json.loads(Path(path).read_text())
    n = skipped = 0
    for row in data:
        key = row.get("id")
        entry = catalog.get(key)
        if not entry:
            skipped += 1
            continue
        cache[key] = _cache_entry(
            key, entry,
            retail_usd=row.get("retail_usd"), retail_url=row.get("retail_url"),
            retail_source=row.get("retail_source"),
            wholesale_usd=row.get("wholesale_usd"), wholesale_url=row.get("wholesale_url"),
            wholesale_source=row.get("wholesale_source"), notes=row.get("notes"))
        n += 1
    save_cache(cache)
    priced = apply_cache_to_catalog(cache)
    print(f"[*] ingested {n} parts ({skipped} unknown keys); catalog now {priced} priced")


# --------------------------------- write-catalog ---------------------------------

def cmd_write_catalog():
    priced = apply_cache_to_catalog(load_cache())
    print(f"[*] applied cache -> catalog ({priced} parts priced)")


# --------------------------------- run (web-assisted) ---------------------------------

SYSTEM = (
    "You are a bicycle-component pricing researcher. For each part you are given, "
    "use web search to find current US prices and return STRICT JSON only.\n"
    "For each part determine, in USD:\n"
    "- retail_usd: the current aftermarket street/replacement price from a reputable "
    "US bike-component retailer (jensonusa.com, worldwidecyclery.com, universalcycles.com, "
    "modernbike.com) or the manufacturer MSRP. Give retail_url and retail_source (the domain).\n"
    "- wholesale_usd: a representative OEM unit price from aliexpress.com or alibaba.com for "
    "the exact part, or — when the part has no model number — the closest match to its "
    "spec_class. Give wholesale_url and wholesale_source.\n"
    "Rules: prices are plain numbers (no $ or commas). If you genuinely cannot find a price, "
    "use null for it and say why in notes. Never invent a price or URL. Output ONLY a JSON "
    'object: {"results":[{"id","retail_usd","retail_url","retail_source","wholesale_usd",'
    '"wholesale_url","wholesale_source","notes"}, ...]} with one entry per part id.'
)


def _part_line(key: str, e: dict) -> str:
    if e.get("model"):
        return (f'{key} | {e.get("category")} | maker={e.get("manufacturer")} '
                f'| model={e.get("model")} | specs={json.dumps(e.get("attributes") or {})}')
    return (f'{key} | {e.get("category")} | maker={e.get("manufacturer")} '
            f'| NO MODEL — price wholesale by spec_class="{e.get("spec_class")}"')


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a possibly-fenced model reply."""
    s = text.strip()
    if "```" in s:
        s = s.split("```", 2)[1]
        s = s[4:] if s.lstrip().lower().startswith("json") else s
    start, end = s.find("{"), s.rfind("}")
    return json.loads(s[start:end + 1]) if start >= 0 and end > start else {}


def cmd_run(max_age_days: int, limit: int | None):
    import anthropic
    client = anthropic.Anthropic()
    catalog, cache = load_catalog(), load_cache()
    due = due_keys(catalog, cache, max_age_days)
    if limit:
        due = due[:limit]
    if not due:
        print("[*] nothing due — every in-use part is priced and fresh")
        return
    print(f"[*] pricing {len(due)} due parts in batches of {PARTS_PER_REQUEST}", file=sys.stderr)
    priced = errors = 0
    for i in range(0, len(due), PARTS_PER_REQUEST):
        batch = due[i:i + PARTS_PER_REQUEST]
        body = "\n".join(_part_line(k, catalog[k]) for k in batch)
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=4000,
                thinking={"type": "adaptive"},
                system=SYSTEM,
                tools=[{"type": "web_search_20250305", "name": "web_search",
                        "max_uses": PARTS_PER_REQUEST * 3}],
                messages=[{"role": "user", "content": body}],
            ) as stream:
                msg = stream.get_final_message()
            text = "".join(b.text for b in msg.content if b.type == "text")
            results = _extract_json(text).get("results", [])
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] batch {i // PARTS_PER_REQUEST} failed: {exc}", file=sys.stderr)
            errors += 1
            continue
        by_id = {r.get("id"): r for r in results}
        for key in batch:
            r = by_id.get(key, {})
            cache[key] = _cache_entry(
                key, catalog[key],
                retail_usd=r.get("retail_usd"), retail_url=r.get("retail_url"),
                retail_source=r.get("retail_source"),
                wholesale_usd=r.get("wholesale_usd"), wholesale_url=r.get("wholesale_url"),
                wholesale_source=r.get("wholesale_source"), notes=r.get("notes"))
            priced += 1
        save_cache(cache)   # checkpoint after every batch
        print(f"  priced {min(i + PARTS_PER_REQUEST, len(due))}/{len(due)}", file=sys.stderr)
    n_priced = apply_cache_to_catalog(cache)
    print(f"[*] processed {priced} parts ({errors} batch errors); catalog {n_priced} priced")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run", "export", "ingest", "write-catalog"):
        p = sub.add_parser(name)
        p.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
        if name in ("run", "export"):
            p.add_argument("--limit", type=int, default=None)
        if name == "export":
            p.add_argument("-o", "--out", default="/tmp/component_prices_work.json")
        if name == "ingest":
            p.add_argument("path")
    args = ap.parse_args()

    if args.cmd == "plan":
        cmd_plan(args.max_age_days)
    elif args.cmd == "run":
        cmd_run(args.max_age_days, args.limit)
    elif args.cmd == "export":
        cmd_export(args.max_age_days, args.out, args.limit)
    elif args.cmd == "ingest":
        cmd_ingest(args.path)
    elif args.cmd == "write-catalog":
        cmd_write_catalog()


if __name__ == "__main__":
    main()
