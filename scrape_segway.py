#!/usr/bin/env python3
"""
Segway e-bike spec scraper.

Segway's store (store.segway.com) is Magento behind a Next.js front, so unlike
the Shopify brands there is no products.json — but the Magento GraphQL endpoint
is open. Discovery and pricing come from GraphQL; the detailed spec tables are
NOT in the store at all, they're embedded as JSON (AEM "component_*_json"
blobs) in the brand-site product pages (www.segway.com/ebike/products/<series>
.html), which also carry the color list ({colorName, rgba, images}).

Per model the store also embeds a small per-product highlight strip
("specifications": Motor / Battery Capacity / Max Range / Torque) in its RSC
payload; those rows are appended AFTER the brand-page rows so per-product
figures win label collisions (the Myon S shares the Myon brand page but states
its own battery/range).

Colors are sold as separate store products (like Monarc); they're merged here
by stripping trailing color words off the url_key, so each bike is one model
entry with `options.colors` from the brand page.

Output JSON mirrors the other scrapers. No Playwright needed — everything is
plain HTTP.

Usage:
    python scrape_segway.py                  # all models -> segway_ebikes.json
    python scrape_segway.py --limit 2        # quick test
    python scrape_segway.py -o out.json      # custom output path
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scraper_common import fetch_json
from bike_taxonomy import classify_product_types

STORE = "https://store.segway.com"
BRAND = "https://www.segway.com"
GRAPHQL = f"{STORE}/graphql"
LOGO = "https://store.segway.com/favicon.ico"

# bike categories on the store (url_path); Myon S is category-less and is only
# found via the sitemap probe below
CATEGORIES = ("ebike", "electric-dirt-bike")

# sitemap slugs that look like bike product pages (vs. the thousands of parts)
_BIKE_SLUG = re.compile(r"^(segway-ebike-[a-z0-9-]+|[a-z0-9-]*electric-bike[a-z0-9-]*)$")
# accessory words that disqualify a slug/name even when it matches above
_ACCESSORY = re.compile(
    r"basket|kit|fender|mirror|battery|charger|bag|rack|cover|helmet|lock"
    r"|top[- ]tube|passenger", re.I)

# trailing url_key tokens that denote a colorway, not a distinct bike
_COLOR_TOKENS = {
    "red", "blue", "silver", "grey", "gray", "black", "white", "green", "dark",
    "light", "orange", "yellow", "sage", "olive", "beige", "sand", "mint",
}


def gql(query: str) -> dict:
    url = f"{GRAPHQL}?{urllib.parse.urlencode({'query': query})}"
    return fetch_json(url)


_PRODUCT_FIELDS = """
    name sku url_key stock_status __typename
    price_range { minimum_price {
        final_price { value currency } regular_price { value } } }
    image { url }
