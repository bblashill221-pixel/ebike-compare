#!/usr/bin/env python3
"""
Buzz Bicycles e-bike scraper (Magento 2 store, server-rendered PDP HTML).

Buzz runs Magento (X-Magento-Vary cookie) with no products.json. Discovery reads
the /shop/ listing for product URLs; accessories (coolers, panniers, racks) are
dropped both by URL keyword and by the hard requirement that a real bike's PDP
carries the "product-section-specs" grid with a Motor row. Each PDP server-renders
a JSON-LD Product (name/sku/price/image/availability/description) plus the spec
grid -- section <h3> headers over <p class="font-extrabold">Label</p><p>Value</p>
pairs -- both parsed straight from HTML, no browser needed.

Products are simple (single SKU, no Magento swatch config), so each model gets one
"Default" color carrying the JSON-LD hero image.

Usage:  python scrape_buzz.py [-o out.json] [--limit N]
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import scraper_common  # noqa: F401  (sets LD_LIBRARY_PATH; unused otherwise)
from bike_taxonomy import classify_product_types

BASE = "https://www.buzzbicycles.com"
SHOP = f"{BASE}/shop/"
LOGO = f"{BASE}/media/logo/stores/11/buzz-logo-white.png"

# URL slugs that are accessories, not bikes (belt-and-suspenders: the Motor-row
# requirement in build_model already rejects them, but skipping the fetch is faster).
_ACCESSORY = re.compile(
    r"cooler|pannier|rack|basket|bag|cover|charger|battery|tube|tire|lock|helmet|"
    r"fender|mirror|light(?:-|$)|phone|kit|part", re.I)
_TAG = re.compile(r"<[^>]+>")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def _text(s: str) -> str:
    return " ".join(htmllib.unescape(_TAG.sub(" ", s or "")).split())


def discover() -> list[str]:
    """Candidate bike PDP URLs from the /shop/ listing, accessories filtered out."""
    page = fetch(SHOP)
    urls = re.findall(r"https://www\.buzzbicycles\.com/buzz-[a-z0-9-]+/", page)
    seen, out = set(), []
    for u in urls:
        slug = u.rstrip("/").rsplit("/", 1)[-1]
        if u in seen or _ACCESSORY.search(slug):
            continue
        seen.add(u)
        out.append(u)
    return out


def parse_jsonld(page: str) -> dict:
    """The JSON-LD Product node: name/sku/description/image/price/availability."""
    for m in re.finditer(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(m.group(1))
        except (ValueError, TypeError):
            continue
        for it in (data if isinstance(data, list) else [data]):
            if isinstance(it, dict) and it.get("@type") == "Product":
                return it
    return {}


def parse_specs(page: str) -> dict:
    """{label: value} from the product-section-specs grid (section headers dropped;
    normalize re-groups by label keyword anyway). Anchored on the grid container's
    closing quote so the stylesheet rule of the same name is skipped."""
    i = page.find('product-section-specs">')
    if i < 0:
        return {}
    seg = page[i:i + 12000]
    specs: dict = {}
    for label, value in re.findall(
            r'<p class="font-extrabold">\s*(.*?)\s*</p>\s*<p>\s*(.*?)\s*</p>', seg, re.S):
        k, v = _text(label), _text(value)
        if k and v and k not in specs:
            specs[k] = v
    return specs


def _body_torque(page: str) -> str | None:
    """A motor torque figure (e.g. "60Nm") stated in the page's feature/description
    prose -- Buzz lists torque there, not in the spec grid, for some models
    ("...500W motor delivering 60Nm of torque"). Nm on these single-product PDPs
    only ever refers to the bike's motor."""
    m = re.search(r"(\d{2,3})\s*N[·.\s]?m\b", _text(page), re.I)
    return f"{m.group(1)} Nm" if m else None


def _ascii_punct(s: str) -> str:
    """Curly quotes / en-dash -> ASCII so height_range_in parses 5'2" - 6'3"."""
    return (s.replace("’", "'").replace("‘", "'")
             .replace("”", '"').replace("“", '"')
             .replace("–", "-").replace("—", "-").replace("″", '"')
             .replace("′", "'"))


