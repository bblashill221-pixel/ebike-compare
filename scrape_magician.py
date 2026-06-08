#!/usr/bin/env python3
"""
Magician Ebikes (magicianebikes.com) spec scraper (Shopify, products.json only).

Models come from the `all-product` collection feed. Magician is a tiny brand whose
product pages put their spec sheet in IMAGES; the only machine-readable specs are
embedded in the description prose ("Bafang 72v5000w … front 72v20ah and rear
72v10ah … 200NM … up to 80 miles"). Those are pulled out with targeted regexes
into a flat label->value map. Coverage is intentionally sparse (the image-only
specs can't be read) — the data audit will flag the gaps.

Usage:
    python scrape_magician.py [-o out.json] [--limit N]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from scraper_common import fetch_json, clean_title, build_colors  # noqa: E402  (also sets LD_LIBRARY_PATH)
from bike_taxonomy import classify_product_types

BASE = "https://magicianebikes.com"
LOGO = "https://magicianebikes.com/cdn/shop/files/295f76d0-2bd0-4eff-93de-70ba6fb24942.png?v=1746688187"
COLLECTION = "all-product"


def parse_specs(body_html: str) -> dict:
    """Pull the specs Magician states in prose; the rest live in images."""
    txt = html.unescape(re.sub(r"<[^>]+>", " ", body_html or ""))
    txt = " ".join(txt.split())
    out: dict[str, str] = {}

    m = re.search(r"(bafang\s*)?(\d{2,3})\s*v\s*(\d{3,4})\s*w", txt, re.I)  # motor V/W
    if m:
        out["Motor"] = f"{'Bafang ' if m.group(1) else ''}{m.group(2)}V {m.group(3)}W"
    front = re.search(r"front\s*(\d{2,3})\s*v\s*(\d{1,2})\s*ah", txt, re.I)
    rear = re.search(r"rear\s*(\d{2,3})\s*v\s*(\d{1,2})\s*ah", txt, re.I)
    if front or rear:
        parts = []
        if front:
            parts.append(f"Front {front.group(1)}V {front.group(2)}Ah")
        if rear:
            parts.append(f"Rear {rear.group(1)}V {rear.group(2)}Ah")
        out["Battery"] = " + ".join(parts)
    t = re.search(r"(\d{2,3})\s*nm", txt, re.I)
    if t:
        out["Torque"] = f"{t.group(1)}Nm"
    r = re.search(r"(\d{2,3})\s*miles?", txt, re.I)
    if r:
        out["Range"] = f"Up to {r.group(1)} miles"
    if re.search(r"full[- ]?suspension", txt, re.I):
        out["Suspension"] = "Full suspension"
    if re.search(r"fat[- ]?style|fat\s*tire", txt, re.I):
        out["Tires"] = "Fat tires"
    if re.search(r"programmable display", txt, re.I):
        out["Display"] = "Fully programmable display"
    if re.search(r"class 1.*class 2.*class 3|unlimited mode", txt, re.I):
        out["Class"] = "Class 1 / 2 / 3 / Unlimited (configurable)"
    return out


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/collections/{COLLECTION}/products.json?limit=250")
    models = []
    for p in data.get("products", []):
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
        specs = parse_specs(p.get("body_html") or "")
        models.append({
            "model": clean_title(p.get("title")),
            "handle": p.get("handle"),
            "url": f"{BASE}/products/{p['handle']}",
            "product_types": classify_product_types(
                p.get("title") or "", p.get("product_type") or "",
                " ".join(p.get("tags") or [])),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
            "specs": {"all": specs},
            "spec_count": len(specs),
            "warranty": None,
            "scrape_error": None if specs else "no specs in description",
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
    out = {"source": BASE, "logo": LOGO, "collection": COLLECTION,
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Magician e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/magician_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
