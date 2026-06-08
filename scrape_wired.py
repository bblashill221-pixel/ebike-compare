#!/usr/bin/env python3
"""
WIRED Ebikes (wiredebikes.com) spec scraper (Shopify, products.json only).

Models come from the `wired-ebikes` collection feed. WIRED renders product pages
with GemPages (no spec table in the DOM and most detail baked into images), but
every product's `body_html` carries a clean "Specifications" <ul> ("Motor: …",
"Battery: …", "Range: …", …) — so specs are parsed straight from the feed, no
browser needed. Falls back to any plain "Label: value" list items when a model
has no dedicated Specifications block. Output mirrors the other scrapers.

Usage:
    python scrape_wired.py [-o out.json] [--limit N]
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

BASE = "https://wiredebikes.com"
LOGO = "https://wiredebikes.com/cdn/shop/files/Wired_1200_600.png?v=1739722992"
COLLECTION = "wired-ebikes"


def detect_shipping() -> dict:
    """Infer shipping from the storefront -- free shipping is only claimed when the
    site says so. WIRED advertises a flat fee ("Flat rate $275 shipping"), so it is
    NOT free; a "free shipping" claim -> free; otherwise leave it unknown."""
    try:
        req = urllib.request.Request(BASE + "/", headers={"User-Agent": "Mozilla/5.0"})
        page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
    except Exception:
        return {"cost": None, "free": None}
    m = (re.search(r"flat[\s-]?rate[^$]{0,15}\$\s*(\d{2,4})\s*shipping", page, re.I)
         or re.search(r"\$\s*(\d{2,4})\s*flat[\s-]?rate\s*shipping", page, re.I))
    if m:
        cost = int(m.group(1))
        return {"cost": cost, "free": cost == 0}
    if re.search(r"free\s+shipping", page, re.I):
        return {"cost": 0, "free": True}
    return {"cost": None, "free": None}


def _li_pairs(block: str) -> dict:
    """`<li>Label: value</li>` items in `block` -> {label: value}."""
    out: dict[str, str] = {}
    for li in re.findall(r"<li[^>]*>(.*?)</li>", block, re.I | re.S):
        text = html.unescape(re.sub(r"<[^>]+>", " ", li))
        text = " ".join(text.split())
        m = re.match(r"([A-Za-z][\w /&'+-]{1,28}?)\s*[:：]\s*(.+)", text)
        if not m:
            continue
        label, value = " ".join(m.group(1).split()), m.group(2).strip()
        if value and len(value) <= 200 and label.lower() not in out:
            out[label] = value
    return out


def parse_specs(body_html: str) -> dict:
    """Prefer the dedicated "Specifications" list; else any Label: value list items."""
    body_html = body_html or ""
    m = re.search(r"specification[s]?\s*</h\d>\s*(<ul[^>]*>.*?</ul>)", body_html, re.I | re.S)
    if m:
        specs = _li_pairs(m.group(1))
        if specs:
            return specs
    return _li_pairs(body_html)


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/collections/{COLLECTION}/products.json?limit=250")
    shipping = detect_shipping()
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
            # WIRED's whole line is moto/moped-style; the titles carry no moto
            # keyword, so add one to the classifier signal to land them as eMoto.
            "product_types": classify_product_types(
                p.get("title") or "", p.get("product_type") or "",
                " ".join(p.get("tags") or []) + " moped-style"),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
            "specs": {"all": specs},
            "spec_count": len(specs),
            "warranty": None,
            "shipping": shipping,   # found on the site, not assumed free
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
    ap = argparse.ArgumentParser(description="Scrape WIRED e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/wired_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
