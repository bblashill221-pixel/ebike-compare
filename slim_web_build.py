#!/usr/bin/env python3
"""
Emit the slim web payload from the full normalized build.

The app has no database: web/public/ebike.json is fetched whole, parsed, and
held in memory (mobile pain = parse time + memory, growing per brand). The component
de-duplication now happens UPSTREAM in intern_components.py (the shared `components` table
+ refs, which the internal build also carries). This step just produces the web copy: it

  1. drops fields the web never reads / aren't read at runtime, and
  2. minifies (the internal file is pretty-printed).

The `components` table + the `model.specs[group][field]` refs pass through unchanged; the
app rehydrates them once in DataProvider. (If run on a NOT-yet-interned file it still works
— it just emits the inline specs without the shared table.)

Usage:  python slim_web_build.py [-i active.json] [-o web/public/ebike.json]
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "data" / "current" / "active" / "ebike.json"
DST = HERE / "web" / "public" / "ebike.json"

# Fields not consumed by the web app (verified) or not read at runtime.
DROP_MODEL_KEYS = {
    "brand_extra", "available_options", "variant_options", "color_names", "source_id",
    "spec_count", "scrape_error", "curated_overrides", "html_extracted", "data_audit",
}
DROP_ANALYSIS_KEYS = {"percentiles", "feature_notable", "highlights"}
DROP_CONFIG_KEYS = {"image", "sku"}   # card pricing needs only options/price/available


def slim(doc: dict) -> dict:
    for m in doc.get("models", []):
        for k in DROP_MODEL_KEYS:
            m.pop(k, None)
        analysis = m.get("analysis")
        if isinstance(analysis, dict):
            for k in DROP_ANALYSIS_KEYS:
                analysis.pop(k, None)
        for cfg in m.get("configurations") or []:
            if isinstance(cfg, dict):
                for k in DROP_CONFIG_KEYS:
                    cfg.pop(k, None)
    # The `components` table + the model.specs refs (from intern_components.py) pass
    # through unchanged — that's the shared-component dedup the app rehydrates.
    return doc


def main():
    ap = argparse.ArgumentParser(description="Write the slim web payload from the full build.")
    ap.add_argument("-i", "--input", default=str(SRC))
    ap.add_argument("-o", "--output", default=str(DST))
    args = ap.parse_args()

    raw = Path(args.input).read_bytes()
    doc = json.loads(raw)
    out = json.dumps(slim(doc), ensure_ascii=False, separators=(",", ":"))
    Path(args.output).write_text(out, encoding="utf-8")

    before, after = len(raw), len(out.encode("utf-8"))
    gz = len(gzip.compress(out.encode("utf-8")))
    print(f"[slim] {args.output}: {before/1e6:.2f} MB -> {after/1e6:.2f} MB raw "
          f"({100*(before-after)/before:.0f}% smaller), {gz/1e6:.2f} MB gzip; "
          f"{len(doc.get('components') or {})} shared components")


if __name__ == "__main__":
    main()
