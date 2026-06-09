#!/usr/bin/env python3
"""
Juiced Bikes e-bike spec scraper (Shopify).

Juiced is a Shopify store, but its e-bikes live at the catalog root rather than
a working `electric-bikes` collection, so discovery walks `products.json` and
keeps the bike-priced products (price gate + an accessory-word denylist). Specs
are server-rendered into the product page's `.pdp-data-specs-item` list
(label/value), so no Playwright is needed — plain HTTP throughout.

Each bike's `.js` endpoint carries per-variant availability and the colour's own
photo. Colours come from the Color option; the Frame option (Full Suspension vs
Hardtail) is emitted as `Version` so the shared tier-expansion splits it into
sibling cards the same way other brands' build tiers are split.

Output JSON mirrors the other scrapers.

Usage:
    python scrape_juiced.py                  # all models -> juiced_ebikes.json
    python scrape_juiced.py --limit 2        # quick test
    python scrape_juiced.py -o out.json      # custom output path
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

from scraper_common import fetch_json, build_colors
from bike_taxonomy import classify_product_types

BASE = "https://juicedbikes.com"
LOGO = "https://juicedbikes.com/cdn/shop/files/juiced-logo.png"

# Products under this price are parts/accessories, not bikes.
MIN_BIKE_PRICE = 800.0
# Accessory/part products to skip even if priced like a bike.
_ACCESSORY = re.compile(
    r"\bkit\b|nameplate|headplate|sticker|\bbag\b|\bpad\b|fender|charger|battery"
    r"|tire|tube|mirror|rack|lock|helmet|throttle|light|coming[\s-]?soon", re.I)

# Box-contents rows in the spec list ("Bike Manual: x1") aren't specs.
_BOX_CONTENT = re.compile(r"^x\d+$", re.I)


def _norm(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\xa0", " ").strip()


def _fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


# ----------------------------- catalog discovery -----------------------------

def discover_handles() -> list[str]:
    """Bike handles from the paginated products.json feed (price-gated)."""
    handles, page = [], 1
    while True:
        data = fetch_json(f"{BASE}/products.json?limit=250&page={page}")
        products = data.get("products", [])
        if not products:
            break
        for p in products:
            title = p.get("title") or ""
            prices = [float(v["price"]) for v in p.get("variants", []) if v.get("price")]
            if (prices and min(prices) >= MIN_BIKE_PRICE
                    and not _ACCESSORY.search(title) and not _ACCESSORY.search(p.get("handle") or "")):
                handles.append(p["handle"])
        if len(products) < 250:
            break
        page += 1
    return handles


# ------------------------------ page extraction ------------------------------

def extract_specs(page_html: str) -> dict:
    """The PDP's `.pdp-data-specs-item` rows as {label: value}, dropping the
    box-contents ("x1") rows. Later duplicate labels keep the first value."""
    specs: dict = {}
    for m in re.finditer(r'<li class="pdp-data-specs-item[^"]*">(.*?)</li>', page_html, re.S):
        lab = re.search(r'pdp-data-specs-label">(.*?)</strong>', m.group(1), re.S)
        val = re.search(r'pdp-data-specs-value">(.*?)</span>', m.group(1), re.S)
        if not lab or not val:
            continue
        label, value = _norm(lab.group(1)), _norm(val.group(1))
        if label and value and not _BOX_CONTENT.match(value) and label not in specs:
            specs[label] = value
    return specs


def extract_hero_specs(page_html: str) -> dict:
    """Top "hero" specs (Max Range, Top Speed, Peak Motor Power, Battery) that sit
    in `.product-data-spec` blocks, separate from the `.pdp-data-specs` list."""
    out: dict = {}
    for value, label in re.findall(
            r'product-data-spec-value[^>]*>(.*?)</[^>]+>.*?product-data-spec-label[^>]*>(.*?)</',
            page_html, re.S):
        v = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())
        lab = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", label)).split())
        if lab and v and lab not in out:
            out[lab] = v
    return out


def scrape_model(handle: str) -> dict:
    js = fetch_json(f"{BASE}/products/{handle}.js")
    variants = js.get("variants", [])
    # `options` may be a list of names or of {name, position, values} dicts
    opt_names = [o["name"] if isinstance(o, dict) else o for o in js.get("options", [])]
    # option index for Color / Frame (1-based, matching variant.option{n})
    def idx_of(pred):
        for i, name in enumerate(opt_names, start=1):
            if pred(name):
                return i, name
        return None, None
    color_idx, _ = idx_of(lambda n: n.lower().startswith("color"))
    frame_idx, frame_name = idx_of(lambda n: n.lower() in ("frame", "frame type", "version"))

    images = [m.get("src") for m in js.get("media", []) if m.get("src")]
    fallback = images[0] if images else None
    color_values = []
    if color_idx is not None:
        for v in variants:
            cv = v.get(f"option{color_idx}")
            if cv and cv not in color_values:
                color_values.append(cv)
    colors = build_colors(color_values, color_idx, variants, fallback)

    prices = [float(v["price"]) / 100 for v in variants if v.get("price") is not None]
    options: dict = {"colors": colors}
    # Frame (Full Suspension / Hardtail) -> "Version" so tier-expansion splits it
    if frame_idx is not None:
        options["Version"] = []
        for v in variants:
            fv = v.get(f"option{frame_idx}")
            if fv and fv not in options["Version"]:
                options["Version"].append(fv)

    configs = []
    for v in variants:
        opts = {}
        if color_idx is not None and v.get(f"option{color_idx}"):
            opts["Color"] = v[f"option{color_idx}"]
        if frame_idx is not None and v.get(f"option{frame_idx}"):
            opts["Version"] = v[f"option{frame_idx}"]
        configs.append({
            "options": opts,
            "price": float(v["price"]) / 100 if v.get("price") is not None else None,
            # per-variant compare-at so the tier split can apply the sale per version
            "regular_price": float(v["compare_at_price"]) / 100 if v.get("compare_at_price") else None,
            "sku": v.get("sku"),
            "variant_id": v.get("id"),
            "available": v.get("available"),
            "image": (v.get("featured_image") or {}).get("src"),
        })

    page_html = _fetch(f"{BASE}/products/{handle}") or ""
    specs = extract_specs(page_html)
    for label, value in extract_hero_specs(page_html).items():
        specs.setdefault(label, value)   # adds Max Range, Top Speed, … if not in the list
    name = js.get("title") or handle
    compare = [float(v["compare_at_price"]) / 100 for v in variants
               if v.get("compare_at_price")]
    return {
        "model": name,
        "handle": handle,
        "url": f"{BASE}/products/{handle}",
        "product_types": classify_product_types(
            name, js.get("type") or "", handle + " " + " ".join(specs.values())[:300]),
        "price_from": min(prices) if prices else None,
        "regular_price": max(compare) if compare else None,
        "currency": "USD",
        "options": options,
        "configurations": configs,
        "specs": {"all": specs},
        "spec_count": len(specs),
        "warranty": None,
        "scrape_error": None if specs else "no specs extracted",
    }


# ----------------------------------- main ------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Scrape Juiced Bikes e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/juiced_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only first N models.")
    args = ap.parse_args()

    print(f"[*] Discovering models from {BASE}/products.json ...", file=sys.stderr)
    handles = discover_handles()
    if args.limit:
        handles = handles[: args.limit]
    print(f"[*] Found {len(handles)} bike product(s).", file=sys.stderr)

    models = []
    for h in handles:
        m = scrape_model(h)
        status = "ok" if m["spec_count"] else f"FAIL ({m['scrape_error']})"
        ncol = len(m["options"].get("colors", []))
        print(f"    - {m['model'][:30]:<30} {m['spec_count']:>3} specs  "
              f"{ncol} colors  [{status}]", file=sys.stderr)
        models.append(m)

    models.sort(key=lambda r: r["model"] or "")
    out = {
        "source": BASE, "logo": LOGO,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(models),
        "models": models,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for m in models if m["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(models)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
