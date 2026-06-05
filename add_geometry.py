#!/usr/bin/env python3
"""
Pull geometric dimensions out of each model's specs into a structured
`geometry` field (standover height, reach, stack, top tube, head/seat tube,
chainstay, wheelbase, rider-height range, seat height, frame size, angles, …).

Specs that look like geometry are copied (not removed) into model["geometry"].
Run after the scrapers (the wrapper calls it automatically).
"""
import glob
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

# Geometry-dimension keywords (substring match on the spec label).
GEO_KEYS = (
    "standover", "stand over", "reach", "stack", "top tube", "head tube",
    "seat tube", "headtube", "seattube", "chainstay", "chain stay", "wheelbase",
    "wheel base", "rider height", "user height", "recommended rider",
    "height range", "inseam", "seat height", "saddle height", "frame size",
    "bike size", "head angle", "seat angle", "head tube angle", "seat tube angle",
    "handlebar width", "saddle width", "seatpost length", "frame stack",
    "effective top tube", "minimum seat", "maximum seat", "min saddle",
    "max saddle", "standover height", "fork offset", "frame reach", "frame geometry",
    "stand-over", "step-over", "step over", "stepover",
)
# Labels that contain a geo word but are really components -> exclude.
EXCLUDE = ("fork ", "crankset", "bottom bracket", "tire", "tyre", "wheel size",
           "rim", "headset", "spoke", "size & fit", "stem ")


def is_geo(label: str) -> bool:
    low = label.lower()
    if any(x in low for x in EXCLUDE):
        return False
    return any(k in low for k in GEO_KEYS)


def per_size(value):
    """Turn "S: 170mm | M: 170mm | L: 175mm" into {"S": "170mm", ...} so geometry
    is per size variant; otherwise return the value unchanged."""
    if not isinstance(value, str) or " | " not in value:
        return value
    parts = [p.strip() for p in value.split(" | ")]
    out = {}
    for p in parts:
        m = re.match(r"^([A-Za-z0-9./'\"-]{1,6})\s*:\s*(.+)$", p)
        if not m:
            return value
        out[m.group(1)] = m.group(2).strip()
    return out or value


def main():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        d = json.load(open(f))
        with_geo = 0
        for m in d.get("models", []):
            specs = (m.get("specs") or {}).get("all", {}) or {}
            # Preserve any geometry the scraper already captured (e.g. a dedicated
            # geometry table), then add geometry-looking rows from the specs.
            geo = dict(m.get("geometry") or {})
            for label, value in specs.items():
                if is_geo(label) and label not in geo:
                    geo[label] = value
            # Structure per-size values ("S: x | M: y") into {size: value} dicts so
            # geometry is captured per model variant where the source is per-size.
            geo = {k: per_size(v) for k, v in geo.items()}
            m["geometry"] = geo
            if geo:
                with_geo += 1
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
        print(f"{Path(f).stem.replace('_ebikes',''):<12} models_with_geometry="
              f"{with_geo}/{len(d.get('models', []))}")


if __name__ == "__main__":
    main()
