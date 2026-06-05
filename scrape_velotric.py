#!/usr/bin/env python3
"""
Velotric e-bike spec scraper.

Velotric is a Shopify store. Models are discovered from the electric-bikes
collection feed; each product page is then rendered with Playwright to extract
the specification grid. Colors are emitted as {name, hex, image}:

  * name  -- the Shopify "Color" variant option value,
  * image -- that color's variant photo (from the catalog feed),
  * hex   -- read from the page's `data-colors-patterns` map (a Velotric
             ColorName::#hex lookup embedded in the swatch markup).

Output JSON mirrors the Aventon/Lectric scrapers.

Usage:
    python scrape_velotric.py                  # all models -> velotric_ebikes.json
    python scrape_velotric.py --limit 3        # quick test (first 3 models)
    python scrape_velotric.py -o out.json      # custom output path
    python scrape_velotric.py --concurrency 3  # parallel product pages
    python scrape_velotric.py --headed         # watch the browser
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

_DEPS = Path(__file__).parent / ".chromium-deps" / "root"
if _DEPS.exists():
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join([
        str(_DEPS / "usr/lib/x86_64-linux-gnu"),
        str(_DEPS / "lib/x86_64-linux-gnu"),
        os.environ.get("LD_LIBRARY_PATH", ""),
    ]).strip(os.pathsep)

from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

BASE = "https://www.velotricbike.com"
LOGO = "https://www.velotricbike.com/cdn/shop/files/20230607-183010.png?v=1686133833&width=256"
COLLECTION = "electric-bikes"

TECHNICAL_KEYWORDS = (
    "motor", "battery", "cell", "charger", "range", "controller", "throttle",
    "display", "sensor", "pedal assist", "walk mode", "speed", "class", "watt",
    "voltage", "usb", "app", "anti-theft", "water resistant", "torque", "power",
    "wireless", "connectivity", "gps",
)
PHYSICAL_KEYWORDS = (
    "weight", "height", "size", "frame", "fork", "wheel", "tire", "tyre", "brake",
    "rotor", "derailleur", "shift", "chain", "cassette", "freewheel", "gear",
    "crank", "chainring", "pedal", "saddle", "seat", "handlebar", "grip", "stem",
    "headset", "kickstand", "rack", "fender", "light", "spoke", "hub", "rim",
    "dimension", "suspension", "color",
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


def build_colors(color_values, color_idx, variants, fallback_image):
    """[{name, hex(None), image}] -- hex is filled later from the PDP map."""
    colors = []
    for name in color_values:
        img = None
        if color_idx is not None:
            for v in variants:
                if v.get(f"option{color_idx}") == name:
                    fi = v.get("featured_image")
                    if fi and fi.get("src"):
                        img = fi["src"]
                        break
        colors.append({"name": name, "hex": None, "swatch_image": None,
                       "image": img or fallback_image})
    return colors


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
            if o["name"].lower() == "color":
                color_values = o.get("values", [])
                color_idx = i + 1
            else:
                options[o["name"]] = o.get("values", [])
        options["colors"] = build_colors(color_values, color_idx, variants, fallback)

        models.append({
            "model": p.get("title"),
            "handle": p.get("handle"),
            "url": f"{BASE}/products/{p['handle']}",
            "product_type": p.get("product_type"),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
        })
    return models


# ------------------------------ page extraction ------------------------------

# Velotric uses two spec templates across the lineup, so try both.
JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const out = [];
    // Layout A: newer models -> .specs-components grid (value per size variant).
    for (const t of document.querySelectorAll('.specs-components-grid-item-title')) {
        const content = t.parentElement.querySelector('.specs-components-grid-item-content');
        let val = '';
        if (content) {
            const variants = [...content.querySelectorAll('.specs-variant')]
                .map(v => norm(v.innerText)).filter(Boolean);
            val = variants[0] || norm(content.innerText);
        }
        const label = norm(t.innerText);
        if (label && val) out.push([label, val]);
    }
    if (out.length) return out;
    // Layout B: older models -> dl.specifications-list with .spe-row entries.
    for (const row of document.querySelectorAll('.specifications-list .spe-row, .spe-row')) {
        const label = norm(row.querySelector('.spe-row-title')?.innerText);
        const val = norm(row.querySelector('.spe-row-content')?.innerText);
        if (label && val) out.push([label, val]);
    }
    if (out.length) return out;
    // Layout C: fallback to the highlight blocks.
    for (const blk of document.querySelectorAll('.spec-block')) {
        const label = norm(blk.querySelector('.spec-title')?.innerText);
        const val = norm(blk.querySelector('.spec-subtitle')?.innerText);
        if (label && val) out.push([label, val]);
    }
    return out;
}"""

