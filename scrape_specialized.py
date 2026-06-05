#!/usr/bin/env python3
"""
Specialized e-bike spec scraper.

Specialized runs a Next.js / Salesforce Commerce Cloud site. The current e-bike
lineup is discovered from the e-bikes category page (/shop/ebikes); each product
page is then rendered with Playwright to extract:

  * physical + technical specifications (the `SpecContainer` sections:
    E-Bike, Frameset, Brakes, Drivetrain, Wheels & Tires, Cockpit, ...),
  * colors as {name, hex, image} -- the hex is read from each color swatch's
    inline background-color, and the image is that color's hero photo (captured
    by clicking the swatch),
  * available options (frame sizes) and the price.

Output JSON mirrors the Aventon/Lectric/Ride1Up scrapers.

Usage:
    python scrape_specialized.py                  # all models -> specialized_ebikes.json
    python scrape_specialized.py --limit 3        # quick test (first 3 models)
    python scrape_specialized.py -o out.json      # custom output path
    python scrape_specialized.py --concurrency 2  # parallel product pages
    python scrape_specialized.py --headed         # watch the browser
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
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

BASE = "https://www.specialized.com"
LOGO = "assets/logos/specialized.svg"   # self-hosted wordmark (Specialized renders its logo as inline SVG; no clean CDN asset)
PLP_URL = f"{BASE}/us/en/shop/ebikes"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Spec-section categories that are electronic/technical; everything else (frame,
# brakes, drivetrain, wheels, cockpit, accessories, weight) is physical.
TECH_CATEGORIES = {"e-bike", "ebike", "electronics", "motor", "battery", "electric"}
TECHNICAL_KEYWORDS = ("motor", "battery", "charger", "display", "remote", "ui",
                      "range", "controller", "sensor", "watt", "voltage", "torque")


def classify(category: str, label: str) -> str:
    if category.strip().lower() in TECH_CATEGORIES:
        return "technical"
    low = label.lower()
    if any(kw in low for kw in TECHNICAL_KEYWORDS):
        return "technical"
    return "physical"


def titlecase(s: str) -> str:
    return " ".join(w.capitalize() if w.isupper() or w.islower() else w
                    for w in s.split(" "))


# ------------------------------ overlay handling -----------------------------

DISMISS_JS = r"""() => {
    for (const s of ['#onetrust-consent-sdk','[id*=onetrust]','[class*=CookieBanner]',
                     '[class*=Modal]','[class*=modal]','[class*=Overlay]','[class*=overlay]',
                     '[class*=Popup]','[class*=popup]','[class*=RegionSelector]']) {
        document.querySelectorAll(s).forEach(e => { try { e.remove(); } catch (_) {} });
    }
}"""


async def dismiss(page):
    for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept All')",
                "button:has-text('Accept')"]:
        try:
            el = page.locator(sel).first
            if await el.count() and await el.is_visible():
                await el.click(timeout=2000)
                await page.wait_for_timeout(300)
        except Exception:
            pass
    try:
        await page.evaluate(DISMISS_JS)
    except Exception:
        pass


# ------------------------------ catalog discovery ----------------------------

async def discover_models(context) -> list[dict]:
    """Render the e-bikes PLP, scroll to load all cards, return distinct models."""
    page = await context.new_page()
    await page.goto(PLP_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    await dismiss(page)
    prev = -1
    for _ in range(30):
        n = await page.evaluate(
            "() => document.querySelectorAll('a[href*=\"/p/\"]').length")
        if n == prev:
            break
        prev = n
        await page.mouse.wheel(0, 4000)
        await page.wait_for_timeout(600)
    links = await page.evaluate(r"""() => {
        const norm = s => (s||'').replace(/\s+/g,' ').trim();
        const out = [];
        for (const a of document.querySelectorAll('a[href*="/p/"]')) {
            const m = a.getAttribute('href').match(/\/us\/en\/([a-z0-9-]+)\/p\/(\d+)/);
            if (!m) continue;
            out.push({slug: m[1], url: location.origin + a.getAttribute('href').split('?')[0],
                      name: norm(a.innerText).split('\n')[0]});
        }
        return out;
    }""")
    await page.close()
    seen, models = set(), []
    for l in links:
        if l["slug"] in seen:
            continue
        seen.add(l["slug"])
        models.append(l)
    return models


# ------------------------------ page extraction ------------------------------

JS_SPECS = r"""() => {
    const norm = s => (s||'').replace(/\s+/g,' ').trim();
    const out = [];
    for (const cont of document.querySelectorAll('[class*=SpecContainer_container]')) {
        const cat = norm(cont.querySelector('[class*=specNameContainer]')?.innerText);
        for (const comp of cont.querySelectorAll('[class*=componentContainer]')) {
            const ps = [...comp.querySelectorAll('p')].map(p => norm(p.innerText)).filter(Boolean);
            if (ps.length >= 2) out.push([cat, ps[0], ps.slice(1).join(' ')]);
        }
    }
    return out;
}"""

JS_SWATCHES = r"""() => {
    const rgb2hex = s => {
        const m = s && s.match(/\d+(\.\d+)?/g);
        return (m && m.length >= 3)
            ? '#' + m.slice(0,3).map(x => Math.round(+x).toString(16).padStart(2,'0')).join('')
            : null;
    };
    const urlOf = bi => { const m = bi && bi.match(/url\("?(.*?)"?\)/); return m ? m[1] : null; };
    const out = [];
    for (const btn of document.querySelectorAll('button[class*=ColorSwatch_container]')) {
        const name = btn.getAttribute('aria-label') || btn.getAttribute('title') || '';
        const chip = btn.querySelector('[class*=swatchColor]') || btn.querySelector('[class*=swatch]');
        const cs = chip ? getComputedStyle(chip) : null;
        out.push({name: name.trim(),
                  hex: cs ? rgb2hex(cs.backgroundColor) : null,
                  swatch_image: cs ? urlOf(cs.backgroundImage) : null});
    }
    return out;
}"""

JS_HERO = r"""() => {
    const im = document.querySelector('[class*=Gallery] img, [class*=gallery] img, picture img, main img');
    return im ? (im.currentSrc || im.getAttribute('src') || '').split('?')[0] : null;
}"""

# Geometry table: header row = sizes, each row = a dimension + per-size values.
JS_GEOMETRY = r"""() => {
    const norm = s => (s||'').replace(/\s+/g,' ').trim();
    const out = {};
    for (const t of document.querySelectorAll('table[class*=Table_table]')) {
        const rows = [...t.querySelectorAll('tr')];
        if (rows.length < 2) continue;
        const sizes = [...rows[0].children].map(c => norm(c.innerText));
        for (const r of rows.slice(1)) {
            const cells = [...r.children].map(c => norm(c.innerText));
            const dim = cells[0];
            if (!dim) continue;
            const vals = cells.slice(1)
                .map((v, i) => (sizes[i + 1] ? `${sizes[i + 1]}: ${v}` : v))
                .filter(Boolean);
            if (vals.length) out[dim] = vals.join(" | ");
        }
    }
    return out;
}"""

JS_SIZES = r"""() => {
    const norm = s => (s||'').replace(/\s+/g,' ').trim();
    // Frame sizes are the geometry table's column headers.
    for (const t of document.querySelectorAll('table[class*=Table_table]')) {
        const head = t.querySelector('tr');
        if (!head) continue;
        const cells = [...head.children].map(c => norm(c.innerText)).filter(Boolean);
        if (cells.length && cells.every(c => c.length <= 4)) return cells;
    }
    return [];
}"""

JS_PRICE = r"""() => {
    // The JSON-LD Product schema carries the authoritative price(s).
    const prices = [];
    let currency = 'USD';
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
        let d; try { d = JSON.parse(s.textContent); } catch (e) { continue; }
        for (const obj of (Array.isArray(d) ? d : [d])) {
            if (obj['@type'] !== 'Product') continue;
            let offers = obj.offers;
            if (!Array.isArray(offers)) offers = offers ? [offers] : [];
            for (const o of offers) {
                if (o && o.price != null) {
                    prices.push({price: parseFloat(o.price),
                                 name: o.name || o.sku || null,
                                 sku: o.sku || null});
                    if (o.priceCurrency) currency = o.priceCurrency;
                }
            }
        }
    }
    return {prices, currency};
}"""


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
            await dismiss(page)
            for _ in range(12):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(250)
            await page.wait_for_selector("[class*=SpecContainer_container]",
                                         state="attached", timeout=15000)

            name = (await page.evaluate("() => document.querySelector('h1')?.innerText?.trim() || ''")) \
                or model.get("name") or model["slug"]
            rows = await page.evaluate(JS_SPECS)
            if not rows:
                raise RuntimeError("no specs extracted")
            swatches = await page.evaluate(JS_SWATCHES)
            sizes = await page.evaluate(JS_SIZES)
            geometry = await page.evaluate(JS_GEOMETRY)
            pr = await page.evaluate(JS_PRICE)

            # Per-color hero image: click each swatch, capture the hero.
            colors = []
            btns = page.locator("button[class*=ColorSwatch_container]")
            nbtn = await btns.count()
            for i, sw in enumerate(swatches):
                img = None
                if i < nbtn:
                    try:
                        await btns.nth(i).scroll_into_view_if_needed(timeout=2000)
                        await btns.nth(i).click(timeout=3000)
                        await page.wait_for_timeout(900)
                        img = await page.evaluate(JS_HERO)
                    except Exception:
                        img = None
                # swatch_image is a fallback only: drop it when a hex is known.
                colors.append({"name": titlecase(sw["name"]), "hex": sw["hex"],
                               "swatch_image": None if sw["hex"] else sw.get("swatch_image"),
                               "image": img})
            if not colors:  # single-color product: use the hero as one entry
                hero = await page.evaluate(JS_HERO)
                if hero:
                    colors.append({"name": name, "hex": None, "swatch_image": None, "image": hero})
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()

            physical, technical, all_specs = {}, {}, {}
            for cat, label, value in rows:
                key = " ".join(label.split())
                all_specs[key] = value
                (technical if classify(cat, key) == "technical" else physical)[key] = value

            offers = pr.get("prices") or []
            pvals = [o["price"] for o in offers]
            result["model"] = name
            result["price_range"] = {
                "min": min(pvals) if pvals else None,
                "max": max(pvals) if pvals else None,
                "currency": pr.get("currency", "USD"),
            }
            # Every configuration (offer) with its own price, not just the range.
            result["configurations"] = [
                {"name": o.get("name"), "sku": o.get("sku"), "price": o["price"]}
                for o in offers
            ]
            result["options"] = {"sizes": sizes, "colors": colors}
            result["geometry"] = geometry
            result["specs"] = {"physical": physical, "technical": technical, "all": all_specs}
            result["spec_count"] = len(all_specs)
            result["scrape_error"] = None
            return result
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                result["model"] = model.get("name") or model["slug"]
                result["price_range"] = {"min": None, "max": None, "currency": "USD"}
                result["configurations"] = []
                result["options"] = {"sizes": [], "colors": []}
                result["specs"] = {"physical": {}, "technical": {}, "all": {}}
                result["spec_count"] = 0
                result["warranty"] = None
                result["scrape_error"] = f"{type(e).__name__}: {e}"
                return result
            await asyncio.sleep(2.0 * attempt)
    return result


# ----------------------------------- main ------------------------------------

async def run(args) -> int:
    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed, args=["--no-sandbox"])
        context = await browser.new_context(viewport={"width": 1366, "height": 1000},
                                            user_agent=UA)

        print(f"[*] Discovering models from {PLP_URL} ...", file=sys.stderr)
        models = await discover_models(context)
        if args.limit:
            models = models[: args.limit]
        print(f"[*] Found {len(models)} e-bike model(s).", file=sys.stderr)

        async def worker(m):
            async with sem:
                r = await scrape_model(context, m)
            status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
            print(f"    - {r.get('model', m['slug'])[:34]:<34} {r['spec_count']:>3} specs  "
                  f"{len(r['options']['colors'])} colors  [{status}]", file=sys.stderr)
            results.append(r)

        await asyncio.gather(*(worker(m) for m in models))
        await context.close()
        await browser.close()

    results.sort(key=lambda r: r.get("model") or r["slug"])
    out = {
        "source": BASE, "logo": LOGO,
        "category": "ebikes",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(results),
        "models": results,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Specialized e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/specialized_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N models.")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
