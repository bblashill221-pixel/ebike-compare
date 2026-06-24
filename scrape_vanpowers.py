#!/usr/bin/env python3
"""
Vanpowers (vanpowers.com) spec scraper (Shopify, products.json + page HTML).

Model list, colours, prices and per-variant configurations come from the `ebikes`
collection feed. Specs live in the static product HTML, but Vanpowers uses two
page templates, so the parser reads all of them and merges (first value wins):

  * the rich per-model table   ``<tr class="parameter-row"><td class="parameter-name">
    label</td><td class="parameter-value">value</td>…`` (GrandTeton / UrbanCross /
    Cycanon) — the most complete source (Motor, Battery, Frame, Brakes, Fork, …);
  * a flat spec list           ``<h5 class="spec-title">label</h5><h5 class="spec-body">
    value</h5>`` (UrbanGlide family);
  * icon "highlight" cards      ``<div class="spec_item">… class="title"…class="value"…``
    (Top Speed, Fat Tires, Rack Load, Motor power) — fills any gaps.

Battery capacity isn't in the flat-list template's structured rows, so it's
recovered from the product description (`body_html`) as a fallback.

Usage:
    python scrape_vanpowers.py [-o out.json] [--limit N]
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

BASE = "https://vanpowers.com"
COLLECTION = "ebikes"

# Spec labels tidied to the canonical forms the pipeline's parsers key on (frame,
# motor, fork, …). Most labels already match; these just normalise the variants.
_LABEL_RENAME = {
    "Front Fork": "Fork", "Hub Motor": "Motor", "Motor power": "Motor Power",
    "Maximum Load Capacity": "Max Load", "Rack Load Capacity": "Rack Load",
    "Recommended Rider Height": "Rider Height", "Frame size": "Frame Size",
    # UrbanGlide spec cards: PAYLOAD is the bike's max load; LOAD CAPACITY is the rack
    "PAYLOAD": "Max Load", "LOAD CAPACITY": "Rack Load",
}


def _label_for(value: str) -> str | None:
    """Best canonical label for a bare trim-comparison value (those rows carry only icons,
    no text label) — inferred from the value's content."""
    l = value.lower()
    if "sensor" in l: return "Sensor"
    if "suspension fork" in l or ("fork" in l and "travel" in l): return "Fork"
    if "disc brake" in l or " brake" in l: return "Brakes"
    if "mid drive" in l or "hub motor" in l: return "Motor"
    if "wh" in l and ("batter" in l or "lithium" in l): return "Battery"
    if re.search(r"\d+\.?\d*\s*lb", l) and "kg" in l: return "Weight"
    if "mile" in l: return "Range"
    if "charger" in l: return "Charger"
    if re.search(r"\d+[\s-]*speed", l): return "Rear Derailleur"
    if "tire" in l: return "Tires"
    if "seat post" in l: return "Seat Post"
    if "handlebar" in l: return "Handlebar"
    if "stem" in l: return "Stem"
    if "rated" in l and "peak" in l: return "Power"
    return None


def _comparison_col0(page: str) -> dict:
    """The on-page trim-comparison table puts the CURRENT model in COLUMN 0 (verified on
    UrbanGlide Standard/Pro/Ultra). Each `<div class="row">` is one spec across the 3 trims
    as `<p class="value">`; take col 0 and label it by content. Fills the fields the
    UrbanGlide flat spec list omits (fork, sensor, the correct per-trim weight, battery)."""
    out: dict[str, str] = {}
    for row in re.findall(r'<div class="row">(.*?)</div>\s*</div>', page, re.S):
        vals = [_clean(v) for v in re.findall(r'<p class="value">(.*?)</p>', row, re.S) if _clean(v)]
        if len(vals) != 3:        # only the 3-trim comparison rows
            continue
        lab = _label_for(vals[0])
        if lab:
            out.setdefault(lab, vals[0])
    return out

_TAG = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", s or "")).split())


