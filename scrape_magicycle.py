#!/usr/bin/env python3
"""
Magicycle (magicyclebike.com) spec scraper (Shopify, products.json + page HTML).

The model list, colors and prices come from the `e-bikes` collection feed. Each
product page renders its specifications into the static HTML as a list of
``<div class="detail-specification-item"><div>label</div><span>value</span></div>``
rows (Motor, Battery, Range, Brake, Frame, Tires, Weight, payload, rider height,
…), so they're read straight from the page -- no browser needed. Accessory
"Bundle Sale" listings in the collection are skipped.

Usage:
    python scrape_magicycle.py [-o out.json] [--limit N]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scraper_common import fetch_json, clean_title, build_colors  # noqa: E402  (also sets LD_LIBRARY_PATH)
from bike_taxonomy import classify_product_types

BASE = "https://magicyclebike.com"
COLLECTION = "e-bikes"

# Spec labels renamed to the canonical forms the pipeline's parsers key on.
# Only "Bike Frame" is strictly required (the frame parser matches the exact
# field "frame"); the rest are tidied for consistent display.
_LABEL_RENAME = {
    "Bike Frame": "Frame", "Hub Motor": "Motor", "Front Fork": "Fork",
    "Total Payload Capacity": "Max Load", "Recommended Rider Heights": "Rider Height",
    "Recommended Rider Height": "Rider Height", "Frame size": "Frame Size",
}


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_specs(page: str) -> dict:
    """Read the `.detail-specification-item` spec rows (label <div> + value <span>)."""
    out: dict[str, str] = {}
    for label_html, body in re.findall(
        r'<div class="detail-specification-item"[^>]*>\s*'
        r"<div[^>]*>(.*?)</div>\s*<span[^>]*>(.*?)</span>", page, re.S):
        label = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", label_html)).split())
        value = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())
        if not (label and value and len(label) < 40):
            continue
        out.setdefault(_LABEL_RENAME.get(label, label), value)
    return out


def discover_logo() -> str:
    page = fetch_html(BASE)
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
    if m:
        return m.group(1)
    m = re.search(r'src="(//[^"]*cdn/shop/[^"]*logo[^"]*\.(?:png|webp|svg))"', page, re.I)
    return ("https:" + m.group(1)) if m else ""


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/collections/{COLLECTION}/products.json?limit=250")
    models = []
    for p in data.get("products", []):
        title = p.get("title") or ""
        # Skip accessory "Bundle Sale" listings -- they re-list a bike + extras.
        if re.search(r"\bbundle\b", title, re.I):
            continue
        variants = p.get("variants", [])
        prices = [float(v["price"]) for v in variants if v.get("price")]
        images = [img.get("src") for img in p.get("images", []) if img.get("src")]
        fallback = images[0] if images else None
        options, color_values, color_idx = {}, [], None
        for i, o in enumerate(p.get("options", [])):
            if not o.get("name"):
                continue
            if o["name"].lower().startswith(("color", "colour")):
                color_values = o.get("values", [])
                color_idx = i + 1
            else:
                options[o["name"]] = o.get("values", [])
        options["colors"] = build_colors(color_values, color_idx, variants, fallback)
        # per-variant configurations WITH availability (Shopify variants carry
        # `available`) so a fully sold-out bike is recognized as such downstream.
        opt_names = [o.get("name") for o in p.get("options", [])]
        configurations = []
        for v in variants:
            opts = {}
            for j, nm in enumerate(opt_names, start=1):
                val = v.get(f"option{j}")
                if nm and val not in (None, "Default Title"):
                    opts[nm] = val
            configurations.append({
                "options": opts,
                "price": float(v["price"]) if v.get("price") else None,
                "available": bool(v.get("available")),
                "sku": v.get("sku"),
            })
        url = f"{BASE}/products/{p['handle']}"
        specs = parse_specs(fetch_html(url))
        models.append({
            "model": clean_title(title),
            "handle": p.get("handle"),
            "url": url,
            "product_types": classify_product_types(
                title, p.get("product_type") or "", " ".join(p.get("tags") or [])),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
            "configurations": configurations,
            "specs": {"all": specs},
            "spec_count": len(specs),
            "warranty": None,
            "scrape_error": None if specs else "no specs found",
        })
    return models


def run(args) -> int:
    print(f"[*] Discovering e-bike models from {BASE}/collections/{COLLECTION} ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    for r in models:
        status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
        print(f"    - {r['model'][:32]:<32} {r['spec_count']:>3} specs  "
              f"{len(r['options'].get('colors', []))} colors  [{status}]", file=sys.stderr)
    results = sorted(models, key=lambda r: r["model"] or "")
    out = {"source": BASE, "logo": discover_logo(), "collection": COLLECTION,
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Magicycle e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/magicycle_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
