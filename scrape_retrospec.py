#!/usr/bin/env python3
"""
Retrospec (retrospec.com) e-bike spec scraper (Shopify, static HTML — no browser).

E-bikes are discovered from the store feed filtered to product_type starting with
"Ebike - Electric" (the "EBike Part - ..." rows are parts). Retrospec has no spec table;
it presents specs as icon "get-to-know" blocks whose `.specs-titlenew` carries a
descriptive value ("500W Planetary Geared Hub Motor", "48V/500Wh LG Li-Ion Battery",
"Tektro Hydraulic Disc Brakes", "20mph Top Assisted Speed", "Up to 75-Mile Range", ...).
Each value is mapped to a canonical field by keyword, and the size chart <table> yields
the rider-height range. Colors + per-variant stock come from the Shopify feed. Output
mirrors the other scrapers.

Usage:
    python scrape_retrospec.py [-o out.json] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scraper_common import fetch_json, clean_title, build_colors, shopify_sold_out_options
from bike_taxonomy import classify_product_types

BASE = "https://www.retrospec.com"
LOGO = "https://www.retrospec.com/cdn/shop/files/socialshare_24a991df-92a3-478a-8154-22ff9d446382.jpg"
EBIKE_TYPE_PREFIX = "ebike - electric"
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

# Descriptive spec-highlight value -> canonical field (first match wins; order matters).
_LABELS = [
    (re.compile(r"top.*speed|\bmph\b", re.I), "Top Speed"),
    (re.compile(r"range|mile", re.I), "Range"),
    (re.compile(r"\bmotor\b", re.I), "Motor"),
    (re.compile(r"batter|\bwh\b|\bah\b|li-?ion|lithium", re.I), "Battery"),
    (re.compile(r"brake", re.I), "Brakes"),
    (re.compile(r"\btires?\b|\btyres?\b", re.I), "Tires"),
    (re.compile(r"fork|suspension", re.I), "Fork"),
    (re.compile(r"gear|cassette|derailleur|drivetrain", re.I), "Drivetrain"),
    (re.compile(r"display|lcd", re.I), "Display"),
    (re.compile(r"\bsystem\b", re.I), "System"),
    (re.compile(r"frame", re.I), "Frame"),
    (re.compile(r"payload|capacity|\bweight\b", re.I), "Payload"),
]


def fetch_html(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_HDRS), timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _txt(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _label_for(value: str) -> str | None:
    for rx, lab in _LABELS:
        if rx.search(value):
            return lab
    return None


def parse_specs(html: str) -> dict:
    specs: dict = {}
    extra = 0
    for m in re.finditer(r'<div class="get-to-know-blocks">(.*?)</div>\s*</div>', html, re.S):
        blk = m.group(1)
        tm = re.search(r'specs-titlenew">(.*?)</p>', blk, re.S)
        if not tm:
            continue
        val = _txt(tm.group(1))
        if not val:
            continue
        lab = _label_for(val)
        if lab is None:
            extra += 1
            lab = f"Highlight {extra}"
        specs.setdefault(lab, val)
    # size chart: the table also carries SKU/Price columns, so pull the rider-height range
    # and standover by PATTERN across all cells (column-index heuristics leak SKU/$ values).
    cells = [_txt(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", html, re.S)]
    heights = [c for c in cells
               if re.search(r"\d\s*['’].*(?:to|-|–).*\d", c) and "$" not in c and "sku" not in c.lower()]
    stand = [c for c in cells if re.fullmatch(r"\d+(?:\.\d+)?\s*[\"”]", c)]
    if heights and "Rider Height Range" not in specs:
        specs["Rider Height Range"] = " / ".join(dict.fromkeys(heights))
    if stand and "Standover Height" not in specs:
        specs["Standover Height"] = " / ".join(dict.fromkeys(stand))
    return specs


def discover_models() -> list[dict]:
    models, seen, page = [], set(), 1
    while page <= 8:
        data = fetch_json(f"{BASE}/products.json?limit=250&page={page}")
        products = data.get("products", [])
        if not products:
            break
        for p in products:
            if not (p.get("product_type") or "").lower().startswith(EBIKE_TYPE_PREFIX):
                continue
            h = p.get("handle")
            if not h or h in seen:
                continue
            seen.add(h)
            title = clean_title(p.get("title"))
            variants = p.get("variants", [])
            prices = [float(v["price"]) for v in variants if v.get("price")]
            images = [img.get("src") for img in p.get("images", []) if img.get("src")]
            fallback = images[0] if images else None
            options, color_values, color_idx = {}, [], None
            for i, o in enumerate(p.get("options", [])):
                name = (o.get("name") or "").strip()
                if not name or name == "Title":
                    continue
                if "color" in name.lower() or "colour" in name.lower():
                    color_values = o.get("values", [])
                    color_idx = i + 1
                else:
                    options[name] = o.get("values", [])
            options["colors"] = build_colors(color_values, color_idx, variants, fallback)
            so, ins = shopify_sold_out_options(p)
            models.append({
                "model": title,
                "handle": h,
                "url": f"{BASE}/products/{h}",
                "product_types": classify_product_types(
                    title, p.get("product_type") or "", " ".join(p.get("tags") or [])),
                "price_from": min(prices) if prices else None,
                "currency": "USD",
                "options": options,
                "sold_out_options": so,
                "in_stock": ins,
            })
        if len(products) < 250:
            break
        page += 1
    return models


def scrape_model(model: dict) -> dict:
    result = dict(model)
    try:
        specs = parse_specs(fetch_html(model["url"]))
        result["specs"] = {"all": specs}
        result["spec_count"] = len(specs)
        result["warranty"] = None
        result["scrape_error"] = None if specs else "no specs found"
    except Exception as e:  # noqa: BLE001
        result["specs"] = {"all": {}}
        result["spec_count"] = 0
        result["warranty"] = None
        result["scrape_error"] = f"{type(e).__name__}: {e}"
    return result


def run(args) -> int:
    print(f"[*] Discovering e-bike models from {BASE} ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    print(f"[*] Found {len(models)} e-bike model(s).", file=sys.stderr)
    results = []
    for m in models:
        r = scrape_model(m)
        status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
        print(f"    - {r['model'][:32]:<32} {r['spec_count']:>3} specs  "
              f"{len(r['options'].get('colors', []))} colors  [{status}]", file=sys.stderr)
        results.append(r)
    results.sort(key=lambda r: r["model"] or "")
    out = {"source": BASE, "logo": LOGO,
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Retrospec e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/retrospec_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