"""


def _category_products(url_path: str) -> list[dict]:
    cats = gql('{categories(filters:{url_path:{eq:"%s"}}){items{uid}}}'
               % url_path)["data"]["categories"]["items"]
    if not cats:
        return []
    uid = cats[0]["uid"]
    q = '{products(filter:{category_uid:{eq:"%s"}},pageSize:100){items{%s}}}' % (
        uid, _PRODUCT_FIELDS)
    return gql(q)["data"]["products"]["items"]


def _sitemap_candidates() -> list[str]:
    req = urllib.request.Request(f"{STORE}/sitemap.xml",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml = resp.read().decode("utf-8", "replace")
    slugs = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
        slug = loc.rstrip("/").rsplit("/", 1)[-1]
        if _BIKE_SLUG.match(slug) and not _ACCESSORY.search(slug):
            slugs.append(slug)
    return sorted(set(slugs))


def _probe_products(slugs: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(slugs), 20):
        batch = slugs[i:i + 20]
        keys = ",".join(f'"{s}"' for s in batch)
        q = '{products(filter:{url_key:{in:[%s]}},pageSize:50){items{%s}}}' % (
            keys, _PRODUCT_FIELDS)
        out += gql(q)["data"]["products"]["items"]
    return out


def discover_products() -> list[dict]:
    """Every purchasable bike product (color variants still separate here)."""
    by_sku: dict = {}
    for cat in CATEGORIES:
        for p in _category_products(cat):
            p["_category"] = cat
            by_sku[p["sku"]] = p
    for p in _probe_products(_sitemap_candidates()):
        by_sku.setdefault(p["sku"], p)
    bikes = []
    for p in by_sku.values():
        price = ((p.get("price_range") or {}).get("minimum_price") or {})
        final = ((price.get("final_price") or {}).get("value")) or 0
        name = p.get("name") or ""
        if (p.get("__typename") == "BundleProduct"
                and "bike" in name.lower()
                # eDirt Bikes (Xaber) have no pedals — not e-bikes. The Xyber
                # is pedal-equipped and is named "Electric Bike", so it stays.
                and "dirt" not in name.lower()
                and not _ACCESSORY.search(name)
                and final >= 800):
            bikes.append(p)
    return bikes


def base_handle(url_key: str) -> str:
    """Strip trailing color words: segway-ebike-xafari-red -> segway-ebike-xafari,
    muxi-electric-bike-dark-green -> muxi-electric-bike."""
    parts = url_key.split("-")
    while len(parts) > 1 and parts[-1] in _COLOR_TOKENS:
        parts.pop()
    return "-".join(parts)


def series_candidates(handle: str) -> list[str]:
    """Brand-page basenames to try for a store handle (myon-s falls back to
    myon — the S shares the Myon page)."""
    s = re.sub(r"^segway-ebike-", "", handle)
    s = re.sub(r"-?electric-bike-?", "", s).strip("-") or s
    cands = [s]
    if re.search(r"-[a-z0-9]$", s):
        cands.append(s[:-2])
    return cands


# --------------------------- brand-page extraction ---------------------------

def _fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception:
        return None


def _js_objects(src: str):
    """Parse every `window.component_*_json = {...}` assignment."""
    for m in re.finditer(r"window\.component_[a-z_]*_json\s*=\s*", src):
        start = src.find("{", m.end() - 1)
        depth, i = 0, start
        in_str, esc = False, False
        while i < len(src):
            c = src[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        try:
            yield json.loads(src[start:i + 1])
        except Exception:
            continue


def _walk(obj):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _rgba_to_hex(s: str) -> str | None:
    m = re.findall(r"\d+", s or "")
    if len(m) >= 3:
        return "#" + "".join(f"{int(x):02x}" for x in m[:3])
    return None


def brand_page_data(series: str) -> tuple[dict, list]:
    """(spec rows, colors) from the brand product page's embedded AEM JSON."""
    src = None
    for cand in series_candidates(series):
        src = _fetch(f"{BRAND}/ebike/products/{cand}.html")
        if src and '"category"' in src:
            break
    if not src:
        return {}, []
    specs: dict = {}
    colors: list = []
    root = series.split("-")[0].lower()
    for obj in _js_objects(src):
        blocks = [d for d in _walk(obj)
                  if isinstance(d, dict) and isinstance(d.get("category"), list)
                  and d["category"] and isinstance(d["category"][0], dict)
                  and "options" in d["category"][0]]
        for block in blocks:
            # the page may carry several products (accessories); keep the block
            # whose series matches ours
            ser = next((d.get("series") for d in _walk(block)
                        if isinstance(d, dict) and d.get("series")), "")
            if ser and root not in str(ser).lower():
                continue
            for cat in block["category"]:
                cname = cat.get("name") or ""
                for opt in cat.get("options") or []:
                    label, value = opt.get("option"), opt.get("optionValue")
                    if not label or not value or value.strip() in ("--", "-", ""):
                        continue
                    value = re.sub(r"<br\s*/?>", "; ", value)
                    value = re.sub(r"<[^>]+>", " ", value).strip()
                    key = label if label not in specs else f"{label} ({cname})"
                    specs.setdefault(key, value)
            for d in _walk(block):
                if isinstance(d, dict) and d.get("colorName"):
                    img = ((d.get("colorImage") or {}).get("colorPcImage")) or None
                    if img and img.startswith("/"):
                        img = BRAND + img
                    colors.append({"name": d["colorName"].strip(),
                                   "hex": _rgba_to_hex(d.get("colorValue") or ""),
                                   "swatch_image": None, "image": img})
            if specs:
                return specs, colors
    return specs, colors


