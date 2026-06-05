#!/usr/bin/env python3
"""
Lectric eBikes spec scraper.

Lectric's Shopify catalog lists each color/config as a *separate* product (~39
SKUs). This scraper groups those SKUs into ~8 model families (by product_type),
then uses Playwright to open one product page per spec-distinct config and pull:

  * physical + technical specifications (headline tiles + feature cards),
  * the "included" free-with-purchase accessory bundle and paid add-on upgrades,

and merges everything to the model level (keeping the most specific value on
collisions, while preserving every config's specs under `configs`). Each model
also lists its feature options: colors (name / hex / image), frame styles, and
battery/performance configs.

Usage:
    python scrape_lectric.py                  # all models -> lectric_ebikes.json
    python scrape_lectric.py --limit 2        # quick test (first 2 families)
    python scrape_lectric.py -o out.json      # custom output path
    python scrape_lectric.py --concurrency 3  # parallel product pages
    python scrape_lectric.py --headed         # watch the browser
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --- Make the locally-extracted Chromium system libs discoverable, if present. ---
_DEPS = Path(__file__).parent / ".chromium-deps" / "root"
if _DEPS.exists():
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join([
        str(_DEPS / "usr/lib/x86_64-linux-gnu"),
        str(_DEPS / "lib/x86_64-linux-gnu"),
        os.environ.get("LD_LIBRARY_PATH", ""),
    ]).strip(os.pathsep)

from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

BASE = "https://lectricebikes.com"
LOGO = "https://lectricebikes.com/cdn/shop/files/logo-t.png?v=1722462393&width=500"
COLLECTION = "ebikes"

# product_type code -> clean model display name.
FAMILY_NAMES = {
    "Bike-4": "Lectric XP4",
    "XPress-2": "Lectric XPress2",
    "XPress-1": "Lectric XPress1",
    "Trike-2": "Lectric XP Trike2",
    "xpl-2": "Lectric XP Lite2",
    "XPeak-2": "Lectric XPeak2",
    "XPed-2": "Lectric XPedition2",
    "one-bike-1": "Lectric ONE",
}
TRIKE_TYPES = {"Trike-2"}

# Fallback curated brand-color approximations, keyed by color name. The scraper
# normally reads the real hex from each color button's SVG fill (see JS_COLORS);
# this map is only used when a button/fill isn't available for a color.
COLOR_HEX = {
    "Tempest Grey": "#44474a",
    "Stratus White": "#e9eaec",
    "Arctic White": "#f2f3f5",
    "Raindrop Blue": "#3a6b8a",
    "Lectric Blue": "#00a3e0",
    "Glacier Blue": "#b7d3e8",
    "Dusk Blue": "#3b4a63",
    "Pine Green": "#2f4a3a",
    "Sandstorm": "#d9c08a",
    "JW Black": "#1a1a1a",
    "Lavender Haze": "#9b8bb4",
    "Phoenix Red": "#c0322b",
}
# Longest names first so "Arctic White" wins over a hypothetical "White".
COLOR_NAMES = sorted(COLOR_HEX, key=len, reverse=True)

# Spec-label classification (shared approach with scrape_aventon.py).
TECHNICAL_KEYWORDS = (
    "motor", "battery", "range", "charger", "charging", "controller", "throttle",
    "display", "sensor", "pedal assist", "riding mode", "speed", "class", "watt",
    "voltage", "wireless", "connectivity", "gps", "app", "certification",
    "torque", "power", "assist", "keyless",
)
PHYSICAL_KEYWORDS = (
    "weight", "payload", "capacity", "limit", "height", "frame", "fork", "wheel",
    "tire", "tyre", "brake", "rotor", "derailleur", "shifter", "chain", "cassette",
    "gear", "crank", "pedal", "saddle", "seat", "handlebar", "grip", "headset",
    "kickstand", "rack", "fender", "light", "headlight", "stem", "spoke", "hub",
    "dimension", "length", "width", "fold", "foldable", "color", "size", "step",
    "assembly", "rider",
)


def classify(label: str) -> str:
    low = label.lower()
    for kw in PHYSICAL_KEYWORDS:
        if kw in low:
            return "physical"
    for kw in TECHNICAL_KEYWORDS:
        if kw in low:
            return "technical"
    return "physical"


# ----------------------------- catalog discovery -----------------------------

def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def parse_color(title: str) -> str | None:
    for name in COLOR_NAMES:
        if name.lower() in title.lower():
            return name
    return None


def parse_frame(title: str, handle: str) -> str:
    blob = f"{title} {handle}".lower()
    if "step-thru" in blob or "step thru" in blob or "step-through" in blob:
        return "Step-Thru"
    return "High-Step"


def parse_battery(title: str, handle: str, tags: list[str]) -> str:
    blob = f"{title} {handle} {' '.join(tags)}".lower()
    parts = []
    if "dual" in blob:
        parts.append("Dual-Battery")
    if "long-range" in blob or "long range" in blob or "longrange" in blob:
        parts.append("Long-Range")
    if "750" in blob and "Long-Range" not in parts:
        parts.append("750")
    return " ".join(parts) if parts else "Standard"


def msrp_from_tags(tags: list[str]) -> float | None:
    for t in tags:
        m = re.match(r"MSRP:(\d+)", t)
        if m:
            return float(m.group(1))
    return None


def discover_skus() -> list[dict]:
    skus = []
    page = 1
    while True:
        data = fetch_json(
            f"{BASE}/collections/{COLLECTION}/products.json?limit=250&page={page}"
        )
        products = data.get("products", [])
        if not products:
            break
        for p in products:
            variants = p.get("variants", [])
            prices = [float(v["price"]) for v in variants if v.get("price")]
            images = [img.get("src") for img in p.get("images", []) if img.get("src")]
            skus.append({
                "title": p["title"],
                "handle": p["handle"],
                "url": f"{BASE}/products/{p['handle']}",
                "product_type": p.get("product_type"),
                "tags": p.get("tags", []),
                "price": min(prices) if prices else msrp_from_tags(p.get("tags", [])),
                "image": images[0] if images else None,
                "color": parse_color(p["title"]),
                "frame_style": parse_frame(p["title"], p["handle"]),
                "battery": parse_battery(p["title"], p["handle"], p.get("tags", [])),
            })
        if len(products) < 250:
            break
        page += 1
    return skus


def group_families(skus: list[dict]) -> dict[str, dict]:
    fams: dict[str, dict] = {}
    for s in skus:
        code = s["product_type"]
        fam = fams.setdefault(code, {
            "family_code": code,
            "model": FAMILY_NAMES.get(code, code),
            "vehicle_type": "trike" if code in TRIKE_TYPES else "bike",
            "skus": [],
        })
        fam["skus"].append(s)
    return fams


def pick_config_skus(skus: list[dict]) -> list[dict]:
    """One representative SKU per (frame_style, battery) config (color-agnostic)."""
    seen, chosen = set(), []
    for s in skus:
        key = (s["frame_style"], s["battery"])
        if key not in seen:
            seen.add(key)
            chosen.append(s)
    return chosen


# ------------------------------ page extraction ------------------------------

JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const result = {tiles: [], cards: []};
    const grid = document.querySelector('#productFeaturesDesktop, .product-features-grid');
    if (grid) {
        for (const it of grid.querySelectorAll('.feature-item')) {
            // Label + value are the non-icon child elements. textContent is used
            // so values are still read when a tab panel is collapsed/hidden.
            const parts = [...it.children]
                .filter(c => !c.classList.contains('icon'))
                .map(c => norm(c.textContent)).filter(Boolean);
            let label = null, value = '';
            if (parts.length >= 2) { label = parts[0]; value = parts.slice(1).join(' '); }
            else {
                const lines = (it.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
                if (lines.length) { label = lines[0]; value = lines.slice(1).join(' '); }
            }
            if (label) result.tiles.push([label, value]);
        }
    }
    for (const li of document.querySelectorAll('#specifications .specifications-list li')) {
        const name = norm(li.querySelector('h3')?.textContent);
        const detail = norm(li.querySelector('p')?.textContent);
        if (name && detail) result.cards.push([name, detail]);
    }
    return result;
}"""

