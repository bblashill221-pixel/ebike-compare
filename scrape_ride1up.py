#!/usr/bin/env python3
"""
Ride1Up e-bike spec scraper.

Ride1Up runs on WooCommerce (not Shopify). Models are discovered from the
"bikes" category grid, then Playwright opens each product page to extract:

  * physical + technical specifications (the "Components & Tech Specs" list),
  * available options (the WooCommerce variation attributes: frame type,
    drivetrain, color, ...),
  * colors as {name, hex, image} -- the hex is sampled from the swatch image's
    pixels (Ride1Up uses image swatches, not solid-color chips), and the image
    is the color's own variation photo.

Output JSON mirrors the Aventon/Lectric scrapers.

Usage:
    python scrape_ride1up.py                  # all models -> ride1up_ebikes.json
    python scrape_ride1up.py --limit 2        # quick test (first 2 models)
    python scrape_ride1up.py -o out.json      # custom output path
    python scrape_ride1up.py --concurrency 2  # parallel product pages
    python scrape_ride1up.py --headed         # watch the browser
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

BASE = "https://ride1up.com"
LOGO = "https://ride1up.com/wp-content/uploads/2021/01/ride1up.svg"
BIKES_CATEGORY = f"{BASE}/product-category/bikes/?per_page=50"

TECHNICAL_KEYWORDS = (
    "motor", "battery", "range", "charger", "charging", "controller", "throttle",
    "display", "sensor", "pas", "pedal assist", "speed", "class", "watt", "voltage",
    "wireless", "connectivity", "gps", "app", "torque", "power", "drive", "assist",
)
PHYSICAL_KEYWORDS = (
    "weight", "payload", "rating", "frame", "fork", "wheel", "tire", "tyre", "brake",
    "rotor", "derailleur", "shifter", "chain", "cassette", "gear", "drivetrain",
    "crank", "pedal", "saddle", "seat", "handlebar", "stem", "grip", "headset",
    "kickstand", "rack", "fender", "light", "headlight", "spoke", "hub", "dimension",
    "suspension", "color", "size",
)


def classify(label: str) -> str:
    low = label.lower()
    for kw in PHYSICAL_KEYWORDS:
        if kw in low:
            return "physical"
    for kw in TECHNICAL_KEYWORDS:
        if kw in low:
            return "technical"
    return "technical"


# ----------------------------- catalog discovery -----------------------------

def discover_models() -> list[dict]:
    """Parse the bikes-category product grid for the current model lineup."""
    req = urllib.request.Request(BIKES_CATEGORY, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", "ignore")
    # Restrict to the main product grid (ul.products.columns-*).
    m = re.search(r'<ul[^>]*class="[^"]*products[^"]*columns[^"]*"[^>]*>(.*?)</ul>',
                  html, re.S)
    region = m.group(1) if m else html
    urls = re.findall(r'href="(https://ride1up\.com/product/[a-z0-9-]+/)"', region)
    models = []
    seen = set()
    for u in urls:
        slug = u.rstrip("/").rsplit("/", 1)[-1]
        if slug in seen:
            continue
        seen.add(slug)
        models.append({"slug": slug, "url": u})
    return models


# ------------------------------ page extraction ------------------------------

# Variations + attribute option names from the WooCommerce variations form.
# Per-frame sizing: Ride1Up's chart tabs are frame variants (ST/XR), each with a
# rider-height range (detailed dims are in a diagram image, not text).
JS_GEOMETRY = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const tabs = [...document.querySelectorAll('.frame-size-tabs button')].map(b => norm(b.innerText));
    const secs = [...document.querySelectorAll('.frame-size-section')];
    const byFrame = {};
    secs.forEach((sec, i) => {
        const frame = tabs[i] || ('Variant ' + (i + 1));
        const t = norm(sec.innerText);
        let m = t.match(/Rider Height Range:.*?(\d+'\s*\d*"?\s*[-–]\s*\d+'\s*\d*")/i);
        if (!m) m = t.match(/Rider Height Range:\s*([^*]+?)(?:\s+\d+'\d*"?\/|\s*\*|$)/i);
        if (m) byFrame[frame] = norm(m[1]);
    });
    return Object.keys(byFrame).length ? {"Rider Height Range": byFrame} : {};
}"""