def store_strip(url_key: str) -> dict:
    """The store PDP's per-product highlight strip ("Motor": "750 W", ...) from
    the RSC flight payload. These are per-store-product figures, so they win
    label collisions with the (possibly shared) brand page."""
    src = _fetch(f"{STORE}/{url_key}")
    if not src:
        return {}
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)</script>', src, re.S)
    blob = "".join(c.encode().decode("unicode_escape", "replace") for c in chunks)
    m = re.search(r'"specifications":\s*(\[[^\]]*\])', blob)
    if not m:
        return {}
    try:
        rows = json.loads(m.group(1))
    except Exception:
        return {}
    return {r["subtitle"].strip(): r["title"].strip()
            for r in rows if r.get("subtitle") and r.get("title")}


# ----------------------------------- main ------------------------------------

def build_models(products: list[dict]) -> list[dict]:
    groups: dict = {}
    for p in sorted(products, key=lambda p: p["url_key"]):
        groups.setdefault(base_handle(p["url_key"]), []).append(p)

    # same display name across distinct groups (Myon vs Myon S) -> disambiguate
    name_count: dict = {}
    for handle, ps in groups.items():
        name_count[ps[0]["name"]] = name_count.get(ps[0]["name"], 0) + 1

    models = []
    for handle, ps in sorted(groups.items()):
        primary = ps[0]
        name = primary["name"]
        if name_count[name] > 1:
            # "Segway Myon Electric Bike" sold as myon AND myon-s: grow the
            # series word in place -> "Segway Myon S Electric Bike"
            tag = " ".join(w.upper() if len(w) == 1 else w.title()
                           for w in series_candidates(handle)[0].split("-"))
            root = tag.split(" ")[0]
            name = name.replace(root, tag, 1) if root in name else f"{name} ({tag})"
        prices = [((p["price_range"]["minimum_price"]["final_price"]) or {}).get("value")
                  for p in ps]
        regulars = [((p["price_range"]["minimum_price"].get("regular_price")) or {}).get("value")
                    for p in ps]
        final = min(v for v in prices if v is not None)
        regular = min((v for v in regulars if v is not None), default=None)
        print(f"    - {name[:38]:<38} ${final}  ({len(ps)} colorway(s))", file=sys.stderr)

        specs, colors = brand_page_data(re.sub(r"^segway-ebike-", "", handle))
        strip = store_strip(primary["url_key"])
        all_specs = dict(specs)
        all_specs.update(strip)        # per-product strip wins label collisions

        if not colors:
            colors = [{"name": "Default", "hex": None, "swatch_image": None,
                       "image": (primary.get("image") or {}).get("url")}]
        models.append({
            "model": name,
            "handle": handle,
            "url": f"{STORE}/{primary['url_key']}",
            "product_types": classify_product_types(
                name, "", " ".join([handle, primary.get("_category") or "",
                                    " ".join(all_specs)[:300]])),
            "price_from": final,
            "regular_price": regular if regular and regular > final else None,
            "currency": "USD",
            "options": {"colors": colors},
            "specs": {"all": all_specs},
            "spec_count": len(all_specs),
            "warranty": None,
            "scrape_error": None if all_specs else "no specs extracted",
        })
    return models


def main():
    ap = argparse.ArgumentParser(description="Scrape Segway e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/segway_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only first N models.")
    args = ap.parse_args()

    print(f"[*] Discovering models via {GRAPHQL} ...", file=sys.stderr)
    products = discover_products()
    print(f"[*] Found {len(products)} bike product(s) (colorways separate).", file=sys.stderr)
    models = build_models(products)
    if args.limit:
        models = models[: args.limit]

    out = {
        "source": STORE, "logo": LOGO,
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
