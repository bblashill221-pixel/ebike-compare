#!/usr/bin/env python3
"""
Cannondale e-bike scraper (Typesense catalog API + server-rendered PDP HTML).

Discovery hits the site's own Typesense search (host/key/collection read live
from the catalog page, so a rotated key can't break us) filtered to US electric
bikes. Each product page server-renders a "specs-list-item" sheet (name/desc
pairs under section titles) plus an At-A-Glance highlights block -- both parsed
straight from HTML, no browser needed. Colors come from the doc's swatch codes:
names via the catalog page's COLOR_SWATCH_TO_FILTER map, hexes via the
/api/catalog/swatches CSS.

Prices in the index are cents (price_from current, msrp_from regular).

Usage:  python scrape_cannondale.py [-o out.json] [--limit N]
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import scraper_common  # noqa: F401  (sets LD_LIBRARY_PATH; unused otherwise)
from bike_taxonomy import classify_product_types

BASE = "https://www.cannondale.com"
CATALOG = f"{BASE}/en-us/bikes/electric"
LOGO = f"{BASE}/-/media/images/cannondale-newc-favicon-32x32.ashx"


def fetch(url: str, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def typesense_config() -> dict:
    """{host, apiKey, collection} + swatch-code -> color-name map, read from the
    live catalog page (survives search-key rotation)."""
    page = fetch(CATALOG)
    m = re.search(
        r"TYPESENSE_CONFIG\s*=\s*\{\s*host:\s*'([^']+)',\s*apiKey:\s*'([^']+)',\s*collection:\s*'([^']+)'",
        page)
    if not m:
        raise RuntimeError("TYPESENSE_CONFIG not found on catalog page")
    sw = re.search(r"COLOR_SWATCH_TO_FILTER\s*=\s*(\{.*?\});", page)
    swatch_names = json.loads(sw.group(1)) if sw else {}
    return {"host": m.group(1), "key": m.group(2), "collection": m.group(3),
            "swatch_names": swatch_names}


def swatch_hexes() -> dict:
    """code -> #hex from the swatch stylesheet (.swatch-gra { ... rgb(r,g,b) })."""
    out = {}
    try:
        css = fetch(f"{BASE}/api/catalog/swatches")
    except Exception:
        return out
    for code, r, g, b in re.findall(
            r"\.swatch-(\w+)\s*\{[^}]*rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", css):
        out[code.upper()] = "#%02x%02x%02x" % (int(r), int(g), int(b))
    return out


def search_ebikes(cfg: dict) -> list[dict]:
    """All US electric-bike documents from the Typesense index."""
    docs, page = [], 1
    while True:
        qs = urllib.parse.urlencode({
            "q": "*",
            "filter_by": "country:=US && product_type:=Bike && category_slugs:=electric",
            "per_page": 50, "page": page,
        })
        data = json.loads(fetch(
            f"{cfg['host']}/collections/{cfg['collection']}/documents/search?{qs}",
            headers={"X-TYPESENSE-API-KEY": cfg["key"]}))
        hits = [h["document"] for h in data.get("hits", [])]
        docs += hits
        if page * 50 >= data.get("found", 0) or not hits:
            return docs
        page += 1


_TAG = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return " ".join(htmllib.unescape(_TAG.sub(" ", s)).split())


def parse_pdp(page: str) -> tuple[dict, str | None]:
    """(spec rows, og:image) from a product detail page. Spec rows are the
    specs-list-item name/desc pairs (flat, first occurrence wins). The
    At-A-Glance bullets are mined for discrete facts the sheet omits (range,
    top speed, motor watts, class) -- emitted as their own parseable rows, never
    as one long blob (a joined blob lands in the UI as a giant unreadable row)."""
    specs: dict = {}
    for block in re.findall(
            r'<li[^>]*class="[^"]*specs-list-item[^"]*"[^>]*>(.*?)</li>', page, re.S):
        nm = re.search(r'class="name"[^>]*>(.*?)</', block, re.S)
        dv = re.search(r'class="desc"[^>]*>(.*?)(?:</div|</span|</p)', block, re.S)
        if not (nm and dv):
            continue
        label, value = _text(nm.group(1)), _text(dv.group(1))
        if label and value and label.lower() not in {k.lower() for k in specs}:
            specs[label] = value
    bullets = " ".join(
        _text(b) for b in re.findall(
            r'class="product-overview__copy[^"]*"[^>]*>(.*?)</p>', page, re.S))
    have = {k.lower() for k in specs}
    if "range" not in have:
        m = re.search(r"(\d{2,3})\s*[-\s]?mile", bullets, re.I)
        if m:
            specs["Range"] = f"Up to {m.group(1)} miles"
    if not any("speed" in k for k in have):
        m = re.search(r"(\d{2})\s*mph", bullets, re.I)
        if m:
            specs["Max Speed"] = f"{m.group(1)} mph"
    motor_txt = next((str(v) for k, v in specs.items() if "motor" in k.lower()
                      or "drive unit" in k.lower()), "")
    if not re.search(r"\d{3,4}\s*W\b", motor_txt, re.I):
        m = re.search(r"(\d{3,4})\s*W\b", bullets)
        if m:
            specs["Motor Power"] = f"{m.group(1)}W"
    m = re.search(r"class\s*([123](?:\s*(?:[/,&]|or|and)\s*[123])*)", bullets, re.I)
    if m and "class" not in have:
        specs["Class"] = f"Class {m.group(1)}"
    m = re.search(r'property="og:image" content="([^"]+)"', page)
    return specs, (m.group(1) if m else None)