JS_VARIATIONS = r"""() => {
    const form = document.querySelector('form.variations_form');
    const out = {variations: [], attributes: {}};
    if (!form) return out;
    try { out.variations = JSON.parse(form.getAttribute('data-product_variations') || '[]'); }
    catch (e) { out.variations = []; }
    for (const sel of form.querySelectorAll('select[name^="attribute_"]')) {
        const attr = sel.getAttribute('name');
        const opts = {};
        for (const o of sel.querySelectorAll('option')) {
            if (o.value) opts[o.value] = o.textContent.trim();
        }
        out.attributes[attr] = opts;
    }
    return out;
}"""

# Canonical spec sheet: the "Components & Tech Specs" list (title -> subtitle),
# plus the headline highlight grid (<h3>UPPERCASE</h3> -> value).
JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const components = [], highlights = [];
    for (const row of document.querySelectorAll('.component-text')) {
        const title = norm(row.querySelector('.component-title')?.innerText);
        const sub = norm(row.querySelector('.component-subtitle')?.innerText);
        if (title && sub) components.push([title, sub]);
    }
    for (const h of document.querySelectorAll('h3')) {
        const head = norm(h.innerText);
        if (!head || head !== head.toUpperCase() || head.length > 22) continue;
        let v = norm(h.nextElementSibling?.innerText);
        if (!v) {
            const pt = norm(h.parentElement?.innerText);
            if (pt.startsWith(head)) v = norm(pt.slice(head.length));
        }
        if (v) highlights.push([head, v]);
    }
    return {components, highlights};
}"""

# Color swatch -> hex. Ride1Up swatches are background images, so we sample the
# image's centre pixel on a canvas (same-origin, so the canvas isn't tainted).
# Solid-colour swatches fall back to the computed background-color.
JS_COLOR_HEX = r"""async () => {
    const toHex = (r, g, b) =>
        '#' + [r, g, b].map(x => Math.round(x).toString(16).padStart(2, '0')).join('');
    const rgb2hex = s => {
        const m = s && s.match(/\d+(\.\d+)?/g);
        return (m && m.length >= 3) ? toHex(+m[0], +m[1], +m[2]) : null;
    };
    const cont = document.querySelector('.tawcvs-swatches[data-attribute_name="attribute_pa_color"]');
    const out = {};
    if (!cont) return out;
    for (const sw of cont.querySelectorAll('.swatch')) {
        const slug = sw.getAttribute('data-value');
        if (!slug) continue;
        const cs = getComputedStyle(sw);
        const m = cs.backgroundImage && cs.backgroundImage.match(/url\("?(.*?)"?\)/);
        if (m) {
            // Image swatch: keep the image link and also sample a representative hex.
            const entry = {hex: null, swatch_image: m[1]};
            try {
                const img = new Image();
                img.crossOrigin = 'anonymous';
                img.src = m[1];
                await img.decode();
                const c = document.createElement('canvas');
                c.width = img.naturalWidth; c.height = img.naturalHeight;
                const ctx = c.getContext('2d');
                ctx.drawImage(img, 0, 0);
                const d = ctx.getImageData(Math.floor(c.width / 2), Math.floor(c.height / 2), 1, 1).data;
                entry.hex = toHex(d[0], d[1], d[2]);
            } catch (e) { entry.hex = rgb2hex(cs.backgroundColor); }
            out[slug] = entry;
        } else {
            out[slug] = {hex: rgb2hex(cs.backgroundColor), swatch_image: null};
        }
    }
    return out;
}"""


def color_image_for(slug: str, variations: list[dict]) -> str | None:
    """First variation image whose color attribute matches `slug`."""
    for v in variations:
        if v.get("attributes", {}).get("attribute_pa_color") == slug:
            img = v.get("image") or {}
            src = img.get("full_src") or img.get("src")
            if src:
                return src
    return None


def build_options(attributes: dict, color_hex: dict, variations: list[dict],
                  fallback_image: str | None) -> dict:
    """Map WooCommerce attributes -> options dict. `pa_color` becomes the
    {name, hex, image} colors list; other attributes become value-name lists."""
    options: dict = {}
    colors = []
    for attr, values in attributes.items():
        key = attr.replace("attribute_pa_", "").replace("attribute_", "")
        if key == "color":
            for slug, name in values.items():
                entry = color_hex.get(slug) or {}
                hexv = entry.get("hex")
                colors.append({
                    "name": name,
                    "hex": hexv,
                    # swatch_image is a fallback only: drop it when a hex is known.
                    "swatch_image": None if hexv else entry.get("swatch_image"),
                    "image": color_image_for(slug, variations) or fallback_image,
                })
        else:
            options[key] = list(values.values())
    options["colors"] = colors
    return options


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
            await page.wait_for_timeout(1200)
            for _ in range(12):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(250)
            await page.wait_for_selector(".component-text", state="attached", timeout=15000)

            name = (await page.evaluate(
                "() => (document.querySelector('h1.product_title, h1')?.innerText || '').trim()"
            )) or model["slug"]
            var = await page.evaluate(JS_VARIATIONS)
            raw = await page.evaluate(JS_SPECS)
            geometry = await page.evaluate(JS_GEOMETRY)
            color_hex = await page.evaluate(JS_COLOR_HEX)
            fallback_image = await page.evaluate(
                "() => document.querySelector('meta[property=\"og:image\"]')?.content "
                "|| document.querySelector('.woocommerce-product-gallery img')?.src || null"
            )
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()

            variations = var.get("variations") or []
            physical, technical, all_specs = {}, {}, {}
            for label, value in raw["components"]:
                key = " ".join(label.split())
                all_specs[key] = value
                (physical if classify(key) == "physical" else technical)[key] = value
            # Add headline highlights that aren't already covered (case-insensitive).
            lower = {k.lower() for k in all_specs}
            for label, value in raw["highlights"]:
                key = " ".join(label.split())
                if key.lower() in lower:
                    continue
                all_specs[key] = value
                (physical if classify(key) == "physical" else technical)[key] = value

            if not all_specs:
                raise RuntimeError("no specs extracted")

            prices = [float(v["display_price"]) for v in variations
                      if v.get("display_price") is not None]
            attrs = var.get("attributes", {})
            result["model"] = name
            result["price_range"] = {
                "min": min(prices) if prices else None,
                "max": max(prices) if prices else None,
                "currency": "USD",
            }
            # Every configuration (variant) with its own price, not just the range.
            result["configurations"] = [
                {
                    "options": {a.replace("attribute_pa_", "").replace("attribute_", ""):
                                attrs.get(a, {}).get(slug, slug)
                                for a, slug in v.get("attributes", {}).items()},
                    "price": float(v["display_price"]) if v.get("display_price") is not None else None,
                    "sku": v.get("sku"),
                }
                for v in variations
            ]
            result["options"] = build_options(var.get("attributes", {}), color_hex,
                                               variations, fallback_image)
            result["geometry"] = geometry
            result["specs"] = {"physical": physical, "technical": technical, "all": all_specs}
            result["spec_count"] = len(all_specs)
            result["scrape_error"] = None
            return result
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                result.setdefault("model", model["slug"])
                result["price_range"] = {"min": None, "max": None, "currency": "USD"}
                result["options"] = {"colors": []}
                result["specs"] = {"physical": {}, "technical": {}, "all": {}}
                result["configurations"] = []
                result["spec_count"] = 0
                result["warranty"] = None
                result["scrape_error"] = f"{type(e).__name__}: {e}"
                return result
            await asyncio.sleep(2.0 * attempt)
    return result


# ----------------------------------- main ------------------------------------

async def run(args) -> int:
    print(f"[*] Discovering models from {BASE} bikes category ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    print(f"[*] Found {len(models)} bike model(s).", file=sys.stderr)

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
            print(f"    - {r.get('model', m['slug'])[:30]:<30} {r['spec_count']:>3} specs  "
                  f"{ncol} colors  [{status}]", file=sys.stderr)
            results.append(r)

        await asyncio.gather(*(worker(m) for m in models))
        await context.close()
        await browser.close()

    results.sort(key=lambda r: r.get("model") or r["slug"])
    out = {
        "source": BASE, "logo": LOGO,
        "category": "bikes",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(results),
        "models": results,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Ride1Up e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/ride1up_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N models.")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
