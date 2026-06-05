#!/usr/bin/env python3
"""
Tern Bicycles e-bike spec scraper.

Unlike the Shopify brands, Tern runs a Drupal site (no products.json), and its
catalog mixes electric and non-electric folding bikes. This scraper discovers
every bike from the `/us/bikes/all` listing, then uses Playwright to open each
product page and read its server-rendered `#tech_specs` grid (label/value rows),
price, and color swatches. Only **electric** models (those with a Motor/Battery
spec) that actually carry specs are kept; family landing pages and acoustic
folders are dropped.

Specs are split into `physical` / `technical` groups (plus a flat `all` map), and
colors are `[{name, hex, swatch_image, image}]` — `hex` read straight from each
on-page swatch's `background-color` (hex preferred), `image` the model photo.

Usage:
    python scrape_tern.py                  # all e-bikes -> tern_ebikes.json
    python scrape_tern.py -o out.json      # custom output file
    python scrape_tern.py --limit 3        # only first 3 models (quick test)
    python scrape_tern.py --headed         # show the browser
    python scrape_tern.py --concurrency 4  # parallel product pages (default 4)
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
# (This env must be set before Playwright launches the browser subprocess.)
_DEPS = Path(__file__).parent / ".chromium-deps" / "root"
if _DEPS.exists():
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join([
        str(_DEPS / "usr/lib/x86_64-linux-gnu"),
        str(_DEPS / "lib/x86_64-linux-gnu"),
        os.environ.get("LD_LIBRARY_PATH", ""),
    ]).strip(os.pathsep)

from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

BASE = "https://www.ternbicycles.com"
LOGO = "https://www.ternbicycles.com/sites/default/files/2025-06/Tern-Bicycles-cargo-ebikes-logo.png"
LISTING = "/us/bikes/all"
COLLECTION = "ebikes"

# Label keywords used to classify each spec into a physical vs technical bucket
# (shared approach with scrape_aventon.py / scrape_lectric.py). PHYSICAL is
# checked first; anything unmatched falls to TECHNICAL, then defaults to physical.
TECHNICAL_KEYWORDS = (
    "motor", "battery", "range", "charger", "charging", "controller", "throttle",
    "display", "remote", "sensor", "pedal assist", "assist", "class", "watt",
    "voltage", "wireless", "connectivity", "gps", "app", "certification",
    "torque", "power", "drive unit",
)
PHYSICAL_KEYWORDS = (
    "weight", "payload", "capacity", "limit", "rider", "height", "standover",
    "frame", "fork", "wheel", "tire", "tyre", "brake", "rotor", "derailleur",
    "shifter", "speeds", "chain", "cassette", "gear", "crank", "bottom bracket",
    "pedal", "saddle", "seat", "handlebar", "grip", "headset", "kickstand",
    "rack", "fender", "light", "stem", "spoke", "hub", "dimension", "length",
    "width", "fold", "size", "color", "generation", "gross vehicle",
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

def discover_models() -> list[dict]:
    """Every bike linked from the /us/bikes/all listing (electric filtered later)."""
    req = urllib.request.Request(BASE + LISTING, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", "ignore")
    seen, models = set(), []
    for path in re.findall(r'/us/bikes/\d+/[a-z0-9-]+', html):
        if path in seen:
            continue
        seen.add(path)
        models.append({"handle": path.rsplit("/", 1)[-1], "url": BASE + path})
    return models


# ------------------------------ page extraction ------------------------------

# The Tern product page is server-rendered. Each spec is a row whose label div
# carries `text-header` and whose value is the next sibling (`text-gray-700 …
# col-span-2`). Colors live in `.field-color` swatches with the name on a [title]
# wrapper and the hex in the swatch's inline background-color.
JS_PAGE = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const rgb2hex = s => {
        const m = s && s.match(/\d+(\.\d+)?/g);
        if (!m || m.length < 3) return null;
        return '#' + m.slice(0, 3)
            .map(x => Math.round(+x).toString(16).padStart(2, '0')).join('');
    };
    const q = s => document.querySelector(s);
    const meta = p => (q(`meta[property="${p}"]`) || {}).content || null;

    // --- specs: label (.text-header) -> next sibling value cell ---
    const specs = [];
    for (const lab of document.querySelectorAll('div.text-header')) {
        const val = lab.nextElementSibling;
        if (!val) continue;
        const cls = val.className || '';
        if (cls.indexOf('text-gray-700') === -1 && cls.indexOf('col-span-2') === -1) continue;
        const name = norm(lab.innerText).replace(/:$/, '');
        const value = norm(val.innerText);
        if (name && value) specs.push([name, value]);
    }

    // --- colors: name from [title], hex from the swatch background-color ---
    const colors = [], seen = new Set();
    for (const t of document.querySelectorAll('.field-color [title]')) {
        const name = (t.getAttribute('title') || '').trim();
        if (!name || seen.has(name)) continue;
        const sw = t.querySelector('.color_field__swatch');
        let hex = null;
        if (sw) hex = rgb2hex(getComputedStyle(sw).backgroundColor)
                   || rgb2hex(sw.getAttribute('style') || '');
        seen.add(name);
        colors.push({name, hex});
    }

    // --- meta: model name, price, photo ---
    let title = (meta('og:title') || (q('h1') || {}).innerText || '').trim();
    title = title.split('|')[0].trim();
    const priceTxt = ((q('.field-pricing') || {}).innerText) || '';
    const pm = priceTxt.match(/\$([0-9][0-9,]*)/);
    const price = pm ? parseFloat(pm[1].replace(/,/g, '')) : null;

    return {title, price, image: meta('og:image'), specs, colors};
}"""


