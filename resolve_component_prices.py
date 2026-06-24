#!/usr/bin/env python3
"""
Resolve a single RETAIL price for every part in the component catalog:

  * retail_usd — aftermarket street/replacement value (what a buyer pays to buy
                 that exact part) from US bike-component retailers (Jenson USA,
                 Worldwide Cyclery, Universal Cycles, …) or manufacturer MSRP.

Brand matters: a Bosch/Specialized system battery or a Fox fork costs far more
than a generic equivalent, so the estimators are brand/tier-aware. There is NO
blended/overall score (firm project rule). (Wholesale/OEM cost was dropped — too
hard to estimate reliably — so this is retail-only now.)

Monthly refresh, no API key needed — the scraper does the fetching. Three modes
on the selection commands (plan/scrape/run/export):
  (default)       only UNRESOLVED parts (no researched price / never looked up)
  --date M/D/Y    unresolved + any researched price last checked before that date
  --all           every in-use part (full re-price; in sync with the normalized build)

  python resolve_component_prices.py plan [--all|--date M/D/Y]   # show the due-set (offline)
  python resolve_component_prices.py scrape [--all|--date ...]   # KEY-FREE: price due parts from Worldwide Cyclery
  python resolve_component_prices.py export -o work.json         # due parts -> file for manual research
  python resolve_component_prices.py ingest work.json            # ingest researched prices (no API key)
  python resolve_component_prices.py run [--limit N]             # web-assisted lookup via Claude (needs key)
  python resolve_component_prices.py write-catalog               # re-finalize the catalog (estimate fills the rest)

`scrape` is the primary key-free refresh: it conservatively matches each part to a
Worldwide Cyclery (Shopify) listing and writes a researched price only on a strong
brand+model+category match. For model-less parts (and anything not matched) the retail
price falls back to the brand/spec heuristic in estimate_component_costs.py.

Prices live in the catalog itself (data/component_catalog.json).
Needs ANTHROPIC_API_KEY only for `run`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from estimate_component_costs import (
    cost_battery, cost_motor, cost_brakes, cost_drivetrain, cost_fork,
    cost_display, cost_tires,
)

DATA = Path(__file__).parent / "data"
CATALOG_PATH = DATA / "component_catalog.json"
# Prices live IN the catalog (one file): each component's `aftermarket` block holds the
# researched OR estimated retail price, a method ("researched"|"estimated") and a 0–1
# confidence. The old separate price cache (component_prices.json) was fully redundant
# with this and is gone — the "cache" helpers below now read/write the catalog directly.

# Estimate confidence by how much price-driving context the heuristic actually had.
def _confidence(method: str, basis: str | None) -> float:
    if method == "researched":
        return 0.9
    b = (basis or "").lower()
    if re.search(r"\d+\s*nm|\d+\s*wh|\d+\s*mm|\d+-speed|gates|pinion|rohloff|carbon", b):
        return 0.75                      # a real spec drove it (torque/Wh/travel/speed/material)
    if re.search(r"mid-drive|hub motor|premium|hydraulic|air|suspension|belt|cvt|gear", b):
        return 0.5                       # type/brand known, but not the precise spec
    return 0.35                          # flat category default / "assumed"


def _is_researched(am: dict, side: str) -> bool:
    """A side ('retail'/'wholesale') counts as researched when it has a price AND a real
    source (a URL or a retailer/marketplace domain — not the 'spec_heuristic' tag)."""
    if am.get(f"{side}_usd") is None:
        return False
    if am.get(f"{side}_url"):
        return True
    src = (am.get(f"{side}_source") or "").lower()
    return bool(src) and src != "spec_heuristic"
MODEL = "claude-opus-4-8"
PARTS_PER_REQUEST = 8

RETAIL_SOURCES = ("jensonusa.com", "worldwidecyclery.com", "universalcycles.com",
                  "modernbike.com", "bike-discount.de", "manufacturer MSRP")
WHOLESALE_SOURCES = ("aliexpress.com", "alibaba.com")

# Catalog category -> spec-cost function from estimate_component_costs.py, reused
# for the per-part retail fallback. NB drivetrain SINGLES (chain/cassette/shifter/
# derailleur/crankset) are intentionally NOT mapped here — cost_drivetrain prices a
# whole drivetrain, not one part — they use the per-part flats below instead.
_FALLBACK_FN = {
    "battery": cost_battery, "motor": cost_motor, "brakes": cost_brakes,
    "fork": cost_fork, "display": cost_display, "tire": cost_tires,
}
# Flat single-part retail estimates for categories without a per-part spec-cost
# function (street price of a budget OEM single, grounded in the price research).
_FALLBACK_FLAT = {
    "chain": 14, "shifter": 18, "derailleur": 25, "cassette": 22, "crankset": 45,
    "saddle": 30, "seatpost": 45, "seat_post": 45, "stem": 25, "handlebar": 30,
    "handlebars": 30, "grips": 18, "grips_bar_tape": 18, "hub": 50, "pedals": 20,
    "light": 30, "charger": 40, "controller": 45, "throttle": 18, "sensor": 35,
    "wheel": 75, "rims": 40, "fenders": 25, "rack": 35, "kickstand": 12,
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
    """The price 'cache' is now the catalog's own per-part `aftermarket` blocks — one
    file. Returns {catalog_key: aftermarket-dict} for staleness/research bookkeeping."""
    return {k: dict(e["aftermarket"]) for k, e in load_catalog().items()
            if isinstance(e.get("aftermarket"), dict)}


def save_cache(cache: dict):
    """Persist aftermarket blocks straight back into the catalog (prices live there)."""
    doc = load_json(CATALOG_PATH, {})
    comps = doc.get("components") or {}
    for key, am in cache.items():
        if key in comps:
            comps[key]["aftermarket"] = am
    doc["generated_at"] = now_iso()
    CATALOG_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------ due-set selection ------------------------------
# Three monthly-refresh modes (no API key needed — the scraper does the fetching):
#   (default)      only UNRESOLVED parts (no researched price / never looked up)
#   --date M/D/Y   unresolved PLUS any researched price last checked before that date
#   --all          every in-use part (full re-price; the set is sourced from the
#                  normalized build via component_catalog.py, so it stays in sync)

def _parse_mdy(s: str) -> datetime:
    return datetime.strptime(s, "%m/%d/%Y").replace(tzinfo=timezone.utc)


def _checked_before(checked_at: str | None, cutoff: datetime) -> bool:
    """True when a part's last-lookup date is missing/empty or older than the cutoff."""
    if not checked_at:
        return True
    try:
        ts = datetime.fromisoformat(checked_at)
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < cutoff


