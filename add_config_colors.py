#!/usr/bin/env python3
"""
Make colour schemes per-configuration.

Some models (e.g. Ride1Up Vorsa) offer different colours for different
configurations. Each entry in a model's `configurations` list already records
the chosen colour *name*; this enriches it to the full colour object
({name, hex, swatch_image, image}) so every configuration carries its complete
colour scheme, and reconciles `options.colors` to include any colour that only
appears in the configurations (e.g. Vorsa's "snow").

Run after add_configurations.py (the wrapper calls it automatically).
"""
import glob
import json
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"


def color_option_key(cfg_options: dict) -> str | None:
    for k in cfg_options:
        if k.lower() == "color" or k.lower() == "colour":
            return k
    return None


def main():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        d = json.load(open(f))
        touched = 0
        for m in d.get("models", []):
            configs = m.get("configurations")
            colors = (m.get("options") or {}).get("colors")
            if not configs or colors is None:
                continue
            lookup = {c["name"].strip().lower(): c for c in colors if c.get("name")}
            seen_names = {c["name"].strip().lower() for c in colors if c.get("name")}
            per_config = False
            for cfg in configs:
                opts = cfg.get("options") or {}
                ckey = color_option_key(opts)
                if not ckey:
                    continue
                cname = str(opts[ckey]).strip()
                full = lookup.get(cname.lower())
                if not full:
                    # colour that only appears in configs -> add it to the model list
                    full = {"name": cname, "hex": None, "swatch_image": None, "image": None}
                    if cname.lower() not in seen_names:
                        colors.append(full)
                        lookup[cname.lower()] = full
                        seen_names.add(cname.lower())
                # attach the full colour scheme to this configuration
                cfg["color"] = {k: full.get(k) for k in ("name", "hex", "swatch_image", "image")}
                per_config = True
            if per_config:
                touched += 1
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
        print(f"{Path(f).stem.replace('_ebikes',''):<10} configs enriched with colour scheme "
              f"on {touched} models")


if __name__ == "__main__":
    main()