def is_electric(all_specs: dict) -> bool:
    """A Tern model is an e-bike iff it has a Motor or Battery spec with a value."""
    for label, value in all_specs.items():
        low = label.lower()
        if ("motor" in low or "battery" in low or "drive unit" in low) and value:
            return True
    return False


async def scrape_model(context, model: dict, retries: int = 2) -> dict:
    result = dict(model)
    for attempt in range(1, retries + 1):
        page = await context.new_page()
        try:
            await page.goto(model["url"], wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector("div.text-header", timeout=8000)
            except Exception:
                pass
            await page.wait_for_timeout(500)
            data = await page.evaluate(JS_PAGE)
            warranty = await page.evaluate(JS_WARRANTY)
            await page.close()

            physical, technical, all_specs = {}, {}, {}
            for label, value in data["specs"]:
                key = " ".join(label.split())   # normalise whitespace
                if key.lower().startswith("color"):   # colors handled separately
                    continue
                all_specs[key] = value
                (physical if classify(key) == "physical" else technical)[key] = value

            colors = [{"name": c["name"], "hex": c["hex"],
                       "swatch_image": None, "image": data.get("image")}
                      for c in data["colors"]]

            result.update({
                "title": data["title"] or model["handle"],
                "url": model["url"],
                "product_type": None,
                "price_from": data["price"],
                "currency": "USD",
                "options": {"colors": colors},
                "specs": {"physical": physical, "technical": technical, "all": all_specs},
                "spec_count": len(all_specs),
                "electric": is_electric(all_specs),
                "warranty": warranty,
                "scrape_error": None,
            })
            return result
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                result.update({
                    "title": model["handle"],
                    "product_type": None, "price_from": None, "currency": "USD",
                    "options": {"colors": []},
                    "specs": {"physical": {}, "technical": {}, "all": {}},
                    "spec_count": 0, "electric": False, "warranty": None,
                    "scrape_error": f"{type(e).__name__}: {e}",
                })
                return result
            await asyncio.sleep(1.5 * attempt)
    return result


async def run(args) -> int:
    print(f"[*] Discovering bikes from {BASE}{LISTING} ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    print(f"[*] Found {len(models)} bike page(s); keeping electric ones with specs.",
          file=sys.stderr)

    scraped: list[dict] = []
    sem = asyncio.Semaphore(args.concurrency)

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
                if r["scrape_error"]:
                    tag = f"FAIL ({r['scrape_error']})"
                elif not r["electric"]:
                    tag = "skip (not electric)"
                elif not r["spec_count"]:
                    tag = "skip (no specs)"
                else:
                    tag = "ok"
                print(f"    - {r['title']:<28} {r['spec_count']:>3} specs  "
                      f"{len(r['options']['colors'])} colors  [{tag}]", file=sys.stderr)
                scraped.append(r)

        await asyncio.gather(*(worker(m) for m in models))
        await context.close()
        await browser.close()

    # Keep only electric models that actually have specs; dedup by title,
    # preferring the richest spec set.
    best: dict[str, dict] = {}
    for r in scraped:
        if not (r["electric"] and r["spec_count"]):
            continue
        key = r["title"].lower()
        if key not in best or r["spec_count"] > best[key]["spec_count"]:
            best[key] = r
    results = sorted(best.values(), key=lambda r: r["title"])
    for r in results:               # internal flag, not part of the output schema
        r.pop("electric", None)

    out = {
        "source": BASE, "logo": LOGO,
        "collection": COLLECTION,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(results),
        "models": results,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok} electric models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Tern e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/tern_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N bike pages.")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--headed", action="store_true", help="Run with a visible browser.")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