def select_due(catalog: dict, cache: dict, *, all_: bool = False,
               before: datetime | None = None) -> list[str]:
    """In-use parts that need a (re-)lookup under the selected mode."""
    out = []
    for k, e in catalog.items():
        if e.get("usage_count", 0) <= 0:
            continue
        if all_:
            out.append(k)
            continue
        am = cache.get(k) or {}
        if not _is_researched(am, "retail"):          # unresolved -> always due
            out.append(k)
        elif before is not None and _checked_before(am.get("checked_at"), before):
            out.append(k)
    return out


def _mode_label(all_: bool, before: datetime | None) -> str:
    if all_:
        return "all in-use parts"
    if before:
        return f"unresolved + checked before {before:%m/%d/%Y}"
    return "unresolved only"


# ----------------------------- heuristic fallback -----------------------------

def _synth_specs(entry: dict) -> dict:
    """A minimal {label: text} specs dict so estimate_component_costs.cost_* (which scan
    spec text) work on a single catalog part. Renders the entry's make/model + structured
    attributes back into the WORDING those estimators expect ("Bafang M600 500W mid-drive
    120Nm"), so brand/tier, placement and torque drive the context-aware estimate."""
    bits = [entry.get("manufacturer") or "", entry.get("model") or "",
            entry.get("spec_class") or "", entry.get("sample_details") or ""]
    for k, v in (entry.get("attributes") or {}).items():
        if k == "_kind" or v in (None, ""):
            continue
        if k == "placement":
            bits.append("mid-drive" if str(v).lower() == "mid" else "hub motor")
        elif k == "torque_nm":
            bits.append(f"{v}Nm")
        elif k == "capacity_wh":
            bits.append(f"{v}Wh")
        elif k in ("power_w", "peak_w"):
            bits.append(f"{v}W")
        elif k == "travel_mm":
            bits.append(f"{v}mm travel")
        elif k in ("speeds", "gears"):
            bits.append(f"{v}-speed")
        else:
            bits.append(f"{k} {v}")
    blob = " ".join(str(b) for b in bits if b)
    return {entry.get("category", "part"): blob}


