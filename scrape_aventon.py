#!/usr/bin/env python3
"""
Aventon e-bike spec scraper.

Discovers every e-bike model from Aventon's Shopify catalog, then uses Playwright
to open each product page, open the "Technical Specifications" drawer, and extract
the full label/value spec table. Specs are split into `physical` and `technical`
groups (and a flat `all` map) and written to JSON.

Usage:
    python scrape_aventon.py                  # scrape all models -> aventon_ebikes.json
    python scrape_aventon.py -o out.json      # custom output file
    python scrape_aventon.py --limit 3        # only first 3 models (quick test)
    python scrape_aventon.py --headed         # show the browser
    python scrape_aventon.py --concurrency 4  # parallel product pages (default 3)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --- Make the locally-extracted Chromium system libs discoverable, if present. ---
# (This env must be set before Playwright launches the browser subprocess.)
_DEPS = Path(__file__).parent / ".chromium-deps" / "root"
if _DEPS.exists():
    _libdirs = [
        str(_DEPS / "usr/lib/x86_64-linux-gnu"),
        str(_DEPS / "lib/x86_64-linux-gnu"),
    ]
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(
        _libdirs + [os.environ.get("LD_LIBRARY_PATH", "")]
    ).strip(os.pathsep)

from playwright.async_api import async_playwright, TimeoutError as PWTimeout  # noqa: E402
from warranty_js import JS_WARRANTY

BASE = "https://www.aventon.com"
LOGO = "https://aventon.imgix.net/aventon_favicon_72.png?w=256"
COLLECTION = "ebikes"
SPEC_TRIGGERS = [
    "Technical Specifications",
    "Tech specs",
    "Specifications",
    "Full Specs",
    "Specs",
]

# Label keywords used to classify each spec into a physical vs technical bucket.
# Matching is case-insensitive substring on the spec label. First match wins;
# anything unmatched falls through to TECHNICAL_KEYWORDS, then to "physical".
TECHNICAL_KEYWORDS = (
    "motor", "battery", "range", "charger", "charging", "controller", "throttle",
    "display", "sensor", "pedal assist", "speed", "class", "watt", "voltage",
    "wireless", "connectivity", "gps", "app", "certification", "water resistance",
    "torque", "power",
)
PHYSICAL_KEYWORDS = (
    "weight", "limit", "height", "frame", "fork", "spacing", "wheel", "tire",
    "tyre", "brake", "rotor", "derailleur", "shifter", "chain", "cassette",
    "chainring", "crank", "bottom bracket", "pedal", "saddle", "seatpost",
    "seat post", "handlebar", "grip", "headset", "kickstand", "rack", "fender",
    "light", "stem", "spoke", "hub", "dimension", "length", "width", "color",
    "size", "style", "geometry",
)


def classify(label: str) -> str:
    """Return 'physical' or 'technical' for a spec label."""
    low = label.lower()
    for kw in PHYSICAL_KEYWORDS:
        if kw in low:
            return "physical"
    for kw in TECHNICAL_KEYWORDS:
        if kw in low:
            return "technical"
    return "physical"


# Fallback curated brand-color approximations, keyed by Aventon's (often
# non-literal) color names. The scraper normally reads the real hex from each
# on-page color swatch (see extract_swatch_hex); this map is only used when a
# swatch isn't found for a color. The per-color `image` is a color-correct
# variant photo.
COLOR_HEX = {
    "Stealth": "#2b2b2b",
    "Matte Stealth": "#2b2b2b",
    "Matte Black": "#1a1a1a",
    "Midnight Black": "#1a1a1a",
    "Matte Midnight Black": "#1a1a1a",
    "Anvil": "#52555a",
    "Basalt": "#4a4d4f",
    "Flint": "#6f7276",
    "Mica": "#8b8d8f",
    "Sterling": "#9ea1a4",
    "Haze": "#c7c9cc",
    "Matcha": "#8a9a5b",
    "Sage": "#9caf88",
    "Glacier Mint": "#b9e4d0",
    "Camouflage": "#4b5320",
    "Sandstone": "#c2a679",
    "Baja": "#caa472",
    "Java": "#5a3a22",
    "Koi": "#e8743b",
    "Sakura": "#f4c2c2",
    "Cobalt": "#1f3a93",
    "Cobalt Blue": "#1f3a93",
    "Blue Onyx": "#27374d",
    "Blue Steel": "#4a6b8a",
    "Matte Storm Blue": "#3b5266",
    "Pacific": "#2c5f7c",
    "Cerulean": "#2a7fb8",
    "Lagoon": "#2e8b8b",
    "Borealis": "#3a6b6b",
    "Tropos": "#4a7c8c",
    "Matte Aurora": "#6a8caf",
}


def build_colors(color_values: list[str], color_idx: int | None,
                 variants: list[dict], fallback_image: str | None) -> list[dict]:
    """Build [{name, hex, image}] for a model's colors (same shape as Lectric).

    `image` is the color-correct variant photo; `hex` is a best-effort curated
    approximation (null when the color name isn't in COLOR_HEX).
    """
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
        colors.append({"name": name, "hex": COLOR_HEX.get(name),
                       "swatch_image": None, "image": img or fallback_image})
    return colors


def discover_models() -> list[dict]:
    """Pull every e-bike from the Shopify products.json feed (paginated)."""
    models: list[dict] = []
    page = 1
    while True:
        url = f"{BASE}/collections/{COLLECTION}/products.json?limit=250&page={page}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        products = data.get("products", [])
        if not products:
            break
        for p in products:
            variants = p.get("variants", [])
            prices = [float(v["price"]) for v in variants if v.get("price")]
            images = [img.get("src") for img in p.get("images", []) if img.get("src")]
            fallback_image = images[0] if images else None

            # Split out the Color option into a {name, hex, image} list (same shape
            # as the Lectric scraper); keep other options (Size, Frame) as-is.
            options: dict = {}
            color_values, color_idx = [], None
            for i, o in enumerate(p.get("options", [])):
                if not o.get("name"):
                    continue
                if o["name"].lower() == "color":
                    color_values = o.get("values", [])
                    color_idx = i + 1  # variant option fields are 1-based
                else:
                    options[o["name"]] = o.get("values", [])
            options["colors"] = build_colors(color_values, color_idx, variants,
                                             fallback_image)

            models.append({
                "title": p.get("title"),
                "handle": p.get("handle"),
                "url": f"{BASE}/products/{p.get('handle')}",
                "product_type": p.get("product_type"),
                "vendor": p.get("vendor"),
                "tags": p.get("tags", []),
                "price_from": min(prices) if prices else None,
                "currency": "USD",
                "options": options,
                "available": any(v.get("available") for v in variants),
            })
        if len(products) < 250:
            break
        page += 1
    return models


async def open_spec_drawer(page) -> bool:
    """Click whichever 'specifications' trigger exists. Returns True if opened."""
    for label in SPEC_TRIGGERS:
        try:
            el = page.get_by_text(label, exact=False).first
            if await el.count() and await el.is_visible():
                await el.scroll_into_view_if_needed(timeout=3000)
                await el.click(timeout=3000)
                # Wait until rows actually appear.
                await page.wait_for_selector(".property-line", timeout=8000)
                return True
        except PWTimeout:
            continue
        except Exception:
            continue
    # Maybe the table is already inline.
    try:
        if await page.locator(".property-line").count():
            return True
    except Exception:
        pass
    return False


async def extract_specs(page) -> list[tuple[str, str]]:
    """Read every spec row as (label, value) in document order."""
    return await page.evaluate(
        """() => {
            const rows = [...document.querySelectorAll('.property-line')];
            const out = [];
            for (const row of rows) {
                const valEl = row.querySelector('.tech-spec-value');
                if (!valEl) continue;
                const value = (valEl.innerText || '').trim();
                // Label = the row text with the value text stripped off the end.
                let label = (row.innerText || '').trim();
                if (label.endsWith(value)) {
                    label = label.slice(0, label.length - value.length).trim();
                }
                if (label) out.push([label, value]);
            }
            return out;
        }"""
    )


async def extract_swatch_hex(page) -> dict:
    """Map color name -> {hex, swatch_image}, read from each color swatch.

    Each swatch button carries the color name in `data-sl` (e.g.
    "color_swatch_Matte Black") and a round chip whose background is either a
    solid colour (-> hex) or an image (-> swatch_image URL).
    """
    return await page.evaluate(
        r"""() => {
            const rgb2hex = s => {
                const m = s && s.match(/\d+(\.\d+)?/g);
                if (!m || m.length < 3) return null;
                return '#' + m.slice(0, 3)
                    .map(x => Math.round(+x).toString(16).padStart(2, '0')).join('');
            };
            const urlOf = bi => {
                const m = bi && bi.match(/url\("?(.*?)"?\)/);
                return m ? m[1] : null;
            };
            const out = {};
            const btns = document.querySelectorAll(
                '.color-swatches button[data-sl], .color-swatches .options__item button');
            for (const btn of btns) {
                const sl = btn.getAttribute('data-sl') || '';
                const name = sl.replace(/^color_swatch_/, '').trim();
                if (!name) continue;
                const chip = btn.querySelector('[class*=rounded-full]') || btn;
                const cs = getComputedStyle(chip);
                const entry = {hex: rgb2hex(cs.backgroundColor), swatch_image: urlOf(cs.backgroundImage)};
                if (entry.hex || entry.swatch_image) out[name] = entry;
            }
            return out;
        }"""
    )


async def scrape_model(context, model: dict, retries: int = 2) -> dict:
    result = dict(model)
    for attempt in range(1, retries + 1):
        page = await context.new_page()
        try:
            await page.goto(model["url"], wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1200)
            opened = await open_spec_drawer(page)
            if not opened:
                raise RuntimeError("spec drawer not found")
            pairs = await extract_specs(page)
            if not pairs:
                raise RuntimeError("no spec rows extracted")

            # Real per-color swatch from the on-page swatches: solid colour ->
            # hex (curated map is fallback), or a background-image -> swatch_image.
            swatch = await extract_swatch_hex(page)
            for c in result.get("options", {}).get("colors", []):
                entry = swatch.get(c["name"])
                if entry:
                    if entry.get("hex"):
                        c["hex"] = entry["hex"]
                    if entry.get("swatch_image"):
                        c["swatch_image"] = entry["swatch_image"]
                # swatch_image is a fallback only: drop it when a hex is known.
                if c.get("hex"):
                    c["swatch_image"] = None

            physical, technical, all_specs = {}, {}, {}
            for label, value in pairs:
                key = " ".join(label.split())  # normalise whitespace
                all_specs[key] = value
                (physical if classify(key) == "physical" else technical)[key] = value

            result["specs"] = {
                "physical": physical,
                "technical": technical,
                "all": all_specs,
            }
            result["spec_count"] = len(all_specs)
            result["scrape_error"] = None
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()
            return result
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                result["specs"] = {"physical": {}, "technical": {}, "all": {}}
                result["spec_count"] = 0
                result["warranty"] = None
                result["scrape_error"] = f"{type(e).__name__}: {e}"
                return result
            await asyncio.sleep(1.5 * attempt)
    return result


async def run(args) -> int:
    print(f"[*] Discovering models from {BASE}/collections/{COLLECTION} ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    print(f"[*] Found {len(models)} e-bike model(s).", file=sys.stderr)

    results: list[dict] = []
    sem = asyncio.Semaphore(args.concurrency)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not args.headed, args=["--no-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )

        async def worker(m):
            async with sem:
                r = await scrape_model(context, m)
                status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
                print(f"    - {m['title']:<38} {r['spec_count']:>3} specs  [{status}]",
                      file=sys.stderr)
                results.append(r)

        await asyncio.gather(*(worker(m) for m in models))
        await context.close()
        await browser.close()

    results.sort(key=lambda r: r["title"] or "")
    out = {
        "source": BASE, "logo": LOGO,
        "collection": COLLECTION,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(results),
        "models": results,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).",
          file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Aventon e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/aventon_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N models.")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--headed", action="store_true", help="Run with a visible browser.")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
