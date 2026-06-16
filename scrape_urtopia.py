#!/usr/bin/env python3
"""
Urtopia (newurtopia.com) spec scraper (Shopify, products.json + page HTML).

The model list, colors, sizes and prices come from the `e-bikes` collection feed
(Urtopia's US storefront is newurtopia.com; urtopia.com is the marketing site).
Each product page renders a `.parameters` spec block into the static HTML as
``<div class="u24DemiBold_v2">label</div><div class="u17Light_v2">value</div>``
pairs (Motor, Battery, Range, Brakes, Material, rider height, drivetrain, smart
features, …), read straight from the page -- no browser needed. Frame sizes come
from the "Size" variant option (rider-height envelope is a single published
range, so per-size heights are left null).

Usage:
    python scrape_urtopia.py [-o out.json] [--limit N]
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

BASE = "https://newurtopia.com"
COLLECTION = "e-bikes"

# Spec labels renamed to the canonical forms the pipeline's parsers key on.
_LABEL_RENAME = {
    "Material": "Frame", "Net Weight": "Weight", "Total Weight Limit": "Max Load",
    "Wheels": "Tires", "Urtopia Smartbar": "Handlebar", "Smartbar": "Handlebar",
    "Seat post": "Seat Post", "Grip": "Grips",
}

_SIZE_NAMES = {"XXS": "XX-Small", "XS": "X-Small", "S": "Small", "M": "Medium",
               "L": "Large", "XL": "X-Large", "XXL": "XX-Large"}


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_specs(page: str) -> dict:
    """Read the `.parameters` spec pairs (label .u24DemiBold_v2 + value .u17Light_v2)."""
    out: dict[str, str] = {}
    for label_html, body in re.findall(
        r'<div class="u24DemiBold_v2">(.*?)</div>\s*<div class="u17Light_v2">(.*?)</div>',
        page, re.S):
        label = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", label_html)).split())
        # values carry test-condition footnotes after a <br> or "*"; drop them
        value = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.split(r"<br|\*", body)[0])).split())
        if not (label and value and len(label) < 40):
            continue
        out.setdefault(_LABEL_RENAME.get(label, label), value)
    return out


def frame_sizes_from_option(options: dict) -> list | None:
    """Frame sizes from the "Size" variant option (heights null -- the page lists a
    single overall rider-height range, not per-size)."""
    sizes = next((v for k, v in options.items() if k.lower() == "size"), None)
    if not sizes:
        return None
    out = []
    for s in sizes:
        key = re.sub(r"[^A-Za-z]", "", str(s)).upper()
        out.append({"size": _SIZE_NAMES.get(key, str(s)),
                    "height_min": None, "height_max": None})
    return out or None


def discover_logo() -> str:
    page = fetch_html(BASE)
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
    return m.group(1) if m else ""


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/collections/{COLLECTION}/products.json?limit=250")
    models = []
    for p in data.get("products", []):
        title = p.get("title") or ""
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
        url = f"{BASE}/products/{p['handle']}"
        specs = parse_specs(fetch_html(url))
        model = {
            "model": clean_title(title),
            "handle": p.get("handle"),
            "url": url,
            "product_types": classify_product_types(
                title, p.get("product_type") or "", " ".join(p.get("tags") or [])),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
            "specs": {"all": specs},
            "spec_count": len(specs),
            "warranty": None,
            "scrape_error": None if specs else "no specs found",
        }
        fs = frame_sizes_from_option(options)
        if fs:
            model["frame_sizes"] = fs
        models.append(model)
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
    ap = argparse.ArgumentParser(description="Scrape Urtopia e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/urtopia_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
