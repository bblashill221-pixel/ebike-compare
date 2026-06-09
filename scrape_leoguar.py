#!/usr/bin/env python3
"""
Leoguar (leoguarbikes.com) e-bike scraper (Shopify, products.json + page HTML).

Models come from the off-road / fat-tire / mid-drive / beach-cruiser collections
(deduped). Leoguar renders its spec sheet as graphics, but the key figures are
present in the static page (a stat-hero layout -- "720 Wh", "85Nm", "28 MPH",
"60 Miles") plus the motor/drivetrain in an image filename
("750W_Rear_Hub_Motor_Shimano_8-Speed"). Those are pulled out with targeted
regexes. Coverage is partial (the rest is image-only); the audit flags the gaps.

Usage:  python scrape_leoguar.py [-o out.json] [--limit N]
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

BASE = "https://leoguarbikes.com"
LOGO = "https://leoguarbikes.com/cdn/shop/files/leoguar-logo.png"
COLLECTIONS = ["off-road", "fat-tire", "mid-drive-ebikes", "beach-cruiser"]
_SKIP = re.compile(r"combo|warranty|gift|accessor|bundle|pump|lock|fender|basket|battery\b", re.I)


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_specs(page: str) -> dict:
    """Leoguar's specs are graphics; pull the figures that survive in the static
    page text + the motor/drivetrain encoded in an image filename."""
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    out: dict = {}

    bat = []
    m = re.search(r"(\d{2,3})\s*V\s*(\d{1,2})\s*Ah", txt, re.I)
    if m:
        bat.append(f"{m.group(1)}V {m.group(2)}Ah")
    m = re.search(r"(\d{3,4})\s*Wh", txt, re.I)
    if m:
        bat.append(f"{m.group(1)}Wh")
    if bat:
        out["Battery"] = " ".join(bat)

    m = re.search(r"(\d{3,4})\s*W[_\s]*(Rear[_\s]?Hub|Front[_\s]?Hub|Mid[_\s-]?drive)?[_\s]*Motor", page, re.I)
    if m:
        kind = (m.group(2) or "").replace("_", " ").strip()
        out["Motor"] = f"{m.group(1)}W {kind} motor".replace("  ", " ").strip()
    elif re.search(r"mid[\s-]?drive", txt, re.I):
        out["Motor"] = "Mid-drive motor"

    m = re.search(r"(\d{2,3})\s*Nm", txt, re.I)
    if m:
        out["Torque"] = f"{m.group(1)}Nm"
    m = re.search(r"(\d{2})\s*MPH", txt, re.I)
    if m:
        out["Top Speed"] = f"{m.group(1)} MPH"
    m = re.search(r"(\d{2,3})\s*Miles?\b", txt, re.I)
    if m:
        out["Range"] = f"Up to {m.group(1)} miles"
    m = re.search(r"Shimano[_\s]*(\d{1,2})[_\s-]?Speed", page, re.I)
    if m:
        out["Drivetrain"] = f"Shimano {m.group(1)}-speed"
    m = re.search(r"(Tektro|Shimano)[\s_]*(?:Hydraulic[\s_]*)?Disc[\s_]*Brakes?[\s_]*(\d{3})?", page, re.I)
    if m:
        out["Brakes"] = f"{m.group(1)} hydraulic disc{(' ' + m.group(2) + 'mm') if m.group(2) else ''}"
    elif re.search(r"hydraulic\s*disc", txt, re.I):
        out["Brakes"] = "Hydraulic disc brakes"
    m = re.search(r"(\d{2}(?:\.\d)?)\s*[\"”]?\s*[x×*]\s*(\d(?:\.\d)?)\s*[\"”]?\s*(?:fat\s*)?tire", txt, re.I)
    if m:
        out["Tires"] = f"{m.group(1)}\" x {m.group(2)}\" tires"
    return out


def discover_models() -> list[dict]:
    # Discover from the full catalog rather than a fixed set of collections, so
    # models in other collections (e.g. the Flippo folder) aren't missed. A real
    # bike is typed "Electric bike" and priced like one (>= $800); the many
    # accessories -- some mistyped "Electric bike" -- are cheap and filtered out.
    seen: dict = {}
    try:
        data = fetch_json(f"{BASE}/products.json?limit=250")
    except Exception:
        data = {}
    for p in data.get("products", []):
        h = p.get("handle")
        if not h or h in seen or _SKIP.search(p.get("title", "")):
            continue
        ptype = (p.get("product_type") or "").lower()
        prices = [float(v["price"]) for v in p.get("variants", []) if v.get("price")]
        if ("electric bike" in ptype or "e-bike" in ptype) and (max(prices) if prices else 0) >= 800:
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
    ap = argparse.ArgumentParser(description="Scrape Leoguar e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/leoguar_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
