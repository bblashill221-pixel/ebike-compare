#!/usr/bin/env python3
"""Harvest per-model size-chart IMAGE urls for bikes still missing a rider-height
range. Many brands (Specialized, vvolt, ...) publish the size->rider-height table
only as an image, loaded via JS -- so we render each product page, find the best
size-chart image, and group models by that image (charts are per model-family, so
one image usually covers many models). Output feeds manual/vision transcription
into data/curated/image_heights.json.

Usage: python harvest_size_charts.py [--brand NAME] [--limit N]
"""
import argparse, json, re
from collections import defaultdict
from pathlib import Path
import scraper_common  # noqa
from playwright.sync_api import sync_playwright

DATA = Path(__file__).parent / "data"
ACTIVE = DATA / "current" / "active" / "ebikes_normalized.json"
OUT = DATA / "current" / "size_chart_worklist.json"
_CHART = re.compile(r"size[-_ ]?chart|size[-_ ]?guide|sizechart|sizeguide|sizing", re.I)

def needs(m):
    miss = (m.get("data_audit") or {}).get("missing", [])
    return "fit_height_min_in" in miss or "frame_size_rider_range" in miss

def chart_img(pg):
    pairs = pg.eval_on_selector_all("img", "els=>els.map(e=>[e.currentSrc||e.src||'',e.alt||''])")
    for src, alt in pairs:
        if src and _CHART.search(src.split("?")[0]):
            return src.split("?")[0] if "specialized.com" not in src else src
    for src, alt in pairs:
        if src and _CHART.search(alt):
            return src
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand"); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    models = [m for m in json.load(open(ACTIVE))["models"]
              if needs(m) and m.get("url") and (not a.brand or m["brand"] == a.brand)]
    if a.limit: models = models[:a.limit]
    work = {}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        for i, m in enumerate(models):
            pg = b.new_page(viewport={"width": 1366, "height": 1300})
            url = None
            try:
                pg.goto(m["url"], wait_until="domcontentloaded", timeout=45000)
                pg.wait_for_timeout(2500)
                for _ in range(7): pg.mouse.wheel(0, 2400); pg.wait_for_timeout(200)
                url = chart_img(pg)
            except Exception:
                pass
            pg.close()
            work[m["id"]] = {"brand": m["brand"], "model": m["model"], "page": m["url"], "chart": url}
            print(f"  [{i+1}/{len(models)}] {m['brand']:11} {m['model'][:30]:32} {'OK' if url else '--'}")
        b.close()
    OUT.write_text(json.dumps(work, indent=1, ensure_ascii=False))
    by_img = defaultdict(list)
    for mid, v in work.items():
        if v["chart"]: by_img[v["chart"]].append(mid)
    print(f"\n[harvest] {sum(1 for v in work.values() if v['chart'])}/{len(work)} models have a size-chart image; "
          f"{len(by_img)} unique charts -> {OUT}")
main()