# Frameset retail cost by material (USD). The frameset
# is never parsed as a branded part, so it's costed from the bike's typed frame
# material; a full-suspension frame (pivots/linkage/bearings) carries a premium over a
# hardtail/rigid one (the rear shock itself is priced separately as "rear_shock").
# Unknown material defaults to aluminium (the fleet's modal frame). "steel" is cheap
# hi-tensile/high-carbon (Q235) — below aluminium; quality steel (chromoly/4130) is a
# separate, pricier tier ABOVE aluminium (component_quality maps it from the frame text).
_FRAME_RETAIL = {"steel": 200, "aluminum": 420, "chromoly": 550, "carbon": 1700}
_FRAME_FS_MULT = 1.5


def _frame_cost(table: dict, a: dict) -> int:
    mat = (a.get("material") or "aluminum").lower()
    base = table.get(mat, table["aluminum"])
    if a.get("full_suspension") and mat in ("aluminum", "carbon"):
        base = round(base * _FRAME_FS_MULT)
    return base


def heuristic_retail(entry: dict) -> tuple[int | None, str | None]:
    """Estimated single-part retail cost for a model-less part."""
    cat = entry.get("category", "")
    # A Pinion / Rohloff gearbox is a premium sealed transmission (~$1500 retail), but it
    # parses as a model-less "shifter"/"derailleur" and would otherwise get the ~$18 flat —
    # crushing the value of bikes like the Priority Skyline (SMART.SHIFT Pinion). Detect it
    # by maker/model/text regardless of category.
    ident = (f"{entry.get('manufacturer') or ''} {entry.get('model') or ''} "
             f"{entry.get('spec_class') or ''} {entry.get('sample_details') or ''}").lower()
    if re.search(r"\bpinion\b|rohloff", ident):
        return 1500, "premium gearbox (Pinion/Rohloff)"
    if cat == "frame":
        a = entry.get("attributes") or {}
        return _frame_cost(_FRAME_RETAIL, a), f"{a.get('material') or 'aluminum'} frameset"
    fn = _FALLBACK_FN.get(cat)
    if fn:
        c, note = fn(_synth_specs(entry))
        if c:
            return int(c), note
    if cat in _FALLBACK_FLAT:
        return _FALLBACK_FLAT[cat], f"{cat} base estimate"
    return None, None


# ---------------------------- catalog write-back ----------------------------

_GENERIC_PART = 25   # retail fallback for a category with no estimator

_WHOLESALE_FIELDS = ("wholesale_usd", "wholesale_url", "wholesale_source",
                     "wholesale_method", "wholesale_confidence", "wholesale_basis")


def finalize_catalog() -> dict:
    """Make EVERY in-use component carry a RETAIL price in its `aftermarket` block: keep a
    researched price where present (method 'researched', confidence 0.9), else fill the
    brand/context-aware estimate (method 'estimated', confidence by basis). Retail-only —
    wholesale/OEM cost was dropped (too hard to estimate). The catalog is the single source
    of truth — researched if looked up, estimate as the fallback."""
    doc = load_json(CATALOG_PATH, {})
    comps = doc.get("components") or {}
    researched = estimated = 0
    for e in comps.values():
        am = e.setdefault("aftermarket", {})
        for k in _WHOLESALE_FIELDS:                       # purge any legacy wholesale fields
            am.pop(k, None)
        if _is_researched(am, "retail"):
            am["retail_method"] = "researched"
            am["retail_confidence"] = _confidence("researched", None)
            am.pop("retail_basis", None)
            researched += 1
        else:
            val, note = heuristic_retail(e)
            if val is None:
                val, note = _GENERIC_PART, "generic part (no estimator)"
            am["retail_usd"] = val
            am["retail_method"] = "estimated"
            am["retail_basis"] = note
            am["retail_confidence"] = _confidence("estimated", note)
            estimated += 1
        am.setdefault("currency", "USD")
    doc["priced_count"] = sum(1 for e in comps.values()
                              if (e.get("aftermarket") or {}).get("retail_usd") is not None)
    doc["price_sources"] = {"researched": researched, "estimated": estimated}
    doc["generated_at"] = now_iso()
    CATALOG_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    return doc["price_sources"]


def _cache_entry(key: str, entry: dict, *, retail_usd=None, retail_url=None,
                 retail_source=None, notes=None) -> dict:
    method = "model_lookup" if entry.get("model") else "spec_heuristic"
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
        "method": method, "checked_at": now_iso(), "notes": notes,
    }