def _rider_height(page: str) -> str | None:
    """The "Ideal for riders: 5'2" - 6'3"" pill badge -> a rider-height range
    string for model.geometry (the "fits my height" filter envelope)."""
    for label, val in re.findall(
            r'<span class="font-bold">\s*(.*?):\s*</span>\s*(.*?)\s*</div>', page, re.S):
        if "rider" in _text(label).lower():
            return _ascii_punct(_text(val)) or None
    return None


def build_model(url: str) -> dict | None:
    page = fetch(url)
    ld = parse_jsonld(page)
    specs = parse_specs(page)
    # A real bike states a Motor; accessories that slipped past the URL filter don't.
    motor_key = next((k for k in specs if "motor" in k.lower()), None)
    if not motor_key:
        return None
    # Fold a prose-only torque figure into the Motor spec row when the grid omits
    # it, so torque_nm is captured downstream (e.g. Beekeeper grid says only
    # "500W Rear Hub Drive" while the body states "60Nm of torque").
    if not re.search(r"\bN[·.\s]?m\b|newton", specs[motor_key], re.I):
        torque = _body_torque(page)
        if torque:
            specs[motor_key] = f"{specs[motor_key]}, {torque}"

    offers = ld.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = None
    try:
        price = float(offers.get("price")) if offers.get("price") is not None else None
    except (ValueError, TypeError):
        price = None
    # Availability from the authoritative per-product JSON-LD offer
    # (schema.org/InStock vs /OutOfStock); only if it's absent do we fall back to
    # an explicit out-of-stock marker on the page. (A loose "in stock" page-text
    # search is wrong -- it matches stray copy and flips an out-of-stock bike, e.g.
    # the Cerana T2 Etrike, to available.)
    avail = str(offers.get("availability", "")).lower()
    if "instock" in avail:
        available = True
    elif any(x in avail for x in ("outofstock", "soldout", "discontinued")):
        available = False
    else:
        low = page.lower()
        available = "out of stock" not in low and "sold out" not in low

    name = _text(ld.get("name") or "")
    desc = _text(ld.get("description") or "")
    image = ld.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    colors = [{"name": "Default", "hex": None, "swatch_image": None, "image": image}] \
        if image else []

    rider = _rider_height(page)
    geometry = {"Rider Height Range": rider} if rider else {}

    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "model": name or slug,
        "handle": slug,
        "url": url,
        "model_year": None,
        "family": None,
        "product_types": classify_product_types(name, "", desc),
        "tags": [],
        "price_from": price,
        "regular_price": None,
        "currency": offers.get("priceCurrency") or "USD",
        "available": available,
        "options": {"colors": colors},
        "configurations": [{"options": {}, "price": price, "available": available,
                            "sku": ld.get("sku")}],
        "frame_sizes": None,
        "geometry": geometry,
        "specs": {"all": specs},
        "spec_count": len(specs),
        "warranty": None,
        "scrape_error": None if specs else "no specs extracted",
    }


def run(args) -> int:
    print(f"[*] Discovering e-bike models from {SHOP} ...", file=sys.stderr)
    urls = discover()
    if args.limit:
        urls = urls[: args.limit]
    print(f"[*] {len(urls)} candidate product page(s).", file=sys.stderr)
    models = []
    for u in urls:
        try:
            r = build_model(u)
        except Exception as e:  # noqa: BLE001
            print(f"    - {u}  FAIL ({e})", file=sys.stderr)
            continue
        if r is None:
            continue  # accessory (no motor spec)
        models.append(r)
        status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
        print(f"    - {(r['model'] or '?')[:36]:<36} {r['spec_count']:>3} specs  "
              f"{len(r['options'].get('colors', []))} colors  [{status}]", file=sys.stderr)
    results = sorted(models, key=lambda r: r["model"] or "")
    out = {"source": BASE, "logo": LOGO, "collection": "shop",
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Buzz Bicycles e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/buzz_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
