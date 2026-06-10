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
            for a, b, c, d in re.findall(r"(\d+)'\s*(\d+)\"?\s*[-–]\s*(\d+)'\s*(\d+)", text)]


# ------------------------------ brand extractors ----------------------------

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
    return [{"size": None, "height_min": lo, "height_max": hi} for lo, hi in _ranges(m.group(1))]


def _velotric(page: str, name: str) -> list[dict]:
    """Velotric embeds per-product JSON with a user_height_range that is either a
    single range or labelled per-variant ranges ("HS/R: 4'11" - 5'8" …")."""
    best = None
    for mo in re.finditer(r'"title":"([^"]*)","user_height_range":"((?:[^"\\]|\\.)*)"', page):
        title, rng = html.unescape(mo.group(1)), mo.group(2)
        rng = re.sub(r"\\u003c[^\\]*\\u003e|<[^>]+>", " ", rng).replace("''", '"').replace("’", "'")
        if name and name.lower() in title.lower():
            best = rng
            break
        best = best or rng
    if not best:
        return []
    labelled = re.findall(r"([A-Za-z/ ]{1,18}):\s*(\d+'\s*\d+\"?\s*[-–]\s*\d+'\s*\d+)", best)
    if labelled:
        return [{"size": lbl.strip(" :/"), "height_min": r[0], "height_max": r[1]}
                for lbl, seg in labelled for r in _ranges(seg)]
    return [{"size": None, "height_min": lo, "height_max": hi} for lo, hi in _ranges(best)]


EXTRACTORS = {
    "aventon": lambda p, n: _aventon(p),
    "priority": lambda p, n: _priority(p),
    "velowave": lambda p, n: _velowave(p),
    "velotric": lambda p, n: _velotric(p, n),
}


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
            if m.get("frame_sizes"):       # already captured (e.g. Aventon scraper)
                continue
            sizes = EXTRACTORS[brand](fetch(m.get("url", "")), m.get("model") or m.get("title", ""))
            if not sizes:
                continue
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
