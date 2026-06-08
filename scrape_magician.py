#!/usr/bin/env python3
"""
Magician Ebikes (magicianebikes.com) spec scraper (Shopify, products.json + page HTML).

The model list, colors and price come from the `all-product` collection feed. Each
product page has a "Technical Specifications" accordion (t4s theme) rendered into
the static HTML as <h4>label</h4><p>value</p> rows under collapsed categories
(E-System, Drive, Suspension, Frameset, Wheelset, Components, Weight & Payload, …).
Those rows are read straight from the page HTML — comprehensive (motor, battery
Wh, drivetrain, fork/shock, frame, tires, brakes, weight, rider height) and no
browser needed. Falls back to the description prose if a page lacks the section.

Usage:
    python scrape_magician.py [-o out.json] [--limit N]
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

BASE = "https://magicianebikes.com"
LOGO = "https://magicianebikes.com/cdn/shop/files/295f76d0-2bd0-4eff-93de-70ba6fb24942.png?v=1746688187"
COLLECTION = "all-product"

# Tidy a few spec labels so the pipeline's component parsers recognise them.
_LABEL_RENAME = {
    "Battery sizes": "Battery", "Tire Sizes": "Tires", "Crank set": "Crankset",
    "Shifter Rear": "Rear Derailleur", "Shiter Rear": "Rear Derailleur",
    "Rear suspension": "Rear Shock", "Regular Seat post": "Seatpost",
    "Seat post": "Seatpost", "Weight & Payload": "Weight",
    "Recommended riding height": "Rider Height",
}


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_technical_specs(page: str) -> dict:
    """Read the Technical Specifications accordion (<h4>label</h4><p>value</p>)."""
    s = page.find("Technical Specifications")
    if s < 0:
        return {}
    e = page.find("FAQ & Guides", s)
    region = page[s:e if e > 0 else s + 50000]
    out: dict[str, str] = {}
    for label_html, body in re.findall(r"<h4[^>]*>(.*?)</h4>(.*?)(?=<h4|<a\b|<button|\Z)",
                                       region, re.S):
        label = " ".join(re.sub(r"<[^>]+>", " ", label_html).split())
        value = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(body)).split())
        # the last row's value can run into the next category label; trim it
        value = re.split(r"\b(?:Alpha\s+)?Size & Fittings\b", value)[0].strip()[:180]
        if not (label and value and len(label) < 30):
            continue
        key = _LABEL_RENAME.get(label, label)
        # "Weight & Payload" combines the bike weight and the payload limit; split
        # them so the (larger) payload number isn't read as the bike's weight.
        if key == "Weight":
            pm = re.search(r"payload\s*=?\s*([\d.]+)\s*lb", value, re.I)
            if pm:
                out.setdefault("Max Load", f"{pm.group(1)} lbs")
            wm = re.search(r"with\s+(?:both\s+)?batter[^=]*=\s*([\d.]+)\s*lb", value, re.I)
            if wm:
                value = f"{wm.group(1)} lbs"
        out.setdefault(key, value)
    return out


def parse_prose_specs(body_html: str) -> dict:
    """Fallback: the few specs Magician states in the description prose."""
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body_html or "")).split())
    out: dict[str, str] = {}
    m = re.search(r"(bafang\s*)?(\d{2,3})\s*v\s*(\d{3,4})\s*w", txt, re.I)
    if m:
        out["Motor"] = f"{'Bafang ' if m.group(1) else ''}{m.group(2)}V {m.group(3)}W"
    fr = re.search(r"front\s*(\d{2,3})\s*v\s*(\d{1,2})\s*ah", txt, re.I)
    rr = re.search(r"rear\s*(\d{2,3})\s*v\s*(\d{1,2})\s*ah", txt, re.I)
    if fr or rr:
        out["Battery"] = " + ".join(
            f"{x.group(1)}V {x.group(2)}Ah" for x in (fr, rr) if x)
    t = re.search(r"(\d{2,3})\s*nm", txt, re.I)
    if t:
        out["Torque"] = f"{t.group(1)}Nm"
    r = re.search(r"(\d{2,3})\s*miles?", txt, re.I)
    if r:
        out["Range"] = f"Up to {r.group(1)} miles"
    if re.search(r"full[- ]?suspension", txt, re.I):
        out["Suspension"] = "Full suspension"
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
        url = f"{BASE}/products/{p['handle']}"
        specs = parse_technical_specs(fetch_html(url))
        # the tech-specs section omits range; fill it (and any gaps) from the prose
        for k, v in parse_prose_specs(p.get("body_html") or "").items():
            specs.setdefault(k, v)
        models.append({
            "model": clean_title(p.get("title")),
            "handle": p.get("handle"),
            "url": url,
            "product_types": classify_product_types(
                p.get("title") or "", p.get("product_type") or "",
                " ".join(p.get("tags") or [])),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
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