JS_ACCESSORIES = r"""() => {
    const out = [];
    for (const r of document.querySelectorAll('.upsell-row')) {
        const txt = (r.innerText || '').replace(/\s+/g, ' ').trim();
        if (!txt) continue;
        const name = (r.querySelector('h3,h4,strong,.upsell-title,[class*=title]')?.innerText || '').trim()
                   || txt.split('$')[0].trim();
        const pm = txt.match(/\$([0-9][0-9.,]*)/);
        const free = /\bFREE\b/i.test(txt) || /\bincluded\b/i.test(txt);
        out.push({name, price: pm ? parseFloat(pm[1].replace(/,/g, '')) : null, free});
    }
    return out;
}"""

JS_PERF = r"""() => {
    const sel = '.config-v-b-perf-combos .combo-item-wrapper, .config-v-b-perf-combos [class*=combo-item]';
    const seen = new Set(), out = [];
    for (const e of document.querySelectorAll(sel)) {
        const t = (e.innerText || '').replace(/\s+/g, ' ').trim();
        if (t && !seen.has(t)) { seen.add(t); out.push(t); }
    }
    return out;
}"""

# Colors from the PDP configurator. Each color button is an SVG bike silhouette
# whose largest <path> is filled with the actual color, so we read the hex
# straight from that fill. The button is an <a> linking to that color's product
# page, so its image resolves from the catalog (no need to click/navigate).
# Lectric's "Size Guide" section: <strong>label</strong><span>value</span>
# (Stand Over Height, Rider Height, Handlebar Reach, Seat to Ground, …).
JS_SIZE_GUIDE = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const out = {};
    for (const it of document.querySelectorAll('.size-guide__item')) {
        const label = norm(it.querySelector('strong')?.textContent);
        const value = norm(it.querySelector('span')?.textContent);
        if (label && value) out[label] = value;
    }
    return out;
}"""

JS_COLORS = r"""() => {
    const rgb2hex = s => {
        const m = s && s.match(/\d+(\.\d+)?/g);
        if (!m || m.length < 3) return null;
        const [r, g, b] = m.map(Number);
        return '#' + [r, g, b].map(x => Math.round(x).toString(16).padStart(2, '0')).join('');
    };
    const buttonHex = el => {
        let bestLen = -1, fill = null;
        for (const sh of el.querySelectorAll('path, polygon, rect')) {
            const f = getComputedStyle(sh).fill || sh.getAttribute('fill');
            if (!f || f === 'none') continue;
            const len = (sh.getAttribute('d') || '').length;   // largest shape = body
            if (len >= bestLen) { bestLen = len; fill = f; }
        }
        return rgb2hex(fill);
    };
    const out = [], seen = new Set();
    for (const el of document.querySelectorAll('.config-v-b-color-box-link, .config-v-b-color-box-div')) {
        let label = (el.querySelector('.config-v-b-color-label')?.innerText
                     || el.getAttribute('title') || '').trim();
        if (!label || label.includes('\n') || seen.has(label)) continue;
        const a = el.matches('a') ? el : el.querySelector('a');
        seen.add(label);
        out.push({label, href: a ? a.getAttribute('href') : null, hex: buttonHex(el)});
    }
    return out;
}"""


async def scrape_config(context, sku: dict, retries: int = 3) -> dict:
    cfg = {
        "label": f"{FAMILY_NAMES.get(sku['product_type'], '')} "
                 f"{sku['frame_style']} {sku['battery']}".strip(),
        "url": sku["url"],
        "frame_style": sku["frame_style"],
        "battery": sku["battery"],
        "price": sku["price"],
    }
    for attempt in range(1, retries + 1):
        page = await context.new_page()
        try:
            await page.goto(sku["url"], wait_until="domcontentloaded", timeout=60000)
            # networkidle is a good proxy for "the product SPA has finished
            # hydrating"; the heavy long-range/dual-battery pages need this.
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            # Lazy content (accessories/specs) renders as it scrolls into view.
            for _ in range(8):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(300)
            # Wait for the spec nodes to be attached (the Specifications tab panel
            # is often collapsed/hidden, so we don't wait for visibility).
            try:
                await page.wait_for_selector(
                    "#specifications .specifications-list li, #productFeaturesDesktop .feature-item",
                    state="attached", timeout=20000,
                )
            except Exception:
                pass
            # Poll until specs actually populate. The markup skeleton can attach
            # before its content fills, so we re-check for up to ~30s, alternating
            # scroll direction to keep lazy intersection-observers firing.
            raw = {"tiles": [], "cards": []}
            for i in range(30):
                raw = await page.evaluate(JS_SPECS)
                if raw["tiles"] or raw["cards"]:
                    break
                await page.mouse.wheel(0, 1800 if i % 2 == 0 else -1800)
                await page.wait_for_timeout(1000)

            accessories = await page.evaluate(JS_ACCESSORIES)
            perf = await page.evaluate(JS_PERF)
            cfg_colors = await page.evaluate(JS_COLORS)
            cfg["geometry"] = await page.evaluate(JS_SIZE_GUIDE)
            cfg["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()

            physical, technical, all_specs, features = {}, {}, {}, []
            for label, value in raw["tiles"]:
                key = " ".join(label.split())
                all_specs[key] = value
                (physical if classify(key) == "physical" else technical)[key] = value
            for name, detail in raw["cards"]:
                key = " ".join(name.split())
                features.append({"name": key, "detail": detail})
                all_specs.setdefault(key, detail)
                (physical if classify(key) == "physical" else technical).setdefault(key, detail)

            if not all_specs:
                raise RuntimeError("no specs extracted")

            cfg["specs"] = {"physical": physical, "technical": technical,
                            "all": all_specs, "features": features}
            cfg["accessories"] = {
                "included": [{"name": a["name"], "price": a["price"]}
                             for a in accessories if a["free"]],
                "add_ons": [{"name": a["name"], "price": a["price"]}
                            for a in accessories if not a["free"]],
            }
            cfg["performance_options"] = perf
            cfg["colors"] = cfg_colors
            cfg["error"] = None
            return cfg
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                cfg["specs"] = {"physical": {}, "technical": {}, "all": {}, "features": []}
                cfg["accessories"] = {"included": [], "add_ons": []}
                cfg["performance_options"] = []
                cfg["colors"] = []
                cfg["error"] = f"{type(e).__name__}: {e}"
                return cfg
            await asyncio.sleep(2.5 * attempt)  # cool down; load contention passes
    return cfg


# ------------------------------ model assembly -------------------------------

def merge_specs(configs: list[dict]) -> dict:
    """Merge config specs; on collision keep the most specific (longest) value."""
    physical, technical, all_specs = {}, {}, {}
    for cfg in configs:
        for bucket_name, bucket in (("physical", physical), ("technical", technical),
                                    ("all", all_specs)):
            for k, v in cfg["specs"].get(bucket_name, {}).items():
                if k not in bucket or len(str(v)) > len(str(bucket[k])):
                    bucket[k] = v
    return {"physical": physical, "technical": technical, "all": all_specs}


def merge_accessories(configs: list[dict]) -> dict:
    inc, add = {}, {}
    for cfg in configs:
        for a in cfg["accessories"].get("included", []):
            inc.setdefault(a["name"], a["price"])
        for a in cfg["accessories"].get("add_ons", []):
            add.setdefault(a["name"], a["price"])
    return {
        "included": [{"name": n, "price": p} for n, p in inc.items()],
        "add_ons": [{"name": n, "price": p} for n, p in add.items()],
    }


def build_colors(skus: list[dict], configs: list[dict], handle_img: dict) -> list[dict]:
    """Build [{name, hex, image}]. `hex` comes from the color button's SVG fill
    (the real swatch color), falling back to the curated COLOR_HEX map. `image`
    is the color's own product photo (the button links to that product page)."""
    # Color-correct image keyed by the color encoded in a SKU title.
    title_img = {s["color"]: s["image"] for s in skus if s["color"] and s["image"]}
    # Per-color data scraped from the configurator buttons (hex + link).
    cfg_colors: dict[str, dict] = {}
    for cfg in configs:
        for cc in cfg.get("colors", []):
            name = cc["label"]
            entry = cfg_colors.setdefault(name, {"hex": None, "href": None})
            if cc.get("hex") and not entry["hex"]:
                entry["hex"] = cc["hex"]
            if cc.get("href") and not entry["href"]:
                entry["href"] = cc["href"]

    fallback_img = next((s["image"] for s in skus if s["image"]), None)
    names = list(dict.fromkeys(list(title_img) + list(cfg_colors)))
    colors = []
    for name in names:
        cc = cfg_colors.get(name, {})
        img = title_img.get(name)
        if not img and cc.get("href"):
            img = handle_img.get(cc["href"].rstrip("/").split("/")[-1])
        hexv = cc.get("hex") or COLOR_HEX.get(name)
        colors.append({
            "name": name,
            "hex": hexv,
            # swatch_image is a fallback only (Lectric swatches are inline SVGs anyway).
            "swatch_image": None,
            "image": img or fallback_img,
        })
    return colors