def extract_variants(page: str, salsify_id: str) -> list[dict]:
    """The PDP embeds a per-SKU variants array (Size, MinHeight/MaxHeight in
    inches, ColorName, per-color images, per-SKU price + inventory). Cross-sell
    carousels embed the same shape for other products, so match on
    SalsifyParentId -- normalized, because older products drop the "COLL" infix
    there ("0818-2021") while the search doc keeps it ("0818-COLL2021")."""
    norm = lambda s: (s or "").replace("COLL", "")  # noqa: E731
    target = norm(salsify_id)
    for m in re.finditer(r'\[\{"AvailableB2C"', page):
        s = m.start()
        depth = 0
        e = s
        for e in range(s, min(len(page), s + 500000)):
            if page[e] == "[":
                depth += 1
            elif page[e] == "]":
                depth -= 1
                if depth == 0:
                    break
        try:
            arr = json.loads(page[s:e + 1])
        except ValueError:
            continue
        if any(norm(v.get("SalsifyParentId")) == target for v in arr):
            return arr
    return []


def _ftin(inches) -> str:
    return f"{int(inches) // 12}'{int(inches) % 12}\""


def fetch_api_product(salsify_id: str) -> dict:
    """The site's own product API -- the same Variants payload D2C pages embed
    (Size, MinHeight/MaxHeight, ColorName, per-SKU price + inventory), but it
    answers for dealer-only models too (their pages embed nothing)."""
    try:
        d = json.loads(fetch(f"{BASE}/en-us/api/products/{salsify_id}"))
        return (d.get("Data") or [{}])[0] or {}
    except Exception:  # noqa: BLE001
        return {}


def build_model(doc: dict, cfg: dict, hexes: dict) -> dict:
    url = f"{BASE}/en-us/{doc.get('relative_url', '').lstrip('/')}"
    page = ""
    try:
        page = fetch(url)
    except Exception:
        pass
    specs, og_image = parse_pdp(page) if page else ({}, None)
    # the product API answers for every model (dealer-only pages embed nothing)
    variants = (fetch_api_product(doc.get("salsify_id")).get("Variants")
                or (extract_variants(page, doc.get("salsify_id")) if page else []))

    # index facts the spec sheet may not repeat (first wins keeps PDP rows)
    for label, key in (("Motor", "motor_types"), ("Frame Material", "frame_materials"),
                       ("Brakes", "brake_types"), ("Suspension", "suspensions")):
        vals = doc.get(key) or []
        if vals and label.lower() not in {k.lower() for k in specs}:
            specs[label] = "; ".join(vals)

    # per-size rider-height chart + fit-envelope geometry from the embedded
    # per-SKU data (MinHeight/MaxHeight are inches)
    frame_sizes, by_frame = [], {}
    for v in variants:
        size, lo, hi = v.get("Size"), v.get("MinHeight"), v.get("MaxHeight")
        # 0 / null heights are placeholders, not data
        if not size or not lo or not hi or any(f["size"] == size for f in frame_sizes):
            continue
        frame_sizes.append({"size": size, "height_min": _ftin(lo), "height_max": _ftin(hi)})
        by_frame[size] = f"{_ftin(lo)} - {_ftin(hi)}"
    geometry = {"Rider Height Range": by_frame} if by_frame else {}
    if not frame_sizes and len(doc.get("sizes") or []) > 1:
        # dealer-only models carry no commerce embed (no per-size heights);
        # keep the size names so the size count/picker is still right
        order = {s: i for i, s in enumerate(["XS", "SM", "MD", "LG", "XL", "XXL"])}
        frame_sizes = [{"size": s, "height_min": None, "height_max": None}
                       for s in sorted(doc["sizes"], key=lambda s: order.get(s, 99))]

    # real colorway names + per-color photos from the variants; fall back to
    # the swatch-code filter names + og:image when the embed is missing
    colors, seen = [], set()
    for v in variants:
        nm = v.get("ColorName")
        if not nm or nm in seen:
            continue
        seen.add(nm)
        colors.append({"name": nm,
                       "hex": hexes.get((v.get("ColorSwatch") or "").upper()),
                       "swatch_image": None,
                       "image": v.get("MainDetailImage") or og_image})
    if not colors:
        for code in doc.get("color_swatches") or []:
            names = cfg["swatch_names"].get(code) or []
            colors.append({"name": " / ".join(n.strip() for n in names) or code,
                           "hex": hexes.get(code.upper()),
                           "swatch_image": None, "image": og_image})

    # per-SKU configurations (size x color) with their own price + stock
    configurations = []
    for v in variants:
        sale, msrp_v = v.get("SalePrice"), v.get("Msrp")
        configurations.append({
            "options": {k: vv for k, vv in
                        (("Size", v.get("Size")), ("Color", v.get("ColorName"))) if vv},
            "price": sale or msrp_v,
            "regular_price": msrp_v if (msrp_v and sale and msrp_v > sale) else None,
            "available": (v.get("AvailableInventory") or 0) > 0,
            "sku": v.get("Sku"),
        })

    price = (doc.get("price_from") or 0) / 100 or None
    msrp = (doc.get("msrp_from") or 0) / 100 or None
    # has_availability just means "listed" (true for the whole US partition);
    # has_inventory is the real in-stock-online flag (PDPs of false docs say
    # "Out of Stock")
    in_stock = bool(doc.get("has_inventory"))
    sizes = doc.get("sizes") or []
    if not configurations:
        configurations = [
            {"options": {"Size": s}, "price": price, "available": in_stock, "sku": None}
            for s in sizes
        ]
    name = doc.get("consumer_name_3") or doc.get("model_name") or doc.get("platform")
    tags = " ".join((doc.get("tags") or []) + (doc.get("categories") or []))

    return {
        "model": name,
        "handle": (doc.get("relative_url") or "").rsplit("/", 1)[-1] or doc.get("model_code"),
        "url": url,
        "model_year": doc.get("model_year"),
        "family": doc.get("platform"),
        "product_types": classify_product_types(
            name or "", doc.get("sub_category") or "", tags),
        "tags": doc.get("tags") or [],
        "price_from": price,
        "regular_price": msrp if (msrp and price and msrp > price) else None,
        "currency": doc.get("currency") or "USD",
        "available": in_stock,
        "options": {"colors": colors, "sizes": sizes} if sizes else {"colors": colors},
        "configurations": configurations,
        "frame_sizes": frame_sizes or None,
        "geometry": geometry,
        "specs": {"all": specs},
        "spec_count": len(specs),
        "warranty": None,
        "scrape_error": None if specs else "no specs extracted",
    }


