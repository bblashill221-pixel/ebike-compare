#!/usr/bin/env python3
"""
GoTrax (gotrax.com) e-bike spec scraper (Shopify, static HTML — no browser).

The store sells scooters/hoverboards/parts too, so models are discovered from the
store feed filtered to product_type == "Electric bike" (the Denago sub-brand it also
resells is excluded). Specs are read from each product page's STATIC HTML, which
already carries them in two shapes:
  * a rich spec widget -- `.ai-specs-label-<hash>` / `.ai-specs-value-<hash>` div pairs
    (Motor, Battery, Charging Time, Weight, Brakes, Drivetrain, Rider Height Range, ...),
  * headline icon tiles -- `.title_d1` label + `.sub-title_d2` value (Range / Motor Size
    / Top Speed / Tire / Payload). Not every bike has the rich widget; those fall back
    to the tiles.
Colors + per-variant stock come from the Shopify feed. Output mirrors the other scrapers.

Usage:
    python scrape_gotrax.py [-o out.json] [--limit N]
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

BASE = "https://gotrax.com"
LOGO = "https://gotrax.com/cdn/shop/files/New_Logo_Helmet_and_Text_Black_2_4a4e10bb-c2c1-4f43-abc1-397d3d60d1a5.png?v=1697486333&width=512"
EBIKE_TYPE = "Electric bike"
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}


def fetch_html(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_HDRS), timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _txt(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def parse_specs(html: str) -> dict:
    """Label -> value from the static PDP (rich ai-specs widget first, then icon tiles)."""
    specs: dict = {}
    for m in re.finditer(
            r'ai-specs-label-[^"]*">(.*?)</div>\s*<div class="ai-specs-value-[^"]*">(.*?)</div>',
            html, re.S):
        lab, val = _txt(m.group(1)), _txt(m.group(2))
        if lab and val and lab not in specs:
            specs[lab] = val
    for m in re.finditer(r'title_d1">(.*?)</p>\s*<h3[^>]*sub-title_d2">(.*?)</h3>', html, re.S):
        lab, val = _txt(m.group(1)), _txt(m.group(2))
        if lab and val and lab not in specs:
            specs[lab] = val
    return specs


def discover_models() -> list[dict]:
    models, page = [], 1
    while page <= 8:
        data = fetch_json(f"{BASE}/products.json?limit=250&page={page}")
        products = data.get("products", [])
        if not products:
            break
        for p in products:
            if (p.get("product_type") or "") != EBIKE_TYPE:
                continue
            title = clean_title(p.get("title"))
            if title.lower().startswith("denago") or (p.get("vendor") or "").lower() == "denago":
                continue
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
                "handle": p.get("handle"),
                "url": f"{BASE}/products/{p['handle']}",
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
    ap = argparse.ArgumentParser(description="Scrape GoTrax e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/gotrax_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
