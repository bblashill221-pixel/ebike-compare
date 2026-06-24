#!/usr/bin/env python3
"""
Missing-field resolver: for every model whose typed specs are missing expected
values (audit.py's definition), hunt the value in the model page's ENTIRE HTML
-- visible text AND embedded scripts/JSON -- in up to three escalating passes:

  pass 1  static fetch (urllib), visible text then raw HTML
  pass 2  Playwright-rendered DOM (covers bot-blocked brands), accordions opened
  pass 3  rendered DOM with looser context windows + meta descriptions

Acceptance is deliberately conservative (auto-applied data must not pollute):
a candidate is a value-pattern with the field's concept keyword nearby, parsed
through the SAME analyze.py parser the pipeline uses; a field resolves only
when every candidate on the page parses to ONE consistent value -- conflicting
values (e.g. other models in compare sections) are logged as ambiguous and
skipped.

Accepted values go to data/curated/html_extracted.json with full provenance
(value, snippet, url, pass, timestamp); analyze.py applies them as FALLBACK
only (a scraped value always wins). Unresolved (model, field) pairs are
reported with a reason in data/current/missing_resolution_report.json.

Usage:
  python resolve_missing_fields.py                  # everything (slow)
  python resolve_missing_fields.py --brand engwe    # one brand
  python resolve_missing_fields.py --limit 5        # first N pages per brand
  python resolve_missing_fields.py --passes 1       # static only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import scraper_common  # noqa: F401  (LD_LIBRARY_PATH for bundled chromium)
import analyze
from audit import EXPECTED_FIELDS, CONDITIONAL_FIELDS, _present, _typed
from audit_page_coverage import visible_text

DATA = Path(__file__).parent / "data"
OUT_CURATED = DATA / "curated" / "html_extracted.json"
OUT_REPORT = DATA / "current" / "missing_resolution_report.json"


def _p(parser, key):
    """Adapt an analyze parser to (snippet) -> value via a pseudo-spec row."""
    return lambda snippet: parser({key: snippet})


# A feet-inch rider-height range like 5'2" - 6'5" (curly/straight quotes, ''/").
_RH_RANGE_RE = r"\d\s*['’′]\s*\d{1,2}\s*[\"'″”]*\s*[-–]\s*\d\s*['’′]\s*\d{1,2}"
_RH_PARSE = re.compile(
    r"(\d)\s*['’′]\s*(\d{1,2})\s*[\"'″”]*\s*[-–]\s*(\d)\s*['’′]\s*(\d{1,2})")


def _rider_in(snippet: str, hi: bool):
    m = _RH_PARSE.search(snippet)
    if not m:
        return None
    f, i = (m.group(3), m.group(4)) if hi else (m.group(1), m.group(2))
    return int(f) * 12 + int(i)


def _speed_mph(snippet: str):
    # top speed = the highest stated speed in the window (an unlocked Class-3 28 mph
    # beats a Class-2 20 mph mentioned alongside it)
    if mph := [int(x) for x in re.findall(r"(\d{2})\s*mph", snippet, re.I)]:
        return max(mph)
    if kmh := [int(x) for x in re.findall(r"(\d{2})\s*km/?h", snippet, re.I)]:
        return round(max(kmh) / 1.609)
    return None


def _load_lb(snippet: str):
    # max load = the largest stated capacity in the window (the bike's payload, not a
    # smaller rack/accessory limit that may sit nearby)
    if lb := [int(x) for x in re.findall(r"(\d{2,3})\s*(?:lbs?|pounds)\b", snippet, re.I)]:
        return max(lb)
    if kg := [int(x) for x in re.findall(r"(\d{2,3})\s*kg\b", snippet, re.I)]:
        return round(max(kg) * 2.205)
    return None


# field -> (value pattern, concept keyword, reject pattern, snippet->value)
FIELD_DEFS = {
    # (?![\s-]*hours?) keeps "601 watt-hours" (battery) from reading as watts
    "motor_w": (r"\d{3,4}\s*-?\s*w(?:att)?s?\b(?!h)(?![\s-]*hours?)", r"motor|power",
                r"charger|inverter|output\s*port|watt[\s-]?hours?",
                lambda s: analyze._motor_w({"motor": s})[0]),
    "battery_wh": (r"\d{3,4}\s*-?\s*wh\b|\d{1,2}(?:\.\d)?\s*-?\s*ah\b", r"batter",
                   r"extender|second battery|extra battery",
                   _p(analyze._battery_wh, "battery")),
    "torque_nm": (r"\d{2,3}\s*n[·.\s]?m\b", r"torque|motor",
                  r"in boost|bolt|tighten",
                  _p(analyze._torque_nm, "torque")),
    "range_mi": (r"\d{2,3}\s*\+?\s*-?\s*mi(?:les?)?\b", r"range|per charge|single charge",
                 r"warranty|return|test ride",
                 _p(analyze._range_mi, "range")),
    "weight_lb": (r"\d{2,3}(?:\.\d)?\s*-?\s*(?:lbs?|pounds)\b|\d{2}(?:\.\d)?\s*kg\b",
                  r"weigh|\bbike weight",
                  r"payload|capacity|rider|max.?load|rack|limit|carry",
                  _p(analyze._weight_lb, "weight")),
    "rack_load_lb": (r"\d{2,3}\s*-?\s*(?:lbs?|pounds)\b|\d{2}\s*kg\b", r"rack",
                     r"payload|rider|gross",
                     _p(analyze._rack_load_lb, "rack")),
    "frame_material": (r"alumin|alloy|carbon|steel|chromoly|cr-?mo|magnesium", r"frame",
                       r"fork|rack|basket|fender",
                       _p(analyze._frame_material, "frame")),
    "brake_type": (r"hydraulic|mechanical|disc\s*brake|rim\s*brake|coaster", r"brake",
                   None, _p(analyze._brake_type, "brake")),
    "drive_type": (r"\bhub\b|mid[\s-]?drive|mid[\s-]?motor", r"motor|drive",
                   None, _p(analyze._drive_type, "motor")),
    "drivetrain_type": (r"belt[\s-]?driven?|\bchain\b|gates", r"drivetrain|belt|chain",
                        r"chainstay|chain\s*guard|chain\s*lock",
                        _p(analyze._drivetrain_type, "drivetrain")),
    # reject seatpost/"post suspension" marketing — brands (ENGWE) call a suspension
    # SEATPOST "post suspension" and a fork+seatpost combo a "full suspension system";
    # neither is a real rear shock. (The _suspension validator also requires a rear shock.)
    "suspension": (r"full[\s-]?suspension|front[\s-]?suspension|suspension\s*fork"
                   r"|hardtail|rigid\s*fork|air\s*fork|coil\s*fork|dual[\s-]?suspension",
                   r"suspension|fork", r"seat\s*post|seatpost|post[\s-]?suspension",
                   _p(analyze._suspension, "suspension")),
    "display_type": (r"\blcd\b|\bled\b|\btft\b|colou?r\s*(?:display|screen)", r"display|screen",
                     r"headlight|tail\s*light",
                     _p(analyze._display_type, "display")),
    "cell_brand": (r"samsung|\blg\b|panasonic|molicel|sony|eve\b", r"cell|batter",
                   None, _p(analyze._cell_brand, "battery")),
    "warranty_years": (r"\d{1,2}\s*-?\s*year|lifetime", r"warrant",
                       r"register|extend",
                       lambda s: analyze._warranty_years({"warranty": s})),
    # rider-height range in page prose ("fits riders 5'2\" - 6'5\""). The feet-inch
    # range is the value; require a height/rider/fit keyword and reject inseam /
    # seat / stand-over ranges (also feet-inch, but not rider height). Comparison-
    # widget JSON is dropped by _GLOBAL_REJECT.
    "fit_height_min_in": (_RH_RANGE_RE, r"height|rider|\bfits?\b",
                          r"inseam|stand[\s-]?over|seat[\s_]*(?:tube|height)|stack",
                          lambda s: _rider_in(s, hi=False)),
    "fit_height_max_in": (_RH_RANGE_RE, r"height|rider|\bfits?\b",
                          r"inseam|stand[\s-]?over|seat[\s_]*(?:tube|height)|stack",
                          lambda s: _rider_in(s, hi=True)),
    # extra card-icon values not in the audit's EXPECTED_FIELDS but worth pulling
    # from prose. The ambiguity guard (>1 distinct value -> skip) avoids bad picks
    # when a page quotes several speeds/loads.
    "max_speed_mph": (r"\d{2}\s*(?:mph|km/?h)\b",
                      r"top\s*speed|max\.?\s*speed|max\.?\s*velocity|\bspeed\b|up\s*to",
                      r"wind|charg|cadence|\brpm\b|tire|tyre",
                      _speed_mph),
    "max_load_lb": (r"\d{2,3}\s*(?:lbs?|pounds)\b|\d{2,3}\s*kg\b",
                    r"payload|max\.?\s*load|load\s*capacity|weight\s*capacity|"
                    r"max\.?\s*weight|carry|gross\s*weight|total\s*capacity",
                    r"\brack\b|bike\s*weight|net\s*weight|\bn\.?w\b|batter|frame|tire|tyre",
                    _load_lb),
    "sensor_type": (r"torque\s*[-\s]?sensor|cadence\s*[-\s]?sensor|speed\s*[-\s]?sensor"
                    r"|torque\s*(?:&|and|\+|/| )\s*cadence",
                    r"sensor|pedal\s*assist|\bpas\b", None,
                    _p(analyze._sensor_type, "sensor")),
}


def inventory(doc: dict, brand: str | None):
    """{url: {brand, missing: {field: [model_id, ...]}}} for audited gaps."""
    pages: dict = {}
    for m in doc.get("models", []):
        if brand and m.get("brand") != brand:
            continue
        url = m.get("url")
        if not url:
            continue
        t = _typed(m)
        missing = [k for k, _ in EXPECTED_FIELDS if not _present(t.get(k))]
        missing += [k for k, _, pred in CONDITIONAL_FIELDS
                    if pred(m) and not _present(t.get(k))]
        missing = [f for f in missing if f in FIELD_DEFS]
        if not missing:
            continue
        pg = pages.setdefault(url, {"brand": m["brand"], "missing": defaultdict(list)})
        for f in missing:
            pg["missing"][f].append(m["id"])
    return pages


def fetch_static(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


# Contexts that talk about something other than this bike's spec: image-gallery
# alt text (lists sibling variants), cross-model promos, nav/collection links.
_GLOBAL_REJECT = re.compile(
    r"gallery view|load image|promotion|all-new|shop now|view all|collection"
    # a price in the window means nav/promo/cross-model listing, not a spec
    r"|\$\s*[\d,]{3}"
    # JSON-structure contexts (raw-HTML scan): embedded storefront JSON describes
    # OTHER products (handles/titles/urls); match on JSON syntax itself since the
    # window may clip key names
    r'|"\s*:\s*"|\\/|"handle|"title|"\w+":|href=|/products/'
    # first-person / review prose: customer claims are not vendor facts
    r"|\bI\b|\bI'm\b|\bI've\b|\bmy\b|\bmine\b|verified buyer|\breviews?\b", re.I)
# Categorical fields take a tighter window: their values are common words
# ("full suspension", "LCD") that drift into marketing prose far from the value.
_CATEGORICAL = {"fit_height_min_in", "fit_height_max_in",
                "frame_material", "brake_type", "drive_type", "drivetrain_type",
                "suspension", "display_type", "cell_brand", "sensor_type"}


def candidates(text: str, field: str, window: int) -> dict:
    """{parsed_value: snippet} for every contextual candidate of `field`."""
    val_re, kw_re, rej_re, parse = FIELD_DEFS[field]
    if field in _CATEGORICAL:
        window = min(window, 50)
    out: dict = {}
    for m in re.finditer(val_re, text, re.I):
        s, e = max(0, m.start() - window), min(len(text), m.end() + window)
        ctx = " ".join(text[s:e].split())
        if not re.search(kw_re, ctx, re.I):
            continue
        if _GLOBAL_REJECT.search(ctx):
            continue
        if rej_re and re.search(rej_re, ctx, re.I):
            continue
        try:
            val = parse(ctx)
        except Exception:  # noqa: BLE001
            continue
        if val in (None, "", [], 0):
            continue
        out.setdefault(val, ctx[:220])
    return out


def hunt(texts: list[str], field: str, window: int):
    """(value, snippet) | ('AMBIGUOUS', values) | None across fallback texts."""
    # Categorical values are everyday words that saturate raw HTML (URL slugs
    # "...-full-suspension-ebike...", class names) -- visible text only for them.
    # Numeric facts ARE worth pulling from raw HTML (embedded spec JSON).
    if field in _CATEGORICAL:
        texts = texts[:1]
    for text in texts:
        cands = candidates(text, field, window)
        if len(cands) == 1:
            return ("ok", *next(iter(cands.items())))
        if len(cands) > 1:
            return ("ambiguous", sorted(map(str, cands)), None)
    return None


async def fetch_rendered(urls: list[str], workers: int = 3) -> dict:
    """url -> rendered page.content() with accordions/details opened."""
    from playwright.async_api import async_playwright
    out: dict = {}
    sem = asyncio.Semaphore(workers)

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])

        async def grab(url):
            async with sem:
                pg = await browser.new_page()
                try:
                    await pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                    await pg.wait_for_timeout(2500)
                    for _ in range(8):
                        await pg.mouse.wheel(0, 2500)
                        await pg.wait_for_timeout(200)
                    await pg.evaluate(
                        "() => document.querySelectorAll('details')"
                        ".forEach(d => { d.open = true; })")
                    out[url] = await pg.content()
                except Exception as e:  # noqa: BLE001
                    out[url] = ""
                    print(f"    [fetch error] {url[:70]}: {str(e)[:60]}", file=sys.stderr)
                finally:
                    await pg.close()

        await asyncio.gather(*(grab(u) for u in urls))
        await browser.close()
    return out


def revalidate_cache() -> int:
    """Re-apply the CURRENT accept logic (reject patterns + validator) to every cached
    snippet in html_extracted.json. Parsers harden over time (e.g. _suspension now
    requires a real rear shock, so a "full suspension (front fork + post suspension)"
    marketing snippet no longer reads as full); since the cache is value-first, stale
    values would otherwise persist forever. Updates changed values and drops entries that
    no longer validate. Offline (uses stored snippets). Returns the change count."""
    try:
        cache = json.loads(OUT_CURATED.read_text())
    except (FileNotFoundError, ValueError):
        return 0
    now = datetime.now(timezone.utc).isoformat()
    changes = 0
    for mid in list(cache):
        for field in list(cache[mid]):
            defn = FIELD_DEFS.get(field)
            if not defn:
                continue
            rec = cache[mid][field]
            snippet = rec.get("snippet", "")
            _, _, reject, validator = defn
            new = None if (reject and re.search(reject, snippet, re.I)) else validator(snippet)
            if not new:                         # no longer accepted -> drop
                del cache[mid][field]; changes += 1
            elif new != rec.get("value"):       # parser now reads it differently
                rec["value"] = new; rec["revalidated_at"] = now; changes += 1
        if not cache[mid]:
            del cache[mid]
    OUT_CURATED.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    print(f"[*] revalidated html cache: {changes} change(s)", file=sys.stderr)
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--revalidate", action="store_true",
                    help="re-apply current parsers to the cached snippets, then exit")
    ap.add_argument("--brand")
    ap.add_argument("--limit", type=int, default=0, help="max pages per brand")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("-i", "--input",
                    default=str(DATA / "current" / "active" / "ebike.json"))
    args = ap.parse_args()

    if args.revalidate:
        revalidate_cache()
        return

    # Self-heal the cache against the current parsers before extracting anything new.
    revalidate_cache()
    doc = json.load(open(args.input))
    pages = inventory(doc, args.brand)
    if args.limit:
        kept, per = {}, Counter()
        for url, pg in pages.items():
            per[pg["brand"]] += 1
            if per[pg["brand"]] <= args.limit:
                kept[url] = pg
        pages = kept
    total_missing = sum(len(ids) for pg in pages.values() for ids in pg["missing"].values())
    print(f"[*] {len(pages)} pages, {total_missing} missing (model,field) pairs", file=sys.stderr)

    try:
        extracted = json.loads(OUT_CURATED.read_text())
    except (FileNotFoundError, ValueError):
        extracted = {}
    unresolved: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    def accept(pg, url, field, val, snippet, pass_no, stats):
        for mid in pg["missing"][field]:
            extracted.setdefault(mid, {})[field] = {
                "value": val, "snippet": snippet, "url": url,
                "pass": pass_no, "extracted_at": now}
            stats[field] += 1
        del pg["missing"][field]

    # ---------------- pass 1: static ----------------
    resolved_per_pass = []
    stats: Counter = Counter()
    last_hit: dict = {}

    def static_one(item):
        url, pg = item
        dom = url.split("/")[2]
        wait = last_hit.get(dom, 0) + 1.0 - time.time()
        if wait > 0:
            time.sleep(wait)
        last_hit[dom] = time.time()
        try:
            html = fetch_static(url)
        except Exception as e:  # noqa: BLE001
            return url, None, str(e)
        return url, [visible_text(html), html], None

    if args.passes >= 1:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for url, texts, err in ex.map(static_one, list(pages.items())):
                pg = pages[url]
                if err:
                    continue  # retried rendered in pass 2
                for field in list(pg["missing"]):
                    r = hunt(texts, field, window=80)
                    if r and r[0] == "ok":
                        accept(pg, url, field, r[1], r[2], 1, stats)
                    elif r and r[0] == "ambiguous":
                        unresolved.append({"url": url, "field": field,
                                           "reason": f"ambiguous: {r[1][:4]}"})
                        del pg["missing"][field]  # don't retry looser -- by design
        resolved_per_pass.append(sum(stats.values()))
        print(f"[pass 1] resolved {resolved_per_pass[-1]}", file=sys.stderr)

    # ---------------- passes 2-3: rendered ----------------
    for pass_no, window in ((2, 80), (3, 160)):
        if args.passes < pass_no:
            break
        todo = {u: pg for u, pg in pages.items() if pg["missing"]}
        if not todo:
            break
        before = sum(stats.values())
        rendered = asyncio.run(fetch_rendered(list(todo)))
        for url, pg in todo.items():
            html = rendered.get(url) or ""
            if not html:
                continue
            texts = [visible_text(html)] + ([html] if pass_no == 3 else [])
            for field in list(pg["missing"]):
                r = hunt(texts, field, window)
                if r and r[0] == "ok":
                    accept(pg, url, field, r[1], r[2], pass_no, stats)
                elif r and r[0] == "ambiguous" and pass_no == 3:
                    unresolved.append({"url": url, "field": field,
                                       "reason": f"ambiguous: {r[1][:4]}"})
                    del pg["missing"][field]
        gained = sum(stats.values()) - before
        resolved_per_pass.append(gained)
        print(f"[pass {pass_no}] resolved {gained}", file=sys.stderr)
        if gained == 0:
            break

    # leftovers -> no candidate found anywhere
    for url, pg in pages.items():
        for field, ids in pg["missing"].items():
            unresolved.append({"url": url, "field": field,
                               "reason": f"no candidate ({len(ids)} models)"})

    OUT_CURATED.write_text(json.dumps(extracted, indent=1, ensure_ascii=False))
    OUT_REPORT.write_text(json.dumps({
        "generated_at": now, "resolved_per_pass": resolved_per_pass,
        "resolved_by_field": dict(stats), "unresolved": unresolved,
    }, indent=1, ensure_ascii=False))
    print(f"\nresolved by field: {dict(stats.most_common())}")
    print(f"unresolved pairs: {len(unresolved)}")
    print(f"[*] wrote {OUT_CURATED} and {OUT_REPORT}", file=sys.stderr)


if __name__ == "__main__":
    main()