def merge_geometry(configs: list[dict]) -> dict:
    """Combine each config's size-guide into per-model geometry: a dimension is a
    flat value when it's the same across configs, else {config_label: value}."""
    by_dim: dict = {}
    for c in configs:
        for dim, val in (c.get("geometry") or {}).items():
            by_dim.setdefault(dim, {})[c.get("label", "")] = val
    out = {}
    for dim, by_label in by_dim.items():
        vals = set(by_label.values())
        out[dim] = next(iter(vals)) if len(vals) == 1 else by_label
    return out


def build_model(fam: dict, configs: list[dict], handle_img: dict) -> dict:
    skus = fam["skus"]
    prices = [s["price"] for s in skus if s["price"] is not None]
    perf = []
    for c in configs:
        for p in c.get("performance_options", []):
            if p not in perf:
                perf.append(p)
    merged = merge_specs(configs)
    return {
        "model": fam["model"],
        "family_code": fam["family_code"],
        "vehicle_type": fam["vehicle_type"],
        "urls": [c["url"] for c in configs],
        "price_range": {
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
            "currency": "USD",
        },
        "options": {
            "colors": build_colors(skus, configs, handle_img),
            "frame_styles": sorted({s["frame_style"] for s in skus}),
            "battery": sorted({s["battery"] for s in skus}),
            "performance": perf,
        },
        "configs": configs,
        "specs": merged,
        "accessories": merge_accessories(configs),
        "warranty": next((c.get("warranty") for c in configs if c.get("warranty")), None),
        "geometry": merge_geometry(configs),
        "spec_count": len(merged["all"]),
        "scrape_error": next((c["error"] for c in configs if c["error"]), None),
    }