# --------------------------------- plan ---------------------------------

def cmd_plan(all_: bool, before):
    catalog, cache = load_catalog(), load_cache()
    due = select_due(catalog, cache, all_=all_, before=before)
    modelled = sum(1 for k in due if catalog[k].get("model"))
    inuse = sum(1 for e in catalog.values() if e.get("usage_count", 0) > 0)
    print(f"catalog parts in use: {inuse} | mode: {_mode_label(all_, before)} | due: {len(due)}")
    print(f"  with a model# (scrapable): {modelled} | model-less (heuristic only): {len(due) - modelled}")
    if due:
        print("\n  sample due parts:")
        for k in due[:8]:
            e = catalog[k]
            tag = f"model: {e.get('model')}" if e.get("model") else f"spec_class: {e.get('spec_class')}"
            print(f"    {k}  ({tag})")


# --------------------------------- export / ingest ---------------------------------

def _work_row(key: str, e: dict) -> dict:
    return {"id": key, "category": e.get("category"),
            "manufacturer": e.get("manufacturer"), "model": e.get("model"),
            "spec_class": e.get("spec_class"), "attributes": e.get("attributes"),
            "sample_details": e.get("sample_details")}


def cmd_export(all_: bool, before, out: str, limit: int | None):
    catalog, cache = load_catalog(), load_cache()
    due = select_due(catalog, cache, all_=all_, before=before)
    if limit:
        due = due[:limit]
    rows = [_work_row(k, catalog[k]) for k in due]
    Path(out).write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"[*] exported {len(rows)} due parts -> {out}")
    print("    fill: id, retail_usd, retail_url, retail_source, notes  "
          "(omit a price you can't find)")


def cmd_ingest(path: str):
    """Ingest researched prices: a list of dicts keyed by `id` (the catalog key)
    carrying any of retail_usd/retail_url/retail_source/notes. Model-less retail
    auto-fills from the heuristic when omitted."""
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
            retail_source=row.get("retail_source"), notes=row.get("notes"))
        n += 1
    save_cache(cache)
    r = finalize_catalog()
    print(f"[*] ingested {n} parts ({skipped} unknown keys); catalog finalized "
          f"({r['researched']} researched + {r['estimated']} estimated)")


# --------------------------------- write-catalog ---------------------------------

def cmd_write_catalog():
    r = finalize_catalog()
    print(f"[*] catalog finalized: {r['researched']} researched + "
          f"{r['estimated']} estimated retail prices (every in-use part now priced)")


# --------------------------- scrape (key-free retailer lookup) ---------------------------
# Worldwide Cyclery is a Shopify store: its predictive-search endpoint returns structured
# {title, price, vendor, handle} JSON with no API key. We query "<maker> <model>" per due
# part and CONSERVATIVELY match (brand + EVERY model token + a category keyword, minus
# accessory/sub-part/bundle listings) so a wrong product never overwrites a price — an
# ambiguous part is left as its brand/spec estimate. Proprietary OEM parts (Bosch/
# Specialized system batteries, house-brand cockpits) aren't carried here and stay estimated.

WWC_BASE = "https://www.worldwidecyclery.com"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; ebike-compare price refresh)"}

# category -> keyword(s) the product title MUST contain (a fork query must not land on a
# cassette; a "handlebars" query must not land on a same-brand chainring). A part whose
# category is NOT mapped here is never matched — we only price categories we can sanity-
# check, leaving the rest as estimates.
_CAT_KEYWORDS = {
    "brakes": ("brake",), "fork": ("fork", "suspension"), "rear_shock": ("shock",),
    "derailleur": ("derailleur",), "cassette": ("cassette",), "shifter": ("shift",),
    "chain": ("chain",), "crankset": ("crank",), "motor": ("motor", "drive unit"),
    "battery": ("battery",), "tire": ("tire", "tyre"), "display": ("display", "computer"),
    "saddle": ("saddle",), "seatpost": ("seatpost", "seat post"),
    "seat_post": ("seatpost", "seat post"), "stem": ("stem",),
    "handlebar": ("handlebar",), "handlebars": ("handlebar",),
    "handlebar_tape": ("bar tape", "handlebar tape"), "grips": ("grip",),
    "grips_bar_tape": ("grip", "bar tape"), "hub": ("hub",),
    "rims": ("rim", "wheel"), "wheel": ("wheel", "rim"), "pedals": ("pedal",),
}
# Sub-part / accessory / service / compatibility / bundle listings that are NOT the
# complete part we're pricing. (For OEM/ebike parts, WWC often lists only a service
# piece or a "fits <model>" accessory — e.g. a crank arm "For EP801" or a shock "Damper
# Shaft Assembly", which name the part in the title but aren't it.)
_REJECT_TITLE = re.compile(
    r"\bkit\b|service|\btokens?\b|bleed|\bspare(s)?\b|\bseal\b|bushing|decal|sticker|"
    r"\bremote\b|adapter|\bmount(ing)?\b|\btool\b|\bstand\b|bottle|\bbag\b|lever only|"
    r"\bpads?\b|\brotor\b|\bbolt|\bspacer|groupset|\bcombo\b|\bbundle\b|replacement|"
    r"\bassembly\b|eyelet|\bdamper\b|\bshaft\b|crank arm|arm set|hardware|small part|"
    r"\bcap\b|\bspider\b|compatible|\bfits?\b|\bfor e\w*\d|\bgroup\b|power meter", re.I)
