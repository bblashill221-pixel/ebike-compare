#!/usr/bin/env python3
"""
Giant e-bike spec scraper.

Giant (giant-bicycles.com, US store) is fully server-rendered — no Playwright needed.
Discovery walks a 3-level tree, all plain HTML:

    /us/bikes/e-bikes                      landing -> subcategory grids
      -> /us/bikes/e-bikes/<sub>           e.g. electric-mountain, electric-road
        -> /us/bikes-<series>-eplus...     series page (lists the builds)
          -> /us/<series>-eplus-<build>    the build PDP (one model)

Only **E+** models (slug contains "eplus") are captured — Giant e-bikes only.

Each PDP carries:
  - a schema.org **Product** ld+json: name, image, description, brand, and an
    `offers[]` array (price + per-variant availability InStock/OutOfStock) -> the
    bike is in_stock if ANY size/colour offer is InStock;
  - a clean **`<ul class=specifications>`** BOM: `<li class=datarow><div class=label>
    Motor</div><div class=value>...</div>` rows (Motor/Battery/Sizes/Colors/Frame/
    Fork/Brakes/...), flattened to specs.all.

Classification uses the name + the subcategory ("electric mountain"/"electric road"),
surfaced via `vehicle_type` so normalize re-derives the same type (the PDP url carries
no category word). The BOM is NOT fed to the classifier (component model names carry
stray terrain words).

Usage:
    python scrape_giant.py                 # all E+ models -> giant_ebikes.json
    python scrape_giant.py --limit 2       # quick test
    python scrape_giant.py -o out.json     # custom output path
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bike_taxonomy import classify_product_types

BASE = "https://www.giant-bicycles.com"
EBIKES = f"{BASE}/us/bikes/e-bikes"
# Giant renders its wordmark as inline SVG; the brand mark asset is the closest CDN file.
LOGO = "https://static.giant-bicycles.com/Icons/Giant/v8/favicon.svg"
COLLECTION = "e-bikes"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# subcategory slug -> a category phrase fed to the classifier via vehicle_type
CAT_VEHICLE = {
    "electric-mountain": "electric mountain bike",
    "electric-road": "electric road bike",
    "electric-fitness": "electric fitness hybrid bike",
    "electric-lifestyle": "electric cruiser city bike",
    "electric-gravel": "electric gravel bike",
}

_TAG = re.compile(r"<[^>]+>")
_LD = re.compile(r"<script[^>]*ld\+json[^>]*>(.*?)</script>", re.S)
_SPEC = re.compile(
    r"<li class=datarow><div class=label>(.*?)</div><div class=value>(.*?)</div></li>", re.S)


def _get(url: str, retries: int = 3) -> str:
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            if attempt == retries:
                raise
            time.sleep(1.5 * attempt)
    return ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub(" ", s))).strip()


def _links(text: str, pattern: str) -> list[str]:
    return sorted(set(re.findall(pattern, text)))


def _range_text(h: str) -> str | None:
    """Range from the page's Range estimator block (Extreme/Good/Ideal tiers, km+miles
    toggle) -> "<min>-<max> miles". This lives at the bottom of the page, NOT in the
    spec list, so the BOM scrape misses it."""
    i = h.find("line-behind>Range")
    if i < 0:
        return None
    block = h[i:i + 2500]
    miles = [int(x) for x in re.findall(r"value-miles[^>]*>\s*([0-9]+)\s*miles", block)]
    if not miles:
        return None
    lo, hi = min(miles), max(miles)
    return f"{lo}-{hi} miles" if lo != hi else f"{hi} miles"


def _rider_heights(h: str) -> dict:
    """{size: (min, max)} rider-height range from the "Sizing Guide" size-bar in the
    Sizing Guide and Geometry section (`<ul id=sizing-guide>`): each `<li class=size>`
    has a `<dt class=name>` plus start/end height spans in cm (value-mm) and feet-inch
    (value-inch). Keep the feet-inch values, normalised to plain quotes (5'4")."""
    i = h.find("id=sizing-guide")
    if i < 0:
        return {}
    block = h[i: h.find("</ul>", i) if h.find("</ul>", i) > 0 else i + 6000]

    def _ft(s: str | None) -> str | None:
        return s.replace("’", "'").replace("”", '"').replace("′", "'").strip() if s else None

    out: dict[str, tuple] = {}
    for li in re.findall(r"<li class=size>(.*?)</li>", block, re.S):
        nm = re.search(r"<dt class=name>([^<]+)</dt>", li)
        if not nm:
            continue
        lo = re.search(r'class=start.*?value-inch[^>]*>([^<]+)<', li, re.S)
        hi = re.search(r'class=end.*?value-inch[^>]*>([^<]+)<', li, re.S)
        lo_v, hi_v = _ft(lo.group(1)) if lo else None, _ft(hi.group(1)) if hi else None
        if lo_v or hi_v:
            out[nm.group(1).strip()] = (lo_v, hi_v)
    return out


def _geometry(h: str) -> dict | None:
    """Per-size geometry from the "Sizing Guide and Geometry" table -> {field: {size:
    value}} (like the Trek scraper). Each cell carries an mm + an inch value; keep mm
    (angles/wheel-size have neither and keep their raw text). Giant publishes no per-size
    RIDER-HEIGHT range (its fit tool is a JS body-measurement calculator), so frame_sizes
    stay label-only; this is the geometry the user can read off the page."""
    i = h.find("id=geometrytable")
    if i < 0:
        return None
    block = h[i: h.find("</table>", i) if h.find("</table>", i) > 0 else i + 9000]
    sizes = re.findall(r"name=framesize>([^<]+)</th>", block)
    if not sizes:
        return None
    geo: dict[str, dict] = {}
    for row in re.findall(r"<tr class=property>(.*?)</tr>", block, re.S):
        nm = re.search(r"<td class=name>(.*?)</td>", row, re.S)
        if not nm:
            continue
        # drop the (mm)/(inch)/(degrees) unit-label spans and the leading A/A1 code
        name = _clean(re.sub(r'<span class="?unit-label.*?</span>', " ", nm.group(1), flags=re.S))
        name = re.sub(r"^[A-Z]\d?\s+", "", name).strip()
        per: dict[str, str] = {}
        for sz, cell in zip(sizes, re.findall(r"<td class=value>(.*?)</td>", row, re.S)):
            mm = re.search(r'value-mm">\s*([^<]+?)\s*<', cell)
            if mm:
                per[sz] = f"{mm.group(1)} mm"
            else:                       # angle / wheel-size cell: raw text (keeps °, ")
                txt = _clean(cell)
                if txt:
                    per[sz] = txt
        if per:
            key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            if key:
                geo[key] = per
    return geo or None


def _hub_torque(h: str) -> int | None:
    """A SyncDriveMove hub motor's spec row quotes the mid-drive-EQUIVALENT torque
    ("75Nm"); the real hub torque is lower and stated in prose ("delivers 30Nm")."""
    m = re.search(r"delivers\s+(\d+)\s*Nm", h, re.I)
    return int(m.group(1)) if m else None


def _weight_text(h: str) -> str | None:
    """Bike weight from the marketing prose ("weighs just 21.7kg (size medium)") — Giant
    publishes no weight spec row (the "Weight" row is a dealer disclaimer). Guard against
    component/system weights also phrased "weighs just X kg" (e.g. the Defy's "the system
    weighs just 2.3kg"): only accept a plausible whole-bike weight (~10-45 kg)."""
    for val in re.findall(r"weighs\s+(?:just\s+|only\s+)?(\d+(?:\.\d+)?)\s*kg", h, re.I):
        if 10.0 <= float(val) <= 45.0:
            return f"{val} kg"
    return None


def discover() -> dict[str, str]:
    """{pdp_url: subcategory} for every E+ build PDP, walked from the e-bikes landing."""
    landing = _get(EBIKES)
    subs = _links(landing, r"/us/bikes/e-bikes/[a-z-]+")
    pdps: dict[str, str] = {}
    for sub in subs:
        cat = sub.rsplit("/", 1)[-1]                         # electric-mountain / -road
        grid = _get(BASE + sub)
        for series in _links(grid, r"/us/bikes-[a-z0-9-]*eplus[a-z0-9-]*"):
            page = _get(BASE + series)
            for p in _links(page, r"/us/[a-z0-9-]*eplus[a-z0-9-]*"):
                if p.startswith("/us/bikes-"):              # the series page itself
                    continue
                pdps.setdefault(BASE + p, cat)
    return pdps


def scrape_pdp(url: str, cat: str) -> dict:
    h = _get(url)
    m = _LD.search(h)
    d = json.loads(m.group(1)) if m else {}
    name = _clean(d.get("name") or "")
    offers = d.get("offers") or []
    prices = [float(o["price"]) for o in offers if o.get("price")]
    # in stock when any size/colour offer is purchasable (per-variant availability)
    available = (any("InStock" in (o.get("availability") or "") for o in offers)
                 if offers else None)
    image = d.get("image")
    handle = url.rstrip("/").rsplit("/", 1)[-1]

    specs: dict[str, str] = {}
    for k, v in _SPEC.findall(h):
        key, val = _clean(k), _clean(v)
        if not key or not val or key in specs:
            continue
        # Giant's "Weight" row is a "have your dealer weigh it" disclaimer, not a value
        if key.lower() == "weight" and not re.search(r"\d", val):
            continue
        specs[key] = val

    # bottom-of-page technical info that isn't in the spec list: range estimator + the
    # weight quoted in the model's prose.
    rng = _range_text(h)
    if rng:
        specs.setdefault("Range", rng)
    wt = _weight_text(h)
    if wt:
        specs["Weight"] = wt

    # SyncDriveMove hub motors list the mid-drive-EQUIVALENT torque in the spec row;
    # rewrite it to lead with the real hub torque (torque_nm parses the first Nm) so a
    # 30Nm hub road bike isn't recorded as torquey as an 85Nm mid-drive eMTB.
    mrow = specs.get("Motor", "")
    if re.search(r"syncdrivemove|hub[\s-]?drive", mrow, re.I):
        actual = _hub_torque(h)
        if actual:
            eqm = re.search(r"(\d+)\s*Nm", mrow)
            # NB don't write "mid-drive" into the value — _drive_type matches \bmid\b
            repl = (f"{actual}Nm (≈{eqm.group(1)}Nm-equivalent)"
                    if eqm else f"{actual}Nm")
            specs["Motor"] = re.sub(r"\d+\s*Nm[^,]*", repl, mrow, count=1)

    color = specs.get("Colors") or "Standard"
    price = min(prices) if prices else None
    # frame sizes + rider-height range from the Sizing Guide size-bar; fall back to the
    # "Sizes" BOM row ("S, M, L, XL") for label-only sizes when the guide is absent.
    rh = _rider_heights(h)
    if rh:
        frame_sizes = [{"size": s, "height_min": lo, "height_max": hi}
                       for s, (lo, hi) in rh.items()]
    else:
        frame_sizes = [{"size": s.strip()}
                       for s in re.split(r"[,/]", specs.get("Sizes", "")) if s.strip()]

    return {
        "model": name or handle,
        "handle": handle,
        "url": url,
        # category hint for normalize's classifier (the PDP url has no category word)
        "vehicle_type": CAT_VEHICLE.get(cat, "electric bike"),
        "currency": "USD",
        "price_from": price,
        "options": {"colors": [{"name": color, "hex": None, "swatch_image": None,
                                "image": image}]},
        "configurations": [{"options": {"color": color}, "price": price,
                            "available": available}],
        "frame_sizes": frame_sizes,
        "geometry": _geometry(h),
        "specs": {"all": specs},
        "spec_count": len(specs),
        "scrape_error": None if specs else "no specs",
    }


def run(args) -> int:
    print(f"[*] Discovering Giant e-bikes from {EBIKES} ...", file=sys.stderr)
    pdps = discover()
    items = list(pdps.items())
    if args.limit:
        items = items[: args.limit]
    print(f"[*] Found {len(items)} E+ build(s).", file=sys.stderr)

    results: list[dict] = []
    for url, cat in items:
        try:
            r = scrape_pdp(url, cat)
        except Exception as e:  # noqa: BLE001
            handle = url.rstrip("/").rsplit("/", 1)[-1]
            r = {"model": handle, "handle": handle, "url": url, "vehicle_type": "",
                 "specs": {"all": {}}, "spec_count": 0,
                 "scrape_error": f"{type(e).__name__}: {e}"}
        # classify from the name + category only (NOT the BOM — component model names
        # carry stray terrain words); normalize re-derives the same via vehicle_type.
        r["product_types"] = classify_product_types(r["model"], r.get("vehicle_type", ""), "")
        results.append(r)
        status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
        print(f"    - {r['model'][:34]:<34} {r['spec_count']:>3} specs  [{status}]",
              file=sys.stderr)
        time.sleep(args.delay)

    results.sort(key=lambda r: r["model"] or "")
    out = {
        "source": BASE, "logo": LOGO, "collection": COLLECTION,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(results), "models": results,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Giant e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/giant_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N models.")
    ap.add_argument("--delay", type=float, default=0.4, help="Seconds between PDP fetches.")
    args = ap.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
