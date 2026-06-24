#!/usr/bin/env python3
"""
Trek e-bike spec scraper (SAP Hybris OCC API — HTTP only, no browser).

Discovery: the e-bike category page server-renders each product as a Vue
`:product="{...}"` prop (HTML-entity-encoded JSON) carrying the base product
code / name / url / price.

Specs come from Trek's public anonymous OCC API:
  - /occ/v2/us/products/{code}?fields=FULL  -> variantOptions (the spec endpoint is
    keyed by the default VARIANT sku, not the base code), colours and price;
  - /occ/v2/us/products/{variant}/specs     -> the full BOM as flat
    partName -> description items (Frame, Fork, Motor, Battery, Weight, …).

Output mirrors the other scrapers.

Usage:
    python scrape_trek.py [-o out.json] [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scraper_common import clean_title  # noqa: E402  (import sets LD_LIBRARY_PATH for bundled chromium)
from playwright.async_api import async_playwright  # noqa: E402
from bike_taxonomy import classify_product_types

BASE = "https://www.trekbikes.com"
OCC = "https://api.trekbikes.com/occ/v2/us"
CATEGORY = "B507"   # Trek's e-bike category code
COLLECTION = "electric-bikes"
SEARCH = (f"{OCC}/products/search?query=:relevance:allCategories:{CATEGORY}"
          "&pageSize=300&fields=FULL&lang=en_US&curr=USD")
LOGO = "https://www.trekbikes.com/globalassets/non-product-assets/logos/trek-logo-black.svg"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_PROP = re.compile(r':product="([^"]*)"')


def _get(url: str, as_json: bool = False):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json" if as_json else "text/html",
    })
    with urllib.request.urlopen(req, timeout=45) as r:
        data = r.read().decode("utf-8", "replace")
    return json.loads(data) if as_json else data


def discover() -> list[dict]:
    """Every e-bike from the OCC category search (the on-page grid is paginated and
    only renders the first ~23 — the search API returns the full lineup with the
    primary image and price)."""
    d = _get(SEARCH, as_json=True)
    # Trek sometimes lists the same model (same url slug = handle) under two codes
    # (current + a prior model-year). Keep the NEWER one (higher code) so the handle
    # — and the normalized id — stays unique (a collision crashes the search index).
    by_handle = {}
    for p in d.get("products") or []:
        code, name, url = p.get("code"), p.get("name"), p.get("url")
        if not (code and name and url):
            continue
        handle = url.split("/p/")[0].rstrip("/").split("/")[-1] if "/p/" in url else code
        prev = by_handle.get(handle)
        if prev and str(prev["code"]).isdigit() and str(code).isdigit() and int(prev["code"]) >= int(code):
            continue
        imgs = p.get("images") or []
        prim = next((i.get("url") for i in imgs if i.get("imageType") == "PRIMARY"),
                    imgs[0].get("url") if imgs else None)
        if prim and prim.startswith("//"):
            prim = "https:" + prim
        by_handle[handle] = {
            "code": code, "name": name, "url": BASE + url, "handle": handle,
            "price": (p.get("price") or {}).get("value"),
            "image": prim,
            # category for classification comes from the url path
            # (…/mountain-bikes/electric-mountain-bikes/… , …/electric-hybrid-bikes/…)
            "cats": re.sub(r"[-/]+", " ", url.split("/p/")[0]),
        }
    return list(by_handle.values())


def variant_and_colors(code: str):
    """(default_variant_sku, colors, price, variant_urls) from the FULL product. The
    specs API is keyed by the variant sku; variant_urls (one per colour/size) let the
    availability check fall back to other colours when the default is sold out. NB the
    product-level `stock`/`purchasable` is uselessly `outOfStock` for every Trek bike
    (dealer model) — availability is read from the rendered Add-to-cart button instead."""
    try:
        d = _get(f"{OCC}/products/{code}?fields=FULL&lang=en_US&curr=USD", as_json=True)
    except Exception:
        return None, [], None, []
    vo = d.get("variantOptions") or []
    variant = vo[0].get("code") if vo else None
    colors, seen = [], set()
    for v in vo:
        name = None
        for q in (v.get("variantOptionQualifiers") or []):
            if (q.get("qualifier") or "").lower() in ("style", "color", "colour", "colorgroup"):
                name = q.get("value")
                break
        if name and name not in seen:
            seen.add(name)
            colors.append({"name": name, "hex": None, "swatch_image": None, "image": None})
    urls = [BASE + v["url"] for v in vo if v.get("url")]
    return variant, colors, (d.get("price") or {}).get("value"), urls


# /sizing geometryData column -> (geometry field, unit). Trek lengths are cm,
# angles already carry °. Skipped columns (size number, wheel, offset, trail) aren't
# useful geometry rows here.
_GEO_COLS = {
    "geometrySeattube": ("seat_tube_length", "cm"),
    "geometryAngleSeattube": ("seat_tube_angle", ""),
    "geometryLengthHeadtube": ("head_tube_length", "cm"),
    "geometryAngleHead": ("head_tube_angle", ""),
    "geometryEffToptube": ("effective_top_tube", "cm"),
    "geometryBBHeight": ("bottom_bracket_height", "cm"),
    "geometryLengthChainstay": ("chainstay_length", "cm"),
    "geometryWheelbase": ("wheelbase", "cm"),
    "geometryStandover": ("standover_height", "cm"),
    "geometryFrameReach": ("reach", "cm"),
    "geometryFrameStack": ("stack", "cm"),
}


def _rider_heights(d: dict) -> dict:
    """{size_letter: (min, max)} rider-height range from the size chart
    (productSizeChart.sizeChartGroups[].sizeChartGroups[] where group == 'Rider Height')."""
    out = {}
    for grp in ((d.get("productSizeChart") or {}).get("sizeChartGroups") or []):
        # Road/gravel charts label sizes "XS (47cm)" while the geometry table (which
        # drives frame_sizes) uses the bare letter "XS"; strip the (NNcm) suffix so the
        # rider-height range matches the frame-size letter (MTB/hybrid use "S" verbatim).
        sz = (grp.get("size") or "").split(" (")[0].strip()
        for sub in grp.get("sizeChartGroups") or []:
            if (sub.get("sizeChartGroupName") or "").lower().startswith("rider"):
                out[sz] = (sub.get("formattedSizeChartMin"), sub.get("formattedSizeChartMax"))
    return out


def fetch_sizing(code: str):
    """(frame_sizes, geometry) from /sizing. frame_sizes carry the size letters with
    their RIDER-HEIGHT range from the size chart (productSizeChart); geometry maps each
    dimension to a {size: value} dict so the per-size geometry table renders."""
    try:
        d = _get(f"{OCC}/products/{code}/sizing?lang=en_US&curr=USD", as_json=True)
    except Exception:
        return None, None
    rh = _rider_heights(d)
    headers = d.get("geometryDataHeaders") or []
    rows = [r.get("geometry") or [] for r in (d.get("geometryData") or [])]
    idx = {h: i for i, h in enumerate(headers)}
    li = idx.get("geometryFrameSizeLetter")
    sizes = [r[li].strip() for r in rows if li is not None and li < len(r) and r[li].strip()]
    if not sizes:                       # no geometry table — fall back to chart sizes
        sizes = list(rh.keys())
    if not sizes:
        return None, None
    geometry = {}
    for col, (field, unit) in _GEO_COLS.items():
        ci = idx.get(col)
        if ci is None:
            continue
        per = {}
        for r, sz in zip(rows, sizes):
            if ci < len(r) and str(r[ci]).strip():
                v = str(r[ci]).strip()
                if unit and re.fullmatch(r"[\d.]+", v):
                    v = f"{v} {unit}"
                per[sz] = v
        if per:
            geometry[field] = per
    # Match each frame size to its rider-height range. One-size bikes label the geometry
    # size "One size" but the chart "One size fits most" (or "M") -- when there's a single
    # size and a single chart range, attach it regardless of the label mismatch.
    def _h(sz):
        if sz in rh:
            return rh[sz]
        if len(rh) == 1 and len(sizes) == 1:
            return next(iter(rh.values()))
        return (None, None)
    frame_sizes = [{"size": sz, "height_min": _h(sz)[0], "height_max": _h(sz)[1]}
                   for sz in sizes]
    return frame_sizes, geometry


def fetch_specs(variant: str) -> dict:
    """Flat partName -> description spec map from the OCC specs endpoint."""
    try:
        d = _get(f"{OCC}/products/{variant}/specs?lang=en_US&curr=USD", as_json=True)
    except Exception:
        return {}
    out = {}
    for it in d.get("specItems") or []:
        label = (it.get("partName") or it.get("partId") or "").strip()
        value = (it.get("description") or "").strip()
        if label and value:
            out.setdefault(" ".join(label.split()), value)
    return out


# The rendered "quick-spec" strip next to the buying zone carries the headline specs
# that the OCC API never exposes: E-bike Classification, Range, Weight (+ Torque/Motor/
# Battery as a cross-check). `.spec-name` is the label, its next sibling the value.
JS_QUICKSPEC = r"""() => {
    const out = [], seen = new Set();
    for (const el of document.querySelectorAll('.spec-name')) {
        const lab = (el.textContent || '').replace(/\s+/g, ' ').trim();
        const sib = el.nextElementSibling;
        const val = sib ? (sib.textContent || '').replace(/\s+/g, ' ').trim() : '';
        if (lab && val && !seen.has(lab)) { seen.add(lab); out.push([lab, val]); }
    }
    return out;
}"""


# Availability: out of stock, Trek's "Add to cart" button is present but DISABLED
# (greyed out), so require it ENABLED + visible. A model is sold out only when NO
# colour has an enabled Add-to-cart.
JS_ATC = r"""() => [...document.querySelectorAll('button, a')].some(e => {
    if ((e.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase() !== 'add to cart') return false;
    if (e.disabled || e.getAttribute('aria-disabled') === 'true') return false;
    const s = getComputedStyle(e);
    return s.display !== 'none' && s.visibility !== 'hidden';
})"""


async def _dismiss_consent(page):
    for sel in ("#onetrust-accept-btn-handler", "button:has-text('Allow all')",
                "button:has-text('Accept All')"):
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_timeout(400)
                return
        except Exception:
            pass


async def _any_color_available(context, urls) -> bool:
    """True if any colour variant still shows Add to cart (checked only when the
    default colour is out — most bikes never reach this)."""
    for u in urls[:8]:
        page = await context.new_page()
        try:
            await page.goto(u, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            if await page.evaluate(JS_ATC):
                await page.close()
                return True
        except Exception:
            pass
        await page.close()
    return False


async def add_quickspecs(context, model: dict, retries: int = 2) -> None:
    """Render the PDP: merge the quick-spec strip (class/range/weight/…) and set
    `_available` from the Add-to-cart button (falling back across colours)."""
    for attempt in range(1, retries + 1):
        page = await context.new_page()
        try:
            await page.goto(model["url"], wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)
            await _dismiss_consent(page)
            pairs = []
            for _ in range(10):
                for _ in range(3):
                    await page.mouse.wheel(0, 2500)
                    await page.wait_for_timeout(350)
                pairs = await page.evaluate(JS_QUICKSPEC)
                if pairs:
                    break
                await page.wait_for_timeout(800)
            atc = await page.evaluate(JS_ATC)
            await page.close()
            if pairs:
                for lab, val in pairs:
                    model["specs"]["all"].setdefault(" ".join(lab.split()), val)
                model["spec_count"] = len(model["specs"]["all"])
            # available on the default colour, else check the other colours
            model["_available"] = True if atc else await _any_color_available(
                context, model.get("_variant_urls") or [])
            return
        except Exception:
            await page.close()
            if attempt == retries:
                return
            await asyncio.sleep(1.5 * attempt)


async def run(args) -> int:
    print(f"[*] Discovering e-bike models (category {CATEGORY}) ...", file=sys.stderr)
    products = discover()
    if args.limit:
        products = products[: args.limit]
    print(f"[*] Found {len(products)} e-bike model(s).", file=sys.stderr)

    results = []
    for p in products:
        variant, colors, price, variant_urls = variant_and_colors(p["code"])
        specs = fetch_specs(variant) if variant else {}
        frame_sizes, geometry = fetch_sizing(p["code"])
        if not colors and p.get("image"):
            colors = [{"name": "Standard", "hex": None, "swatch_image": None, "image": p["image"]}]
        price = price if price is not None else p["price"]
        cfg_opts = {"color": colors[0]["name"]} if colors else {}
        results.append({
            "model": clean_title(p["name"]),
            "handle": p["handle"],   # deduped slug (unique) from discover()
            "url": p["url"],
            "currency": "USD",
            "_cats": p["cats"],            # category text for classification (dropped below)
            "_variant_urls": variant_urls, # per-colour urls for the availability fallback
            "price_from": price,
            "options": {"colors": colors},
            # availability set after the Playwright pass (Add-to-cart across colours)
            "configurations": [{"options": cfg_opts, "price": price, "available": None}],
            "specs": {"all": specs},
            "spec_count": len(specs),
            "scrape_error": None if specs else "no specs",
            **({"frame_sizes": frame_sizes} if frame_sizes else {}),
            **({"geometry": geometry} if geometry else {}),
        })

    # Playwright phase: merge the rendered quick-spec strip (class/range/weight) per PDP.
    print("[*] Fetching quick-spec strips (class/range/weight) ...", file=sys.stderr)
    sem = asyncio.Semaphore(args.concurrency)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not args.headed, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1366, "height": 1000}, user_agent=UA)

        async def worker(m):
            async with sem:
                await add_quickspecs(ctx, m)
            print(f"    - {m['model'][:32]:<32} {m['spec_count']:>3} specs", file=sys.stderr)

        await asyncio.gather(*(worker(m) for m in results))
        await ctx.close()
        await browser.close()

    # fold the rendered availability into the config + drop the temp variant urls
    for m in results:
        m["configurations"][0]["available"] = m.pop("_available", None)
        m.pop("_variant_urls", None)

    # classify after quick specs are in (so class/range/etc. inform it). The URL
    # category path (_cats) is Trek's authoritative bucket (electric-mountain-bikes
    # vs electric-hybrid-bikes) -- keep it verbatim. The BOM is supporting signal but
    # carries traps: scrub "folding"(bead) tire wording (else everything reads Folding)
    # and the mountain/MTB use-words baked into component MODEL NAMES (derailleur hanger
    # "Trek FX/MTB Two-Bolt", hub "Shimano HG MTB", wheel "OCLV Mountain Carbon") that
    # falsely promote rigid hybrids/cargo/comfort bikes (Verve+, Fetch+, Vale Go!) to
    # eMTB. Real eMTBs keep their eMTB label via the URL path, not the parts list.
    for m in results:
        cats = m.pop("_cats", "")
        specs_txt = " ".join(m["specs"]["all"].values())
        specs_txt = re.sub(r"\bmtb\b|\bemtb\b|mountain|enduro|downhill|hard[\s-]?tail",
                           " ", specs_txt, flags=re.I)
        extra = re.sub(r"fold\w*", " ", f"{cats} {specs_txt}", flags=re.I)
        m["product_types"] = classify_product_types(m["model"], "", extra)
        # Trek files its Fetch+ cargo line under the hybrid URL bucket; the genuine
        # cargo signal is the Bosch Cargo Line motor ("Performance Line Cargo"), not
        # the word "cargo" anywhere in the BOM -- a plain "Cargo rack" accessory rides
        # on comfort bikes (Townie Go!) too. normalize re-classifies from name/url/
        # tags/tires only and can't see the motor row, so surface the motor-grounded
        # cargo finding via vehicle_type to keep Cargo (and a longtail off eMTB).
        if re.search(r"cargo", m["specs"]["all"].get("Motor", ""), re.I):
            m["vehicle_type"] = "cargo bike"

    results.sort(key=lambda r: r["model"] or "")
    out = {"source": BASE, "logo": LOGO, "collection": COLLECTION,
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Trek e-bike specifications (OCC API + quick-spec strip).")
    ap.add_argument("-o", "--output", default="data/current/trek_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=1)  # Trek PDPs miss the strip under parallel render
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