JS_COLOR_PATTERNS = r"""() => {
    const el = document.querySelector('[data-colors-patterns]');
    return el ? el.getAttribute('data-colors-patterns') : null;
}"""

# Swatch background-image per color name (Velotric uses image swatches for some
# colours, e.g. camo patterns).
JS_SWATCH_IMG = r"""() => {
    const urlOf = bi => {
        const m = bi && bi.match(/url\("?(.*?)"?\)/);
        if (!m) return null;
        return m[1].startsWith('//') ? 'https:' + m[1] : m[1];
    };
    const out = {};
    const els = document.querySelectorAll(
        'shape-swatch[data-color], [class*=color-swatch-select-parent], [class*=color-swatch]');
    for (const el of els) {
        const name = (el.getAttribute('data-color') || el.getAttribute('title') || '').trim();
        if (!name || out[name.toLowerCase()]) continue;
        for (const c of [el, ...el.querySelectorAll('*')]) {
            const u = urlOf(getComputedStyle(c).backgroundImage);
            if (u && !/gradient/.test(u)) { out[name.toLowerCase()] = u; break; }
        }
    }
    return out;
}"""


def parse_color_hex(raw: str | None) -> dict:
    """Parse Velotric's 'Name::#hex/#hex/...' lines into {name_lower: base_hex}."""
    out = {}
    if not raw:
        return out
    for line in raw.split("\n"):
        line = line.strip()
        if "::" not in line:
            continue
        name, spec = line.split("::", 1)
        m = re.search(r"#[0-9a-fA-F]{3,6}", spec)  # first hex = base colour
        if m:
            out[name.strip().lower()] = m.group(0).upper()
    return out


async def scrape_model(context, model: dict, retries: int = 3) -> dict:
    result = dict(model)
    for attempt in range(1, retries + 1):
        page = await context.new_page()
        try:
            await page.goto(model["url"], wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            for _ in range(16):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(250)
            # Best-effort wait; poll until the spec grid actually populates
            # (these heavy pages hydrate slowly, especially under load).
            try:
                await page.wait_for_selector(
                    ".specs-components-grid-item-title, .specifications-list, .spec-block",
                    state="attached", timeout=20000)
            except Exception:
                pass
            pairs = []
            for _ in range(20):
                pairs = await page.evaluate(JS_SPECS)
                if pairs:
                    break
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1000)
            patterns = await page.evaluate(JS_COLOR_PATTERNS)
            swatch_img = await page.evaluate(JS_SWATCH_IMG)
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()

            if not pairs:
                raise RuntimeError("no specs extracted")

            # Fill in real hex (from the color map) and swatch image (from the DOM).
            color_hex = parse_color_hex(patterns)
            for c in result["options"].get("colors", []):
                key = c["name"].strip().lower()
                if color_hex.get(key):
                    c["hex"] = color_hex[key]
                # swatch_image is a fallback only: set it only when no hex is known.
                if not c.get("hex") and swatch_img.get(key):
                    c["swatch_image"] = swatch_img[key]

            physical, technical, all_specs = {}, {}, {}
            for label, value in pairs:
                key = " ".join(label.split())
                all_specs[key] = value
                (physical if classify(key) == "physical" else technical)[key] = value

            result["specs"] = {"physical": physical, "technical": technical, "all": all_specs}
            result["spec_count"] = len(all_specs)
            result["scrape_error"] = None
            return result
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                result["specs"] = {"physical": {}, "technical": {}, "all": {}}
                result["spec_count"] = 0
                result["warranty"] = None
                result["scrape_error"] = f"{type(e).__name__}: {e}"
                return result
            await asyncio.sleep(2.0 * attempt)
    return result


# ----------------------------------- main ------------------------------------

async def run(args) -> int:
    print(f"[*] Discovering models from {BASE}/collections/{COLLECTION} ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    print(f"[*] Found {len(models)} e-bike model(s).", file=sys.stderr)

    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1366, "height": 1000},
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        )

        async def worker(m):
            async with sem:
                r = await scrape_model(context, m)
            status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
            ncol = len(r["options"].get("colors", []))
            print(f"    - {r['model'][:34]:<34} {r['spec_count']:>3} specs  "
                  f"{ncol} colors  [{status}]", file=sys.stderr)
            results.append(r)

        await asyncio.gather(*(worker(m) for m in models))
        await context.close()
        await browser.close()

    results.sort(key=lambda r: r["model"] or "")
    out = {
        "source": BASE, "logo": LOGO,
        "collection": COLLECTION,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(results),
        "models": results,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Velotric e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/velotric_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N models.")
    ap.add_argument("--concurrency", type=int, default=2,
                    help="Parallel pages. Heavy PDPs hydrate slowly; 2 is reliable.")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