def propagate_family_heights(models: list) -> int:
    """Per-size rider heights live only in D2C commerce embeds, so dealer-only
    models lack them even when a same-platform sibling (same frame geometry)
    states them -- e.g. Moterra Neo Carbon 2 has SM-XL heights while Moterra 1-4
    have none. Copy heights across a family per size code, but only when every
    donor in the family agrees on that size's range."""
    by_fam: dict = {}
    for m in models:
        fam = m.get("family")
        if not fam:
            continue
        for f in m.get("frame_sizes") or []:
            if f.get("height_min") and f.get("height_max"):
                by_fam.setdefault(fam, {}).setdefault(
                    f["size"], set()).add((f["height_min"], f["height_max"]))
    filled = 0
    for m in models:
        donors = by_fam.get(m.get("family")) or {}
        if not donors:
            continue
        by_frame = {}
        for f in m.get("frame_sizes") or []:
            if not f.get("height_min"):
                ranges = donors.get(f["size"])
                if ranges and len(ranges) == 1:
                    f["height_min"], f["height_max"] = next(iter(ranges))
                    filled += 1
            if f.get("height_min"):
                by_frame[f["size"]] = f'{f["height_min"]} - {f["height_max"]}'
        if by_frame and not (m.get("geometry") or {}).get("Rider Height Range"):
            m.setdefault("geometry", {})["Rider Height Range"] = by_frame
    return filled


def run(args) -> int:
    print(f"[*] Discovering e-bike models from {CATALOG} ...", file=sys.stderr)
    cfg = typesense_config()
    hexes = swatch_hexes()
    docs = search_ebikes(cfg)
    print(f"[*] Found {len(docs)} US electric bike(s) in the catalog index.", file=sys.stderr)
    if args.limit:
        docs = docs[: args.limit]
    models = []
    for doc in docs:
        r = build_model(doc, cfg, hexes)
        models.append(r)
        status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
        print(f"    - {(r['model'] or '?')[:36]:<36} {r['spec_count']:>3} specs  "
              f"{len(r['options'].get('colors', []))} colors  [{status}]", file=sys.stderr)
    filled = propagate_family_heights(models)
    if filled:
        print(f"[*] Propagated {filled} per-size rider heights across families.",
              file=sys.stderr)
    results = sorted(models, key=lambda r: r["model"] or "")
    out = {"source": BASE, "logo": LOGO, "collection": "bikes/electric",
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Cannondale e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/cannondale_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
