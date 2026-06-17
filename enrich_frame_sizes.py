#!/usr/bin/env python3
"""
Capture each bike's frame sizes and per-size rider-height range.

Most brands sell a bike in one frame size (the scraped rider-height range already
covers it). Some publish a per-frame size chart; this stage fetches the product
page and, with a brand-specific extractor, pulls each size's rider-height range
into `model.frame_sizes` ([{size, height_min, height_max}, ...]) and resets the
bike's rider height to the full envelope (smallest frame's min .. largest frame's
max), so the displayed/searchable range spans every size.

Aventon already captures this in its scraper (model.frame_sizes); models that
already have it are skipped. Runs after the scrapers, before normalize.

Usage:  python enrich_frame_sizes.py [--brand NAME]
"""
import argparse
import glob
import html
import json
import re
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "data"


def fetch(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def _to_in(s):
    m = re.match(r"(\d+)\s*'\s*(\d+)", (s or "").strip())
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None


def _fmt(inch: int) -> str:
    return f"{inch // 12}'{inch % 12}\""


def envelope(sizes: list[dict]):
    mins = [v for s in sizes if (v := _to_in(s.get("height_min")))]
    maxs = [v for s in sizes if (v := _to_in(s.get("height_max")))]
    return (f"{_fmt(min(mins))} - {_fmt(max(maxs))}") if mins and maxs else None


def _ranges(text: str) -> list[tuple[str, str]]:
    """All "A'B - C'D" rider-height ranges in a blob -> [(min, max), ...]."""
    return [(f"{a}'{b}\"", f"{c}'{d}\"")
            for a, b, c, d in re.findall(r"(\d+)'\s*(\d+)\"?\s*[-–~]\s*(\d+)'\s*(\d+)", text)]


_H_LABEL = re.compile(r"(?:rider|recommended|suitable|user|fit)\s*heights?\s*[:：]?", re.I)


def _cm_to_ftin(cm: float) -> str:
    inch = round(cm / 2.54)
    return f"{inch // 12}'{inch % 12}\""


def _decft_to_ftin(ft: float) -> str:
    inch = round(ft * 12)
    return f"{inch // 12}'{inch % 12}\""


def _generic(page: str) -> list[dict]:
    """Single rider-height range published on a product page (most bikes are sold
    in one frame size). Anchored on a "Rider/Recommended/Suitable/User Height"
    label, then the first range in any supported notation -- preferring the brand's
    own imperial feet-inches, then centimetres, then decimal feet -- emitted as a
    one-size collection. Returns [] when no labelled range is in the static HTML."""
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    segs = [txt[m.end():m.end() + 70] for m in _H_LABEL.finditer(txt)]
    if not segs:
        return []
    one = lambda lo, hi: [{"size": None, "height_min": lo, "height_max": hi}]
    for seg in segs:                                   # feet-inches (high inches optional: 5'1"~6')
        mo = re.search(r"(\d+)['’]\s*(\d+)?\s*[\"”'’]{0,2}\s*[-~–]\s*(\d+)['’]\s*(\d+)?", seg)
        if mo:
            a, b, c, d = mo.groups()
            return one(f"{a}'{int(b or 0)}\"", f"{c}'{int(d or 0)}\"")
    for seg in segs:                                   # centimetres
        mo = re.search(r"(\d{3})\s*[-~–]\s*(\d{3})\s*cm", seg)
        if mo:
            return one(_cm_to_ftin(int(mo.group(1))), _cm_to_ftin(int(mo.group(2))))
    for seg in segs:                                   # decimal feet (e.g. 5.6~6.5ft)
        mo = re.search(r"(\d\.\d)\s*[-~–]\s*(\d\.\d)\s*ft", seg)
        if mo:
            return one(_decft_to_ftin(float(mo.group(1))), _decft_to_ftin(float(mo.group(2))))
    return []


# ------------------------------ brand extractors ----------------------------

def _ride1up(page: str) -> list[dict]:
    """Ride1Up publishes a per-size geometry chart: column headers (e.g. "SMALL
    LARGE"), then the row labels (Bike Weight, Weight Capacity, Rider Height
    Range, A - Maximum Seat Height, …), then the values laid out column-major — so
    each size's rider-height range appears once, in header order. (CF RACER1 is
    currently the only multi-size Ride1Up bike.)"""
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    _SZ = r"X-?Small|Small|Medium|Large|X-?Large"
    hdr = re.search(rf"((?:\b(?:{_SZ})\b\s+){{2,}})Bike Weight", txt, re.I)
    if not hdr:
        return []
    sizes = [s.title() for s in re.findall(_SZ, hdr.group(1), re.I)]
    ranges = _ranges(txt[hdr.start():])   # one rider-height range per size column
    if len(ranges) < len(sizes):
        return []
    return [{"size": s, "height_min": lo, "height_max": hi}
            for s, (lo, hi) in zip(sizes, ranges)]


def _aventon(page: str) -> list[dict]:
    out, seen = [], set()
    for mo in re.finditer(r'\{[^{}]*"height_max"[^{}]*\}', page):
        b = html.unescape(mo.group(0)).replace("”", '"').replace("“", '"').replace("’", "'")
        g = lambda k: (m.group(1).strip() if (m := re.search(r'"' + k + r'"\s*:\s*"([^"]*)"', b)) else None)
        name, lo, hi = g("size_full_name") or g("bike_size_label"), g("height_min"), g("height_max")
        if name and lo and hi and (name, lo, hi) not in seen:
            seen.add((name, lo, hi))
            out.append({"size": name, "height_min": lo, "height_max": hi})
    return out


def _priority(page: str) -> list[dict]:
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    m = re.search(r"(?:Approx\.?\s*)?Inseam\s*and\s*Height(.{0,400})", txt, re.I)
    if not m:
        return []
    seg = m.group(1)
    sizes = re.findall(r"\b(X?-?Small|Medium|Large|X-?Large|XS|S|M|L|XL)\b",
                       txt[max(0, m.start() - 120):m.start()])
    pairs = _ranges(seg)
    return [{"size": (sizes[i] if i < len(sizes) else None), "height_min": lo, "height_max": hi}
            for i, (lo, hi) in enumerate(pairs)]


def _velowave(page: str) -> list[dict]:
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    m = re.search(r"Frame\s*size\s*Rider\s*Height\s*Inseam(.{0,400})", txt, re.I)
    if not m:
        return []
    seg = m.group(1)
    # Each chart row is "<size>"  <rider-height range>  <inseam...>, e.g.
    # '17" 5\'5" - 6\'4" ...'. Capture the size label that precedes each range.
    out = [{"size": " ".join(sz.split()), "height_min": f"{a}'{b}\"", "height_max": f"{c}'{d}\""}
           for sz, a, b, c, d in re.findall(
               r'(\d{1,2}(?:\.\d)?\s*["”″])\s*(\d+)\'\s*(\d+)"?\s*[-–]\s*(\d+)\'\s*(\d+)', seg)]
    if out:
        return out
    # older layout with no size column: keep just the ranges
    return [{"size": None, "height_min": lo, "height_max": hi} for lo, hi in _ranges(seg)]


def _velotric_geometry(page: str) -> list[dict]:
    """Velotric's own product page carries a per-size GEOMETRY table whose first
    row per size is that size's rider height ("Regular Height 4'11'' ~ 5'9'' Seat
    Tube Length 380mm ... Large Height 5'6'' ~ 6'4'' ..."). This is authoritative
    for the product, so it's preferred over the cross-product comparison widget
    (which omits the product's own entry). Parsed from the static page."""
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    m = re.search(r"GEOMETRY(.{0,2000})", txt)
    if not m:
        return []
    out, seen = [], set()
    for lbl, a, b, c, d in re.findall(
            r"([A-Za-z]+)\s+Height\s*(\d+)'\s*(\d+)['\"]*\s*[~\-–]\s*(\d+)'\s*(\d+)",
            m.group(1)):
        size = lbl.strip()
        if size in seen:                  # first (authoritative) block per size wins
            continue
        seen.add(size)
        out.append({"size": size, "height_min": f"{a}'{b}\"", "height_max": f"{c}'{d}\""})
    return out


def _velotric_user_height(page: str) -> list[dict]:
    """The product's own "User Height Range" spec row carries its per-size fit,
    with explicit size labels across all current templates:
      - "R: 5'2'' ~ 5'11''  L: 5'9'' ~ 6'7''"          (Discover 3; R/L)
      - "Regular: 4'11'' ~ 5'9'' / Large: 5'6'' ~ 6'4''" (Discover 2)
      - style-prefixed "ST (...): Regular: 5'2'' ~ 5'11'' Large: 5'10'' ~ 6'5''"
        (Nomad 2 -- first range per size wins, i.e. the default build), or
      - a single "5'0'' ~ 6'3''" envelope (GoMad -- one unlabelled size).
    The cross-product comparison widget lives in JSON, not after this text label,
    so it is never matched here."""
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    norm = {"R": "Regular", "L": "Large"}
    rng = r"(\d+)'\s*(\d+)['\"]*\s*[~\-–]\s*(\d+)'\s*(\d+)"
    for mo in re.finditer(r"User Height Range(.{0,220})", txt):
        seg = mo.group(1)
        out = []
        for lab, a, b, c, d in re.findall(
                r"\b(Regular|Large|Small|Medium|R|L)\s*[:：]\s*" + rng, seg):
            size = norm.get(lab, lab)
            if any(s["size"] == size for s in out):     # first (default-build) pair wins
                continue
            out.append({"size": size, "height_min": f"{a}'{b}\"", "height_max": f"{c}'{d}\""})
        if out:
            return out
        env = re.findall(rng, seg)                       # unlabelled single envelope
        if len(env) == 1:
            a, b, c, d = env[0]
            return [{"size": None, "height_min": f"{a}'{b}\"", "height_max": f"{c}'{d}\""}]
    return []


def _velotric(page: str, name: str, model: dict) -> list[dict]:
    """Prefer the product's own per-size data (authoritative, per-URL): the
    explicitly-labelled "User Height Range" spec row, else the GEOMETRY table.
    Fallback: the `data-product-spec-json` comparison block listing EVERY Velotric
    bike (price + type + user_height_range), matched by the product's from-price
    and only when that price is unique on the page (otherwise ambiguous, so left
    missing rather than guessed). Older pages keyed entries by "title"."""
    geo = _velotric_user_height(page) or _velotric_geometry(page)
    if geo:
        return geo
    best = None
    price = model.get("price_from") or model.get("price")
    entries = re.findall(r'"price":"([^"]*)"[^}]*?"user_height_range":"((?:[^"\\]|\\.)*)"', page, re.S)
    if price is not None and entries:
        target = round(float(price))
        matches = [h for pstr, h in entries
                   if (nums := [int(x.replace(",", "")) for x in re.findall(r"([\d,]{3,7})", pstr)])
                   and min(nums) == target]
        if len(matches) == 1:
            best = matches[0]
    if best is None:                                   # legacy "title" format
        for mo in re.finditer(r'"title":"([^"]*)","user_height_range":"((?:[^"\\]|\\.)*)"', page):
            title, rng = html.unescape(mo.group(1)), mo.group(2)
            if name and name.lower() in title.lower():
                best = rng
                break
    if not best:
        return []
    best = re.sub(r"\\u003c[^\\]*\\u003e|<[^>]+>", " ", best).replace("''", '"').replace("’", "'")
    labelled = re.findall(r"([A-Za-z/ ]{1,18}):\s*(\d+'\s*\d+\"?\s*[-–]\s*\d+'\s*\d+)", best)
    if labelled:
        return [{"size": lbl.strip(" :/"), "height_min": r[0], "height_max": r[1]}
                for lbl, seg in labelled for r in _ranges(seg)]
    return [{"size": None, "height_min": lo, "height_max": hi} for lo, hi in _ranges(best)]


# Brands with a per-size size-chart extractor; generic single-size capture backs
# them up (and covers every other brand) when no chart is present on the page.
_CHART = {
    "aventon": lambda p, n, m: _aventon(p),
    "priority": lambda p, n, m: _priority(p),
    "velowave": lambda p, n, m: _velowave(p),
    "velotric": lambda p, n, m: _velotric(p, n, m),
    "ride1up": lambda p, n, m: _ride1up(p),
}
# Every brand we scrape runs the enricher: its chart extractor first (if any),
# then the generic labelled-range fallback.
_ALL_BRANDS = [Path(f).stem.replace("_ebikes", "")
               for f in glob.glob(str(DATA / "current" / "*_ebikes.json"))]
EXTRACTORS = {b: (lambda p, n, m, _c=_CHART.get(b): (_c(p, n, m) if _c else []) or _generic(p))
              for b in _ALL_BRANDS}


def _set_rider_height(m: dict, env: str):
    specs = m.setdefault("specs", {}).setdefault("all", {})
    key = next((k for k in specs if "rider" in k.lower() and "height" in k.lower()), "Rider Height")
    specs[key] = env
    geo = m.get("geometry")
    if isinstance(geo, dict):
        for k in list(geo):
            if "rider" in k.lower() and "height" in k.lower():
                geo[k] = env


def main():
    ap = argparse.ArgumentParser(description="Capture per-frame-size rider-height ranges.")
    ap.add_argument("--brand", default=None)
    args = ap.parse_args()
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        if (args.brand and brand != args.brand) or brand not in EXTRACTORS:
            continue
        d = json.load(open(f))
        changed = 0
        for m in d.get("models", []):
            existing = m.get("frame_sizes")
            if existing and any(s.get("height_min") for s in existing):
                continue               # already has per-size rider heights
            sizes = EXTRACTORS[brand](fetch(m.get("url", "")), m.get("model") or m.get("title", ""), m)
            if not sizes:
                continue
            if existing:
                # Scraper captured size LABELS but no heights (e.g. Urtopia S/M/L).
                # Merge in any per-size heights by matching label; always set the
                # model's rider-height envelope so the "fits me" filter works even
                # when the page only publishes a single envelope (no per-size rows).
                by_lbl = {s["size"]: s for s in sizes if s.get("size") and s.get("height_min")}
                for s in existing:
                    src = by_lbl.get(s.get("size"))
                    if src:
                        s["height_min"], s["height_max"] = src["height_min"], src["height_max"]
                # one-size bike: the page envelope IS that size's range
                if len(existing) == 1 and not existing[0].get("height_min"):
                    los = [v for s in sizes if (v := _to_in(s.get("height_min")))]
                    his = [v for s in sizes if (v := _to_in(s.get("height_max")))]
                    if los and his:
                        existing[0]["height_min"] = _fmt(min(los))
                        existing[0]["height_max"] = _fmt(max(his))
            else:
                m["frame_sizes"] = sizes
            env = envelope(sizes)
            if env:
                _set_rider_height(m, env)
            changed += 1
        if changed:
            Path(f).write_text(json.dumps(d, indent=2, ensure_ascii=False))
        print(f"{brand:<12} frame_sizes on {sum(1 for m in d.get('models', []) if m.get('frame_sizes'))}"
              f"/{len(d.get('models', []))} models")


if __name__ == "__main__":
    main()