_TOK_STOP = {"the", "and", "for", "with", "series", "drive", "unit", "system",
             "ebike", "e-bike", "bike", "new"}


def _toks(s: str | None) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower())
            if len(t) >= 2 and t not in _TOK_STOP]


def _wwc_search(query: str, limit: int = 6) -> list[dict]:
    url = WWC_BASE + "/search/suggest.json?" + urllib.parse.urlencode(
        {"q": query, "resources[type]": "product", "resources[limit]": limit})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=20) as r:
            d = json.loads(r.read())
        return d.get("resources", {}).get("results", {}).get("products", []) or []
    except Exception:  # noqa: BLE001 - network/JSON errors -> no match, part stays estimated
        return []


def _match_product(entry: dict, products: list[dict]) -> dict | None:
    """Conservative match: brand + EVERY model token + a category keyword present, no
    reject words. Returns the cheapest qualifying listing, or None (leave as estimate)."""
    man = (entry.get("manufacturer") or "").lower()
    mtoks = _toks(entry.get("model"))
    cat_kw = _CAT_KEYWORDS.get(entry.get("category", ""))
    if not man or not mtoks or not cat_kw:    # need brand + model + a checkable category
        return None
    best = None
    for p in products:
        title = p.get("title") or ""
        tl = title.lower()
        vendor = (p.get("vendor") or "").lower()
        if man not in vendor:                             # brand must be the product's VENDOR
            continue                                      # (not just named in the title — that
        if not all(re.search(rf"\b{re.escape(t)}\b", tl)  #  lets "fits <brand>" parts through)
                   for t in mtoks):                       # every model token present, whole-word
            continue                                      # (so "e10" != "e101")
        if not any(k in tl for k in cat_kw):              # category sanity (required)
            continue
        if _REJECT_TITLE.search(tl):                      # not a sub-part / bundle
            continue
        try:
            price = float(p.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        if best is None or price < best[0]:               # cheapest qualifying single part
            best = (price, p.get("handle"), title)
    if not best:
        return None
    return {"retail_usd": round(best[0]),
            "retail_url": f"{WWC_BASE}/products/{best[1]}",
            "retail_source": "worldwidecyclery.com",
            "notes": f"WWC match: {best[2][:80]}"}


def cmd_scrape(all_: bool, before, limit: int | None, delay: float = 0.4,
               categories: set | None = None):
    catalog, cache = load_catalog(), load_cache()
    due = [k for k in select_due(catalog, cache, all_=all_, before=before)
           if catalog[k].get("model")             # only model-numbered parts are scrapable
           and (not categories or (catalog[k].get("category") or "").lower() in categories)]
    if limit:
        due = due[:limit]
    print(f"[*] scraping Worldwide Cyclery for {len(due)} model-numbered due parts "
          f"({_mode_label(all_, before)})", file=sys.stderr)
    matched = missed = 0
    for i, key in enumerate(due, 1):
        e = catalog[key]
        q = f"{e.get('manufacturer') or ''} {e.get('model') or ''}".strip()
        hit = _match_product(e, _wwc_search(q))
        if hit:
            cache[key] = _cache_entry(key, e, **hit)
            matched += 1
        else:
            missed += 1
        if i % 25 == 0:
            save_cache(cache)                     # checkpoint
            print(f"  {i}/{len(due)} ({matched} matched, {missed} no-match)", file=sys.stderr)
        time.sleep(delay)                         # be polite to the store
    save_cache(cache)
    r = finalize_catalog()
    print(f"[*] scraped {len(due)}: {matched} priced from WWC, {missed} left as estimate; "
          f"catalog finalized ({r['researched']} researched + {r['estimated']} estimated)")


# --------------------------------- run (web-assisted) ---------------------------------

SYSTEM = (
    "You are a bicycle-component pricing researcher. For each part you are given, "
    "use web search to find the current US retail price and return STRICT JSON only.\n"
    "For each part determine, in USD:\n"
    "- retail_usd: the current aftermarket street/replacement price from a reputable "
    "US bike-component retailer (jensonusa.com, worldwidecyclery.com, universalcycles.com, "
    "modernbike.com) or the manufacturer MSRP. Give retail_url and retail_source (the domain). "
    "Take the brand into account — a Bosch/Specialized system battery or a Fox fork costs far "
    "more than a generic equivalent.\n"
    "Rules: prices are plain numbers (no $ or commas). If you genuinely cannot find a price, "
    "use null for it and say why in notes. Never invent a price or URL. Output ONLY a JSON "
    'object: {"results":[{"id","retail_usd","retail_url","retail_source","notes"}, ...]} '
    "with one entry per part id."
)


def _part_line(key: str, e: dict) -> str:
    if e.get("model"):
        return (f'{key} | {e.get("category")} | maker={e.get("manufacturer")} '
                f'| model={e.get("model")} | specs={json.dumps(e.get("attributes") or {})}')
    return (f'{key} | {e.get("category")} | maker={e.get("manufacturer")} '
            f'| NO MODEL — price retail by spec_class="{e.get("spec_class")}"')


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a possibly-fenced model reply."""
    s = text.strip()
    if "```" in s:
        s = s.split("```", 2)[1]
        s = s[4:] if s.lstrip().lower().startswith("json") else s
    start, end = s.find("{"), s.rfind("}")
    return json.loads(s[start:end + 1]) if start >= 0 and end > start else {}


def cmd_run(all_: bool, before, limit: int | None):
    import anthropic
    client = anthropic.Anthropic()
    catalog, cache = load_catalog(), load_cache()
    due = select_due(catalog, cache, all_=all_, before=before)
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
                retail_source=r.get("retail_source"), notes=r.get("notes"))
            priced += 1
        save_cache(cache)   # checkpoint after every batch
        print(f"  priced {min(i + PARTS_PER_REQUEST, len(due))}/{len(due)}", file=sys.stderr)
    r = finalize_catalog()
    print(f"[*] processed {priced} parts ({errors} batch errors); catalog finalized "
          f"({r['researched']} researched + {r['estimated']} estimated)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    SELECTION = ("plan", "scrape", "run", "export")
    for name in ("plan", "scrape", "run", "export", "ingest", "write-catalog"):
        p = sub.add_parser(name)
        if name in SELECTION:
            p.add_argument("--all", action="store_true",
                           help="re-price every in-use part (default: only unresolved parts)")
            p.add_argument("--date", type=_parse_mdy, default=None, metavar="MM/DD/YYYY",
                           help="also re-price researched parts last checked before this date")
        if name in ("scrape", "run", "export"):
            p.add_argument("--limit", type=int, default=None)
        if name == "scrape":
            p.add_argument("--categories", default=None,
                           help="comma-separated catalog categories to restrict to "
                                "(e.g. brakes,derailleur,shifter,cassette,chain,crankset,fork,shock,rear_shock,tire)")
        if name == "export":
            p.add_argument("-o", "--out", default="/tmp/component_prices_work.json")
        if name == "ingest":
            p.add_argument("path")
    args = ap.parse_args()

    if args.cmd == "plan":
        cmd_plan(args.all, args.date)
    elif args.cmd == "scrape":
        cats = ({c.strip().lower() for c in args.categories.split(",") if c.strip()}
                if args.categories else None)
        cmd_scrape(args.all, args.date, args.limit, categories=cats)
    elif args.cmd == "run":
        cmd_run(args.all, args.date, args.limit)
    elif args.cmd == "export":
        cmd_export(args.all, args.date, args.out, args.limit)
    elif args.cmd == "ingest":
        cmd_ingest(args.path)
    elif args.cmd == "write-catalog":
        cmd_write_catalog()


if __name__ == "__main__":
    main()