# ----------------------------------- main ------------------------------------

async def run(args) -> int:
    print(f"[*] Discovering SKUs from {BASE}/collections/{COLLECTION} ...", file=sys.stderr)
    skus = discover_skus()
    fams = group_families(skus)
    handle_img = {s["handle"]: s["image"] for s in skus if s["image"]}
    print(f"[*] {len(skus)} SKUs -> {len(fams)} model families.", file=sys.stderr)

    fam_list = list(fams.values())
    if args.limit:
        fam_list = fam_list[: args.limit]

    sem = asyncio.Semaphore(args.concurrency)
    models: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1366, "height": 1000},
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        )

        async def worker(fam):
            cfg_skus = pick_config_skus(fam["skus"])
            async with sem:
                configs = []
                for s in cfg_skus:           # sequential per family; sem caps families
                    configs.append(await scrape_config(context, s))
            model = build_model(fam, configs, handle_img)
            status = "ok" if model["spec_count"] else f"FAIL ({model['scrape_error']})"
            print(f"    - {model['model']:<22} {len(cfg_skus)} cfg  "
                  f"{model['spec_count']:>3} specs  "
                  f"{len(model['options']['colors'])} colors  [{status}]", file=sys.stderr)
            models.append(model)

        await asyncio.gather(*(worker(f) for f in fam_list))
        await context.close()
        await browser.close()

    models.sort(key=lambda m: m["model"])
    out = {
        "source": BASE, "logo": LOGO,
        "collection": COLLECTION,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(models),
        "models": models,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for m in models if m["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(models)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Lectric eBike specifications.")
    ap.add_argument("-o", "--output", default="data/lectric_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N families.")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="Parallel families. Heavy PDPs hydrate unreliably when "
                         "loaded concurrently; default 1 (sequential) is the most "
                         "reliable for unattended runs.")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
