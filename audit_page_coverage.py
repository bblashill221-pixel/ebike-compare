#!/usr/bin/env python3
"""
Page-coverage audit: does our captured data contain every spec-like fact a
model's live page states?

For each model in the active build (deduped by URL -- frame/battery siblings
share a page), fetch the page, reduce it to user-visible text, extract every
unit-bearing fact (watts, Wh, volts, Ah, Nm, mph, miles, lbs, e-bike class,
N-speed, rider-height ranges), and check each against the model's captured
corpus (the full normalized record of every sibling on that URL). Misses are
reported with a context snippet.

Read-only: never mutates scrape data. Misses are LEADS for human review, not
auto-ingested -- marketing pages mention other models, accessories, and promo
copy, so some misses are expected noise.

Usage:
  python audit_page_coverage.py                 # all brands (slow: ~350 pages)
  python audit_page_coverage.py --brand aventon
  python audit_page_coverage.py --brand ride1up --limit 5

Output: per-brand console summary + data/current/page_coverage.json
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data"

# fact extractors: unit-class -> regex capturing the numeric value. The same
# set runs on the page text and on the captured corpus so values compare
# like-for-like. kph/km and EU units are skipped (US pages duplicate them).
FACT_RES = {
    "watts": re.compile(r"(\d{3,4})\s*-?\s*w(?:att)?s?\b(?!h)", re.I),
    "wh": re.compile(r"(\d{3,4})\s*-?\s*wh\b", re.I),
    "volts": re.compile(r"(\d{2})\s*-?\s*v(?:olts?)?\b", re.I),
    "ah": re.compile(r"(\d{1,2}(?:\.\d)?)\s*-?\s*ah\b", re.I),
    "nm": re.compile(r"(\d{2,3})\s*n[·.\s]?m\b", re.I),
    "mph": re.compile(r"(\d{2})\s*-?\s*mph\b", re.I),
    "miles": re.compile(r"(\d{2,3})\s*\+?\s*-?\s*mi(?:les?)?\b", re.I),
    "lbs": re.compile(r"(\d{2,3}(?:\.\d)?)\s*-?\s*(?:lbs?|pounds)\b", re.I),
    "class": re.compile(r"\bclass\s*-?\s*([123])\b", re.I),
    "speeds": re.compile(r"\b(\d{1,2})[\s-]?speed\b", re.I),
    "height": re.compile(r"(\d'\s?\d{1,2}\")", re.I),
}


# Known-noise contexts excluded from the miss report (documented in the JSON):
# the standardized range-test footnote ("...estimated based on a rider weighing
# 165 lbs..."), boost-mode torque (deliberately not captured -- only boost
# WATTS map to peak power, per user policy), and review prose mileage.
NOISE_RE = re.compile(r"rider weighing|in boost|miles on it", re.I)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def visible_text(page: str) -> str:
    page = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<!--.*?-->", " ", page, flags=re.S)
    # Unescape BEFORE the final tag strip: pages embed HTML-escaped templates
    # inside attributes (Alpine @click="... {html: `&lt;svg ...`}") whose "=>"
    # breaks tag boundaries -- unescaping turns the leaked payload back into
    # markup so the passes below remove it (incl. SVG path data that would
    # otherwise flood the volts regex).
    page = htmllib.unescape(page)
    page = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r"data:image/[^\"')]*", " ", page)
    page = re.sub(r"<[^>]+>", " ", page)
    return " ".join(page.split())


def norm_val(unit: str, raw: str) -> str:
    if unit == "height":
        # captured charts often write 4'11 without the closing inch mark
        return re.sub(r"\s", "", raw).rstrip('"')
    v = raw.lstrip("0") or "0"
    return v[:-2] if v.endswith(".0") else v


def extract_facts(text: str, with_context: bool):
    """{(unit, value): context} for every unit-bearing fact in `text`."""
    # "5,000 miles" must not read as "000 miles"
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    out: dict = {}
    for unit, rx in FACT_RES.items():
        for m in rx.finditer(text):
            key = (unit, norm_val(unit, m.group(1)))
            if key not in out:
                out[key] = (text[max(0, m.start() - 45):m.end() + 35].strip()
                            if with_context else "")
    return out


# structured-field suffix -> unit text, so parsed components ("power_w": 750)
# and typed fields compare against the page's textual facts ("750W")
_SUFFIX_UNITS = [("_wh", "Wh"), ("_kwh", None), ("_w", "W"), ("_nm", "Nm"),
                 ("_mph", "mph"), ("_mi", "mi"), ("_lbs", "lb"), ("_lb", "lb"),
                 ("_v", "V"), ("_ah", "Ah")]


def _ftin(inches) -> str:
    return f"{int(inches) // 12}'{int(inches) % 12}\""


def corpus_text(models: list) -> str:
    """Every captured string, plus structured numerics re-rendered WITH units."""
    toks: list[str] = []

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, str):
            toks.append(o)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            kl = key.lower()
            if kl == "classes" or kl == "class":
                toks.append(f"class {o}")
            elif kl in ("gears", "speeds"):
                toks.append(f"{o}-speed")
            elif kl.endswith("_in") and "height" in kl:
                toks.append(_ftin(o))
            else:
                for suf, unit in _SUFFIX_UNITS:
                    if kl.endswith(suf):
                        if unit:
                            v = int(o) if float(o).is_integer() else o
                            toks.append(f"{v}{unit}")
                        break

    for m in models:
        walk(m)
    return " ".join(toks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", help="audit one brand only")
    ap.add_argument("--limit", type=int, default=0, help="max pages per brand")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("-i", "--input",
                    default=str(DATA / "current" / "active" / "ebike.json"))
    args = ap.parse_args()

    doc = json.load(open(args.input))
    # group sibling models by page URL: the page states facts for every
    # configuration, so the corpus is the union of all siblings' records
    pages: dict = {}
    for m in doc.get("models", []):
        if args.brand and m.get("brand") != args.brand:
            continue
        url = m.get("url")
        if not url:
            continue
        pages.setdefault((m["brand"], url), []).append(m)

    per_brand: dict = {}
    items = list(pages.items())
    if args.limit:
        by_brand: dict = {}
        items = [it for it in items
                 if by_brand.setdefault(it[0][0], []).append(it) or
                 len(by_brand[it[0][0]]) <= args.limit]

    def audit_page(key_models):
        (brand, url), models = key_models
        try:
            text = visible_text(fetch(url))
        except Exception as e:  # noqa: BLE001
            return brand, url, None, str(e)
        page_facts = extract_facts(text, with_context=True)
        corpus_facts = set(extract_facts(corpus_text(models), with_context=False))
        missing = {k: v for k, v in page_facts.items()
                   if k not in corpus_facts and not NOISE_RE.search(v)}
        return brand, url, {"total": len(page_facts), "missing": missing}, None

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for brand, url, res, err in ex.map(audit_page, items):
            b = per_brand.setdefault(brand, {"pages": 0, "errors": 0, "facts": 0,
                                             "missed": 0, "misses": []})
            b["pages"] += 1
            if err:
                b["errors"] += 1
                continue
            b["facts"] += res["total"]
            b["missed"] += len(res["missing"])
            for (unit, val), ctx in res["missing"].items():
                b["misses"].append({"url": url, "unit": unit, "value": val, "context": ctx})

    print(f"{'brand':<14} {'pages':>5} {'facts':>6} {'missed':>6}  coverage")
    for brand in sorted(per_brand):
        b = per_brand[brand]
        cov = 100 * (1 - b["missed"] / b["facts"]) if b["facts"] else 0
        print(f"{brand:<14} {b['pages']:>5} {b['facts']:>6} {b['missed']:>6}  {cov:5.1f}%"
              + (f"  ({b['errors']} fetch errors)" if b["errors"] else ""))

    out_path = DATA / "current" / "page_coverage.json"
    json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
               "note": ("Misses are leads for review, not definitive gaps: pages "
                        "mention other models, accessories, and promo copy. "
                        "Filtered as known noise: range-test footnotes (rider "
                        "weighing), boost-mode torque (policy: only boost watts "
                        "map to peak), review-prose mileage."),
               "brands": per_brand}, open(out_path, "w"), indent=1, ensure_ascii=False)
    print(f"\n[*] Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
