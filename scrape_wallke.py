#!/usr/bin/env python3
"""
ENGWE (US store, wallkeebike.com) e-bike scraper (Shopify, products.json + page HTML).

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

BASE = "https://wallkeebike.com"
LOGO = "https://wallkeebike.com/cdn/shop/files/wallke-logo.png"
COLLECTIONS = ["all-e-bike"]

_SKIP = re.compile(r"combo|warranty|gift|accessor|bundle", re.I)
# normalize a few vendor labels so the pipeline's parsers recognise them
_LABEL_FIX = {
    "material": "Frame Material", "max mileage": "Max Range", "mileage": "Max Range",
    "transmission system": "Drivetrain", "transmission": "Drivetrain",
    "tires size": "Tires", "tire size": "Tires", "tyres": "Tires",
}


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
        label = _LABEL_FIX.get(label.lower(), label)
        value = cells[1].strip()
        # skip box-content rows ("×1", "*2") and QC/photo checklists ("1. … photo")
        if re.fullmatch(r"[×x*]?\s*\d+", value) or re.match(r"\d+\.\s", value) \
                or re.search(r"\bphoto\b", value, re.I):
            continue
        if (label and len(label) < 30 and value and len(value) < 200
                and label.lower() not in {k.lower() for k in out}
                and label.lower() != value.lower()):
            out[label] = value
    return out


def enrich_from_text(specs: dict, title: str, page: str) -> dict:
    """Fill range / torque / motor from the product title or marketing copy when
    the spec table omits them (Wallke lists range+torque in the title -- "… 180+
    Miles | 150Nm Torque" -- and the motor only in prose). Fills only absent
    fields."""
    have = [k.lower() for k in specs]
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    if not any(("range" in k or "mileage" in k) for k in have):
        m = (re.search(r"(\d{2,3})\s*\+?\s*Miles?\b", title, re.I)
             or re.search(r"up\s*to\s*(\d{2,3})\s*\+?\s*Miles?\b", txt, re.I))
        # else the largest mileage figure quoted on the page (its "up to" range)
        val = (int(m.group(1)) if m
               else max((int(x) for x in re.findall(r"(\d{2,3})\s*\+?\s*Miles?\b", txt, re.I)),
                        default=0))
        if val:
            specs["Max Range"] = f"Up to {val} miles"
    if not any("torque" in k for k in have):
        m = re.search(r"(\d{2,3})\s*N[.\s]?m\b", title, re.I)
        val = (int(m.group(1)) if m
               else max((int(x) for x in re.findall(r"(\d{2,3})\s*N[.\s]?m\b", txt, re.I)),
                        default=0))
        if val:
            specs["Torque"] = f"{val} Nm"
    if not any("motor" in k for k in have):
        # nominal: "NNNNW … <rear/hub/mid> motor" or "motor: <48V> NNNNW";
        # peak: "peak <power:> NNNNW" / "NNNNW peak motor". The "motor" adjacency
        # avoids grabbing an off-grid power-station's rated output (e.g. 600W).
        nom = (re.search(r"(\d{3,4})\s*W[\s\S]{0,18}?(?:rear|front|mid|hub|spoke)[\w\s-]{0,10}?motor", txt, re.I)
               or re.search(r"motor[：:\s-]{0,8}(?:\d{2,3}\s*V\s*)?(\d{3,4})\s*W", txt, re.I))
        # peak must sit next to "motor" so an off-grid station's peak inverter
        # output (e.g. "Peak Power: 3800W") isn't mistaken for the motor peak.
        pk = (re.search(r"(\d{3,4})\s*W\s*peak\s*motor", txt, re.I)
              or re.search(r"peak\s*(\d{3,4})\s*W\s*motor", txt, re.I))
        nv = nom.group(1) if nom else None
        pv = pk.group(1) if pk else None
        if nv and pv:
            specs["Motor"] = f"{nv}W ({pv}W peak)"
        elif nv:
            specs["Motor"] = f"{nv}W"
        elif pv:
            specs["Motor"] = f"{pv}W peak"
    return specs


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
        # sale price: compare_at of the cheapest variant, when it's a real markdown
        cheapest = min((v for v in variants if v.get("price")),
                       key=lambda v: float(v["price"]), default=None)
        regular = None
        if cheapest and cheapest.get("compare_at_price"):
            c = float(cheapest["compare_at_price"])
            if c > float(cheapest["price"]):
                regular = c
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
        # per-variant configurations -> drives stock (availability) + per-config
        # pricing downstream (normalize summarizes sold-out from these flags).
        opt_names = [o.get("name") for o in p.get("options", [])]
        configurations = []
        for v in variants:
            vopts = {}
            for i, nm in enumerate(opt_names):
                val = v.get(f"option{i + 1}")
                if nm and val:
                    vopts[nm] = val
            vprice = float(v["price"]) if v.get("price") else None
            vcmp = float(v["compare_at_price"]) if v.get("compare_at_price") else None
            configurations.append({
                "options": vopts,
                "price": vprice,
                "regular_price": vcmp if (vcmp and vprice and vcmp > vprice) else None,
                "available": v.get("available"),
                "sku": v.get("sku"),
                "variant_id": v.get("id"),
            })
        page_html = fetch_html(f"{BASE}/products/{p['handle']}")
        specs = enrich_from_text(parse_specs(page_html),
                                 clean_title(p.get("title")) or "", page_html)
        out.append({
            "model": clean_title(p.get("title")),
            "handle": p.get("handle"),
            "url": f"{BASE}/products/{p['handle']}",
            "product_types": classify_product_types(
                p.get("title") or "", p.get("product_type") or "",
                " ".join(p.get("tags") or [])),
            "price_from": min(prices) if prices else None,
            "regular_price": regular,
            "currency": "USD",
            "options": options,
            "configurations": configurations,
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
    ap = argparse.ArgumentParser(description="Scrape WALLKE e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/wallke_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