_FT_IN = re.compile(r"(\d)\s*'\s*(\d{1,2})?")          # 5'1", 6'3", 5'10"
_CM_IN = re.compile(r"(\d{3})(?=\s*(?:[-–]\s*\d{3}\s*)?cm)")   # 165cm AND both ends of 170-190cm
_BARE_IN = re.compile(r'(?<!\d\')(\d{2,3})\s*"')        # 61", 66" (not the inch of 5'10")


def _height_minmax(text: str) -> tuple[float, float] | None:
    """(min_in, max_in) from one size's rider-height text. Combine feet-inch AND cm
    (height_range_in would suppress cm whenever any feet-inch is present), falling back
    to bare inches ("61"-66"") only when neither feet-inch nor cm appears. This ignores a
    stray bare inch like UrbanGlide L's "57"" (a typo for 5'7") next to a sane 170-190cm."""
    t = (text.replace("″", '"').replace("′", "'").replace("’", "'").replace("‘", "'")
             .replace("”", '"').replace("“", '"').replace("''", '"'))
    vals = [int(f) * 12 + (int(i) if i else 0) for f, i in _FT_IN.findall(t)]
    vals += [round(float(c) / 2.54, 1) for c in _CM_IN.findall(t)]
    if not vals:
        vals = [int(n) for n in _BARE_IN.findall(t)]
    vals = [v for v in vals if 48 <= v <= 84]
    return (min(vals), max(vals)) if vals else None


def frame_sizes(page: str) -> list[dict] | None:
    """Per-size rider-height ranges from the 'Size & Fit' modal geo-toggle:
    ``<div class="toggle"> S <br> <span>5'1"-5'9" (155-175cm)</span> </div>``. Returns
    [{size, height_min, height_max}] (feet-inch strings); "One-Size" → a single entry
    with no size label."""
    gi = page.find('class="geo-toggle"')
    if gi < 0:
        return None
    region = re.split(r"<table", page[gi:gi + 3000])[0]   # stop before the geometry table
    out = []
    for size, htext in re.findall(
            r'<div class="toggle[^"]*">\s*([^<]+?)\s*<br>\s*<span>(.*?)</span>', region, re.S):
        size = _clean(size)
        mm = _height_minmax(_clean(htext))
        if not mm:
            continue
        fmt = lambda v: f"{int(v) // 12}'{int(v) % 12}\""
        out.append({"size": None if re.fullmatch(r"one[\s-]?size", size, re.I) else size,
                    "height_min": fmt(mm[0]), "height_max": fmt(mm[1])})
    return out or None


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_specs(page: str, body_html: str = "") -> dict:
    """Merge the page's spec rows across Vanpowers' template variants."""
    out: dict[str, str] = {}

    def add(label: str, value: str) -> None:
        label, value = _clean(label), _clean(value)
        if not (label and value and len(label) < 40):
            return
        out.setdefault(_LABEL_RENAME.get(label, label), value)

    # 1) rich per-model table (most complete) — first value column per row
    for row in re.findall(r'<tr class="parameter-row\s*">(.*?)</tr>', page, re.S):
        name = re.search(r'parameter-name">(.*?)</td>', row, re.S)
        vals = [_clean(v) for v in re.findall(r'parameter-value">(.*?)</td>', row, re.S)]
        vals = list(dict.fromkeys(v for v in vals if v))   # dedupe size/variant columns
        if name and vals:
            add(name.group(1), " | ".join(vals))
    # 2) flat spec-title / spec-body list
    for label, value in re.findall(
            r'<h5 class="spec-title">(.*?)</h5>\s*<h5 class="spec-body">(.*?)</h5>', page, re.S):
        add(label, value)
    # 3) highlight spec cards: <h5 class="title">PAYLOAD</h5><p class="value">260Lbs</p>
    #    (UrbanGlide payload/load cards + GrandTeton spec_item cards). The title→value
    #    adjacency excludes the comparison cells, whose values are icon-led with no title.
    for label, value in re.findall(
            r'class="title"[^>]*>\s*([^<]+?)\s*</[^>]+>\s*<[^>]+\bclass="value"[^>]*>\s*([^<]+?)\s*</',
            page, re.S):
        add(label, value)
    # 4) trim-comparison table (current model = column 0): fills fork, sensor, the correct
    #    per-trim weight, battery, etc. that the UrbanGlide flat list leaves out
    for lab, val in _comparison_col0(page).items():
        add(lab, val)
    # 5) battery fallback from the description when nothing above yielded one
    if "Battery" not in out:
        m = re.search(r"(\d{2}\s*v[^.]{0,60}?\d{3,4}\s*wh[^.]{0,40}?(?:battery|cells)?)",
                      _clean(body_html), re.I) or re.search(r"(\d{3,4}\s*wh)", _clean(body_html), re.I)
        if m:
            add("Battery", m.group(1))
    return out


