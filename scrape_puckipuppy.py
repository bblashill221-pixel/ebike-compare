#!/usr/bin/env python3
"""
Puckipuppy (puckipuppy.com) spec scraper (Shopify, products.json + page HTML).

Models are named after dog breeds (Labrador Pro ST, Schnauzer, Doberman, Rottweiler
Etrike, …). The catalog is mostly accessories/spare parts, so the e-bikes are isolated
by: a "Color" product option AND a non-accessory title. Colors/prices/configs come from
the collection feed.

SPECS: Puckipuppy renders its spec table through a third-party "compare" app that loads
values from Shopify metafields client-side — the static HTML carries the spec LABELS but
no values, and a render doesn't populate them. So we extract what the product page does
expose statically: the marketing "feature" headline blocks ("750W Motor | … 28 mph",
"48V 15Ah Battery", "Hydraulic Disc Brakes") plus a few conservative whole-text fallbacks.
The rest is left to resolve_missing_fields.py (it re-fetches each model `url` and hunts the
audited gaps) — every model carries a working `url`.

Usage:
    python scrape_puckipuppy.py [-o out.json] [--limit N]
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

from scraper_common import fetch_json, clean_title, build_colors  # noqa: E402 (sets LD_LIBRARY_PATH)
from bike_taxonomy import classify_product_types

BASE = "https://puckipuppy.com"

# Non-bike listings (accessories / spare parts / bundles) — excluded even if they carry a
# Color option. The e-bikes are whatever has a Color option and is NOT one of these.
_ACCESSORY = re.compile(
    r"\b(pack|package|carrier|rack|kit|battery|warranty|tool|helmet|mudguard|sticker|"
    r"saddle|bag|rotor|brake|fork|handlebar|fender|bracket|rim|harness|port|light|"
    r"freewheel|protection|spare|charging|tire|tube|pedal|seat|grip|charger)\b", re.I)


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def _txt(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def parse_specs(page: str) -> dict:
    """Per-product specs from the page PROSE — the ONLY accurate per-product source on this
    site (the structured "compare" spec table is a fixed default placeholder, identical on
    every page, and the values are JS-locked; confirmed by inspection). One function for all
    models, so the extraction is changed in a single place, never per page.

    Two passes: (1) the product's own "feature" headline blocks ("750W Motor | … 28 mph",
    "48V 15Ah Battery", "Hydraulic Disc Brakes"); (2) conservative whole-text patterns
    anchored to context words, to recover the systems the feature blocks omit (the real
    figures — e.g. the Rottweiler's 1350W — live in the description prose)."""
    out: dict[str, str] = {}
    for blk in re.findall(r'headline__h5 desc"[^>]*>(.*?)</div>', page, re.S):
        t = _txt(blk)
        if not t:
            continue
        head = t.partition("|")[0].strip()
        low = head.lower()
        if not head or len(head) > 48:
            continue
        if "motor" in low:
            out.setdefault("Motor", head)
            m = re.search(r"(?:up to\s*)?(\d{2,3})\s*mph", t, re.I)
            if m:
                out.setdefault("Max Speed", f"{m.group(1)} mph")
        elif "battery" in low:
            out.setdefault("Battery", head)
        elif "brake" in low:
            out.setdefault("Brakes", head)
        elif "range" in low or "mile" in low:
            out.setdefault("Range", head)
        elif "tire" in low or "fat" in low:
            out.setdefault("Tire", head)

    text = _txt(page)

    def near(word_pat, val_pat, win=22):
        """val within `win` chars before/after a context word, either order."""
        return (re.search(rf"{val_pat}[^.]{{0,{win}}}{word_pat}", text, re.I)
                or re.search(rf"{word_pat}[^.]{{0,{win}}}{val_pat}", text, re.I))

    # "MOTOR POWER 750W (960W Peak)" is the product's authoritative key-spec strip — prefer it
    # over the feature blocks / near-motor prose, which can cite a related product or only the
    # peak (the feature block read the Rottweiler as 1350W; its real spec strip is 750W/960W).
    # Note the source mixes ASCII "(" and fullwidth "（".
    m = re.search(r"MOTOR POWER\s*(\d{3,4})\s*W\s*[（(]\s*(\d{3,4})\s*W\s*peak", text, re.I)
    if m:
        out["Motor"] = f"{m.group(1)}W ({m.group(2)}W peak) motor"
    else:
        m = re.search(r"MOTOR POWER\s*(\d{3,4})\s*W", text, re.I)
        if m:
            out["Motor"] = f"{m.group(1)}W motor"
    if "Motor" not in out:
        m = near(r"\bmotor", r"(\d{3,4})\s*W\b")
        if m:
            out["Motor"] = f"{m.group(1)}W motor"
    if "Battery" not in out:
        m = (re.search(r"(\d{2})\s*V\b[^.]{0,12}?(\d{1,2}(?:\.\d)?)\s*Ah\b", text, re.I))
        if m:
            out["Battery"] = f"{m.group(1)}V {m.group(2)}Ah battery"
    if "Max Speed" not in out:
        m = re.search(r"up to\s*(\d{2})\s*mph", text, re.I) or re.search(r"(\d{2})\s*mph", text, re.I)
        if m:
            out["Max Speed"] = f"{m.group(1)} mph"
    if "Range" not in out:
        m = re.search(r"up to\s*(\d{2,3})\s*(?:miles|mi)\b", text, re.I)
        if m:
            out["Range"] = f"Up to {m.group(1)} miles"
    if "Brakes" not in out:
        m = re.search(r"\b(hydraulic|mechanical)\b[^.]{0,12}\bdisc", text, re.I)
        if m:
            out["Brakes"] = f"{m.group(1).title()} disc brakes"
    if "Tire" not in out:
        m = re.search(r"\b(\d{2}(?:\.\d)?)\s*[\"”']?\s*[x×]\s*(\d(?:\.\d)?)\s*[\"”']?", text)
        if m:
            out["Tire"] = f'{m.group(1)}" x {m.group(2)}" tire'
    m = near(r"(?:max\s*load|payload|load\s*capac|capacity)", r"(\d{3})\s*lbs?\b")
    if m:
        out["Max Load"] = f"{m.group(1)} lbs"
    m = near(r"\bweight", r"(\d{2,3}(?:\.\d)?)\s*lbs?\b", win=14)
    if m and float(m.group(1)) >= 35:  # floor rejects stray small-part weights (e.g. 19.5 lbs)
        out["Weight"] = f"{m.group(1)} lbs"
    m = re.search(r"(\d'\s*\d{1,2}[\"'']{1,2})\s*[-–~to]+\s*(\d'\s*\d{1,2}[\"'']{1,2})", text)
    if m:
        out["Rider Height"] = f"{m.group(1)} - {m.group(2)}"
    # drivetrain (gears + maker), sensor, fork, charger, display, ingress rating — also in prose
    m = re.search(r"\b(\d{1,2})\s*-?\s*speed\b", text, re.I)
    if m:
        gears = f"{m.group(1)}-speed"
        out["Derailleur"] = f"{gears} Shimano" if re.search(r"\bshimano\b", text, re.I) else gears
    if re.search(r"\btorque\s*\+?\s*cadence\b", text, re.I):
        out["Sensor"] = "Torque + Cadence"
    elif re.search(r"\btorque\s+sensor\b", text, re.I):
        out["Sensor"] = "Torque sensor"
    elif re.search(r"\bcadence\s+sensor\b", text, re.I):
        out["Sensor"] = "Cadence sensor"
    m = (re.search(r"\bfront fork\b[^.]{0,8}?(\d{2,3})\s*mm[^.]{0,18}?suspension", text, re.I)
         or re.search(r"\b(\d{2,3})\s*mm\b[^.]{0,8}?suspension fork", text, re.I))
    if m:
        out["Fork"] = f"{m.group(1)}mm suspension fork"
    elif re.search(r"\bsuspension fork\b", text, re.I):
        out["Fork"] = "Suspension fork"
    m = (re.search(r"(\d(?:\.\d)?)\s*A\b[^.]{0,15}?charger", text, re.I)
         or re.search(r"charger[^.]{0,15}?(\d(?:\.\d)?)\s*A\b", text, re.I))
    if m:
        out["Charger"] = f"{m.group(1)}A charger"
    m = re.search(r"\b(LCD|TFT)\b", text)
    if m:
        out["Display"] = f"{m.group(1)} display"
    m = re.search(r"\bIP[X]?\d{1,2}\b", text)
    if m:
        out["Water Resistant"] = m.group(0).upper()
    return out


def discover_logo() -> str:
    page = fetch_html(BASE)
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
    return m.group(1) if m else ""


def is_ebike(p: dict) -> bool:
    opt_names = [(o.get("name") or "").lower() for o in p.get("options", [])]
    if "color" not in opt_names:
        return False
    return not _ACCESSORY.search(p.get("title") or "")


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/products.json?limit=250")
    models = []
    for p in data.get("products", []):
        if not is_ebike(p):
            continue
        title = p.get("title") or ""
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
        # per-variant configurations WITH availability (Shopify variants carry `available`)
        opt_names = [o.get("name") for o in p.get("options", [])]
        configurations = []
        for v in variants:
            opts = {}
            for j, nm in enumerate(opt_names, start=1):
                val = v.get(f"option{j}")
                if nm and val not in (None, "Default Title"):
                    opts[nm] = val
            configurations.append({
                "options": opts,
                "price": float(v["price"]) if v.get("price") else None,
                "compare_at_price": float(v["compare_at_price"]) if v.get("compare_at_price") else None,
                "available": bool(v.get("available")),
                "sku": v.get("sku"),
            })
        # SALE: regular (pre-discount) price = the cheapest variant's compare_at_price when it
        # exceeds its sale price. Set directly here (puckipuppy spans several collections, so
        # add_pricing's single-collection sale_map would miss the etrikes); normalize turns
        # regular_price into the pricing block (on_sale / discount).
        regular_price = None
        cheapest = min((v for v in variants if v.get("price")), key=lambda v: float(v["price"]), default=None)
        if cheapest and cheapest.get("compare_at_price"):
            cap = float(cheapest["compare_at_price"])
            if cap > float(cheapest["price"]):
                regular_price = cap
        url = f"{BASE}/products/{p['handle']}"
        specs = parse_specs(fetch_html(url))
        # NB: the breed product_type ("Labrador Pro ST") is marketing junk — classify_product_types
        # ignores it and keys on the title + tags ("Etrike"->trike, etc.).
        models.append({
            "model": clean_title(title),
            "handle": p.get("handle"),
            "url": url,
            "product_types": classify_product_types(
                title, p.get("product_type") or "", " ".join(p.get("tags") or [])),
            "price_from": min(prices) if prices else None,
            "regular_price": regular_price,
            "currency": "USD",
            "options": options,
            "configurations": configurations,
            "specs": {"all": specs},
            "spec_count": len(specs),
            "warranty": None,
            "scrape_error": None,
        })
    return _dedupe(models)


def _dedupe(models: list[dict]) -> list[dict]:
    """Puckipuppy lists each bike both as a multi-color product AND a separate single-color
    "camouflage" listing (same title, color in the handle). Collapse same-title entries into
    one: keep the richest (most colors) as primary, fold in any colors/configs the others add,
    and take the lowest price_from. Without this the catalog shows ~32 cards instead of 24."""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for m in models:
        k = (m.get("model") or "").strip().lower()
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(m)
    out = []
    for k in order:
        grp = groups[k]
        if len(grp) == 1:
            out.append(grp[0])
            continue
        primary = max(grp, key=lambda m: len(((m.get("options") or {}).get("colors")) or []))
        seen = {(c.get("name") or "").lower() for c in primary["options"]["colors"]}
        for m in grp:
            if m is primary:
                continue
            for c in ((m.get("options") or {}).get("colors")) or []:
                if (c.get("name") or "").lower() not in seen:
                    seen.add((c.get("name") or "").lower())
                    primary["options"]["colors"].append(c)
            primary["configurations"].extend(m.get("configurations") or [])
        prices = [c["price"] for c in primary["configurations"] if c.get("price")]
        primary["price_from"] = min(prices) if prices else primary.get("price_from")
        out.append(primary)
    return out


def run(args) -> int:
    print(f"[*] Discovering e-bike models from {BASE}/products.json ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    for r in models:
        print(f"    - {r['model'][:34]:<34} {r['spec_count']:>2} specs  "
              f"{len(r['options'].get('colors', []))} colors  "
              f"{len(r['configurations'])} cfgs", file=sys.stderr)
    results = sorted(models, key=lambda r: r["model"] or "")
    out = {"source": BASE, "logo": discover_logo(),
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[*] Wrote {args.output} ({len(results)} models).", file=sys.stderr)
    return 0 if results else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Puckipuppy e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/puckipuppy_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
