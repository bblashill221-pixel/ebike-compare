#!/usr/bin/env python3
"""
ENGWE (US store, cykebikes.com) e-bike scraper (Shopify, products.json + page HTML).

Models come from the all-ebikes + feature-ebikes collections (deduped; combos and
accessories skipped). Each product page server-renders a spec table whose <tr>
rows are label/value (Motor, Battery, Max Torque, Brake Type, Tires, Frame, Max
Load, Max Speed, Bike Weight, Display, Charger, …), read straight from the page
HTML -- no browser needed.

Usage:  python scrape_engwe.py [-o out.json] [--limit N]
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

BASE = "https://cykebikes.com"
LOGO = "https://cykebikes.com/cdn/shop/files/cyke-logo.png"
COLLECTIONS = ["long-range-ebike", "family-series-ebikes", "cross-series-ebikes", "portable-ebikes"]

_SPEC_LABEL = re.compile(
    r"motor|battery|range|brake|tire|tyre|frame|display|charger|torque|speed"
    r"|weight|load|payload|controller|gear|suspension|sensor|throttle|light"
    r"|wheel|rider|fork|drivetrain|shifter|cassette|chain|pedal|saddle|stem"
    r"|handlebar|rim|hub|grip|kickstand|fender|rack|cell|voltage|certif", re.I)
_SKIP = re.compile(r"combo|warranty|gift|accessor|bundle", re.I)


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_specs(page: str) -> dict:
    """label/value spec rows from the page's <tr> tables (deduped, first wins)."""
    out: dict = {}
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        cells = [c for c in cells if c]
        if len(cells) < 2:
            continue
        label = cells[0].rstrip(" :：：").strip()   # drop trailing colon (ascii + fullwidth)
        value = cells[1].strip()
        # skip QC/photo-checklist rows ("1. Full Ebike photo …", "×1", "… photo")
        if re.match(r"\d+\.\s|×\s*\d", value) or re.search(r"\bphoto\b", value, re.I):
            continue
        if (_SPEC_LABEL.search(label) and len(label) < 26 and value
                and len(value) < 160 and label.lower() not in {k.lower() for k in out}
                and label.lower() != value.lower()):
            out[label] = value
    return out


def discover_models() -> list[dict]:
    seen: dict = {}
    for coll in COLLECTIONS:
        try:
            data = fetch_json(f"{BASE}/collections/{coll}/products.json?limit=250")
        except Exception:
            continue
        for p in data.get("products", []):
            h = p.get("handle")
            if h and h not in seen and not _SKIP.search(p.get("title", "")):
                seen[h] = p
    out = []
    for p in seen.values():
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
        specs = parse_specs(fetch_html(f"{BASE}/products/{p['handle']}"))
        out.append({
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
            "scrape_error": None if specs else "no specs extracted",
        })
    return out


def run(args) -> int:
    print(f"[*] Discovering e-bike models from {BASE} ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    for r in models:
        status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
        print(f"    - {r['model'][:32]:<32} {r['spec_count']:>3} specs  "
              f"{len(r['options'].get('colors', []))} colors  [{status}]", file=sys.stderr)
    results = sorted(models, key=lambda r: r["model"] or "")
    out = {"source": BASE, "logo": LOGO, "collection": "+".join(COLLECTIONS),
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape CYKE e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/cyke_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
