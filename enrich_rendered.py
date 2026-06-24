#!/usr/bin/env python3
"""Rendered per-size rider-height extractor.

Rule of thumb (confirmed across brands): if a bike publishes a *total* rider-height
envelope, its *per-size* breakdown is published too -- in the size guide. The
static-HTML enricher (enrich_frame_sizes.py) only sees the envelope, because the
per-size table is rendered client-side (a size selector showing "Small  Fit for
5'3"~5'9"" ...) or shipped as a chart image. So for every multi-size bike still
lacking per-size ranges we RENDER the page and capture per-size (label, range)
pairs from the DOM. When the size guide is only an image, we record its URL for
transcription into data/curated/image_heights.json instead.

Targets bikes that (a) have size labels but null per-size heights, or (b) are
still flagged by the audit as missing a rider-height range.

Usage: python enrich_rendered.py [--brand NAME] [--limit N]
Writes per-size heights back into data/current/<brand>_ebikes.json (text source)
and data/current/size_chart_worklist.json (image source, for manual reading).
"""
import argparse
import glob
import json
import re
from collections import defaultdict
from pathlib import Path

import scraper_common  # noqa
from playwright.sync_api import sync_playwright

DATA = Path(__file__).parent / "data"
ACTIVE = DATA / "current" / "active" / "ebike.json"
WORKLIST = DATA / "current" / "size_chart_worklist.json"

_RNG = re.compile(r"(\d+)['’]\s*(\d+)?\s*[\"”'’]{0,2}\s*[-~–]\s*(\d+)['’]\s*(\d+)?")

# DOM scrape: per-size (label,text) pairs from size-selector-like elements, plus
# the best size-chart image. Kept in one evaluate() call to render each page once.
_JS = r"""
() => {
  const SIZE=/(x-?small|small|medium|large|x-?large|regular|standard|one[ -]?size|\bxs\b|\bsm\b|\bmd\b|\blg\b|\bxl\b|\bxxl\b|\bs\b|\bm\b|\bl\b)/i;
  const RNG=/\d['’]\s*\d+['’"]*\s*[~\-–]\s*\d['’]\s*\d+/;
  const pairs=[];
  for (const el of document.querySelectorAll('label,button,div,span,li,option,td,th,p')) {
    const t=(el.innerText||'').trim();
    if (!t || t.length>70 || !RNG.test(t)) continue;
    const s=t.match(SIZE);
    if (s) pairs.push([s[1], t]);
  }
  let chart=null;
  for (const im of document.querySelectorAll('img')) {
    const u=(im.currentSrc||im.src||'');
    if (/size[-_ ]?chart|size[-_ ]?guide|sizechart|sizeguide|sizing/i.test(u+'|'+(im.alt||''))) {chart=u; break;}
  }
  return {pairs, chart};
}"""

_LABEL_NORM = {"xs": "X-Small", "s": "Small", "sm": "Small", "m": "Medium", "md": "Medium",
               "l": "Large", "lg": "Large", "xl": "X-Large", "xxl": "XX-Large"}


def _norm_label(raw: str) -> str:
    k = raw.strip().lower().replace(" ", "").replace("-", "")
    if k in ("onesize", "standard", "regular"):
        return raw.strip().title()
    return _LABEL_NORM.get(k, raw.strip().title())


def _pairs_to_sizes(pairs: list) -> list[dict]:
    """(label, full-text) pairs -> [{size, height_min, height_max}], first per label."""
    out, seen = [], set()
    for raw_label, text in pairs:
        m = _RNG.search(text)
        if not m:
            continue
        size = _norm_label(raw_label)
        if size in seen:
            continue
        a, b, c, d = m.groups()
        seen.add(size)
        out.append({"size": size, "height_min": f"{a}'{int(b or 0)}\"",
                    "height_max": f"{c}'{int(d or 0)}\""})
    return out


def _needs(m: dict) -> bool:
    fs = m.get("frame_sizes")
    if fs and not all(s.get("height_min") for s in fs):
        return True                                  # size labels but null heights
    miss = (m.get("data_audit") or {}).get("missing", [])
    return "fit_height_min_in" in miss or "frame_size_rider_range" in miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    targets = [m for m in json.load(open(ACTIVE))["models"]
               if _needs(m) and m.get("url") and (not args.brand or m["brand"] == args.brand)]
    if args.limit:
        targets = targets[:args.limit]

    text_sizes = {}                                  # id -> [frame_sizes]
    charts = {}                                      # id -> {chart, brand, model, page}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        for i, m in enumerate(targets):
            pg = b.new_page(viewport={"width": 1366, "height": 1300})
            res = {"pairs": [], "chart": None}
            try:
                pg.goto(m["url"], wait_until="domcontentloaded", timeout=45000)
                pg.wait_for_timeout(2500)
                for _ in range(7):
                    pg.mouse.wheel(0, 2400)
                    pg.wait_for_timeout(180)
                res = pg.evaluate(_JS)
            except Exception:
                pass
            pg.close()
            sizes = _pairs_to_sizes(res.get("pairs") or [])
            tag = "--"
            if len(sizes) >= 1:
                text_sizes[m["url"]] = sizes
                tag = f"TEXT {[s['size'] for s in sizes]}"
            elif res.get("chart"):
                charts[m["id"]] = {"brand": m["brand"], "model": m["model"],
                                   "page": m["url"], "chart": res["chart"].split("?")[0]
                                   if "specialized.com" not in res["chart"] else res["chart"]}
                tag = "IMG"
            print(f"  [{i+1}/{len(targets)}] {m['brand']:11} {m['model'][:28]:30} {tag}")
        b.close()

    # apply text-sourced per-size ranges back into the brand JSONs (match by id)
    applied = 0
    for f in glob.glob(str(DATA / "current" / "*_ebikes.json")):
        d = json.load(open(f))
        ch = False
        for m in d.get("models", []):
            new = text_sizes.get(m.get("url"))
            if new:
                m["frame_sizes"] = new
                ch = True
                applied += 1
        if ch:
            Path(f).write_text(json.dumps(d, indent=2, ensure_ascii=False))

    WORKLIST.write_text(json.dumps(charts, indent=1, ensure_ascii=False))
    by_img = defaultdict(list)
    for mid, v in charts.items():
        by_img[v["chart"]].append(mid)
    print(f"\n[rendered] {len(text_sizes)} models got per-size TEXT ranges "
          f"(applied {applied}); {len(charts)} need an image chart ({len(by_img)} unique) -> {WORKLIST}")


if __name__ == "__main__":
    main()