def compare_specs() -> dict:
    """Per-model highlight params from the model-comparison page carousel
    (`/pages/compare-models`): {handle: {label: value}}. The page redirects bots away
    from its JS-loaded slides, so only the few server-rendered ones are available -- but
    those uniquely carry a bike's overall Load Capacity, which the product pages omit."""
    page = fetch_html(f"{BASE}/pages/compare-models")
    out: dict[str, dict] = {}
    for link, body in re.findall(
            r'data-link="(/products/[^"]+)"(.*?)(?=data-link="/products/|$)', page, re.S):
        items = {_clean(n): _clean(v) for n, v in re.findall(
            r'<div class="item-name">(.*?)</div>\s*<div class="item-param">(.*?)</div>', body, re.S)}
        if items:
            out[link.rsplit("/", 1)[-1]] = items
    return out


def discover_logo() -> str:
    page = fetch_html(BASE)
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
    if m:
        return m.group(1)
    m = re.search(r'src="(//[^"]*cdn/shop/[^"]*logo[^"]*\.(?:png|webp|svg))"', page, re.I)
    return ("https:" + m.group(1)) if m else ""


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/collections/{COLLECTION}/products.json?limit=250")
    compare = compare_specs()
    models = []
    for p in data.get("products", []):
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
        # per-variant configurations WITH availability (Shopify variants carry
        # `available`) so a fully sold-out bike is recognised as such downstream.
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
                "available": bool(v.get("available")),
                "sku": v.get("sku"),
            })
        url = f"{BASE}/products/{p['handle']}"
        page = fetch_html(url)
        specs = parse_specs(page, p.get("body_html") or "")
        # Fill fields that only the model-comparison section carries (e.g. a bike's overall
        # Load Capacity / Max Load, which the product spec sheet omits).
        cmp = compare.get(p["handle"], {})
        if not any(k in specs for k in ("Max Load", "Maximum Load Capacity")):
            load = cmp.get("Max Load") or cmp.get("Load Capacity")
            if load:
                specs["Max Load"] = load
        if "Weight" not in specs and cmp.get("Lightweight"):
            specs["Weight"] = cmp["Lightweight"]
        fs = frame_sizes(page)
        if not fs:
            # some models (Cycanon) carry the rider-height range in the "Frame Size" field
            # ("One Size (4'11"-6'2")") rather than the Size & Fit geo-toggle
            mm = _height_minmax(specs.get("Frame Size", ""))
            if mm:
                f = lambda v: f"{int(v) // 12}'{int(v) % 12}\""
                fs = [{"size": None, "height_min": f(mm[0]), "height_max": f(mm[1])}]
        models.append({
            "model": clean_title(title),
            "handle": p.get("handle"),
            "url": url,
            "product_types": classify_product_types(
                title, p.get("product_type") or "", " ".join(p.get("tags") or [])),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
            "configurations": configurations,
            # per-size rider-height ranges (Size & Fit geo-toggle, or Frame Size fallback)
            "frame_sizes": fs,
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
    out = {"source": BASE, "logo": discover_logo(), "collection": COLLECTION,
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Vanpowers e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/vanpowers_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
