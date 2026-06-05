#!/usr/bin/env python3
"""
Add the grouped spec view to every per-brand file so all JSON files share the
same `specs` schema as the normalized dataset: `{ all, grouped }`.

`grouped` reorganizes the flat `specs.all` map into ordered, Aventon-style
sections (see spec_groups.py); the Geometry group is the model's `geometry`
field, so this MUST run after add_geometry.py. The raw physical/technical split
is dropped (superseded by `grouped`). Runs in the post-scrape build chain.
"""
import glob
import json
from pathlib import Path

from spec_groups import group_specs

DATA = Path(__file__).parent / "data"


def main():
    for f in sorted(glob.glob(str(DATA / "*_ebikes.json"))):
        if f.endswith("_normalized.json"):
            continue
        d = json.load(open(f))
        for m in d.get("models", []):
            all_specs = (m.get("specs") or {}).get("all") or {}
            m["specs"] = {
                "all": all_specs,
                "grouped": group_specs(all_specs, m.get("geometry") or {}),
            }
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
        ms = d.get("models", [])
        groups = {g for m in ms for g in m["specs"]["grouped"]}
        print(f"{Path(f).stem.replace('_ebikes',''):<11} grouped {len(ms)} models "
              f"into {len(groups)} distinct groups")


if __name__ == "__main__":
    main()
