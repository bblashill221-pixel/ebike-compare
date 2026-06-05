#!/usr/bin/env python3
"""
Add the grouped spec view to every per-brand file so all JSON files share the
same `specs` schema as the normalized dataset: `{ grouped }`.

`grouped` reorganizes the flat spec map into ordered, Aventon-style sections with
snake_case field names (see spec_groups.py); the Geometry group is the model's
`geometry` field, so this MUST run after add_geometry.py. The raw
physical/technical/all maps are dropped (superseded by `grouped`). Runs in the
post-scrape build chain.
"""
import glob
import json
from pathlib import Path

from spec_groups import group_specs
from parse_components import parse_component

DATA = Path(__file__).parent / "data"


def main():
    for f in sorted(glob.glob(str(DATA / "*_ebikes.json"))):
        if f.endswith("_normalized.json"):
            continue
        brand = Path(f).stem.replace("_ebikes", "")
        d = json.load(open(f))
        for m in d.get("models", []):
            specs = m.get("specs") or {}
            if specs.get("all"):
                # fresh scraper output: build the grouped view from the flat map.
                m["specs"] = {"grouped": group_specs(specs["all"], m.get("geometry") or {}, brand)}
            elif specs.get("grouped"):
                # already grouped: just parse component values in place (idempotent).
                grouped = specs["grouped"]
                sib = {k: v for fields in grouped.values()
                       for k, v in fields.items() if isinstance(v, str)}
                for fields in grouped.values():
                    for field, value in list(fields.items()):
                        if isinstance(value, str):
                            parsed = parse_component(field, value, brand, siblings=sib)
                            if parsed:
                                fields[field] = parsed
                m["specs"] = {"grouped": grouped}
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
        ms = d.get("models", [])
        groups = {g for m in ms for g in m["specs"]["grouped"]}
        print(f"{Path(f).stem.replace('_ebikes',''):<11} grouped {len(ms)} models "
              f"into {len(groups)} distinct groups")


if __name__ == "__main__":
    main()
