#!/usr/bin/env python3
"""
Merge per-color duplicate products and family-link frame-style variants.

Some brands publish one product page per colorway (Monarc's Marker line:
"Marker High-Step Cedar Ebike", "Marker High-Step Taconite Ebike", ...). Color
is never a card on this site — colors with the same price belong on one card as
swatches — so entries whose names differ only by their own color name, at the
same price, merge into one model carrying all the colors (each color keeps its
source page as `href`).

Frame styles are the opposite: Step-Thru vs Step-Over ARE distinct cards. They
stay separate here; a second pass links models whose names differ only by a
frame-style token ("Marker High-Step Ebike" / "Marker Step-Thru Ebike",
Velowave "FLINT" / "FLINT ST") into one family (`family_id` + `tier` +
`frame_style`) so the site shows them as siblings and the style is searchable.

Idempotent: merged names no longer contain a color name; family links re-derive
to the same values.

Run before expand_tiers.py (run_scrape.sh wires this).
"""
import glob
import json
import re
from pathlib import Path

from bike_taxonomy import STEP_THRU, STEP_OVER, frame_style_of

HERE = Path(__file__).parent
DATA = HERE / "data"

FRAME_LABEL = {STEP_THRU: "Step-Thru", STEP_OVER: "Step-Over"}

# frame-style tokens that may appear inside a model name
_FRAME_TOKEN = re.compile(
    r"step[\s_-]?thr(?:u|ough)|step[\s_-]?over|high[\s_-]?step|mid[\s_-]?step"
    r"|low[\s_-]?step|\bst\b|\bxr\b|(?<=[a-z])ST\b", re.I)


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def _squash(s: str) -> str:
    return re.sub(r"\s{2,}", " ", s).strip(" -—")


def color_names(m: dict) -> list:
    cols = ((m.get("options") or {}).get("colors")) or m.get("colors") or []
    return [str(c.get("name") or c.get("label")) for c in cols
            if isinstance(c, dict) and (c.get("name") or c.get("label"))]


def name_of(m: dict) -> str:
    return m.get("model") or m.get("title") or m.get("name") or ""


def strip_own_colors(name: str, colors: list) -> str:
    out = name
    for c in colors:
        out = re.sub(re.escape(c), "", out, flags=re.I)
    return _squash(out)


def price_of(m: dict):
    pr = m.get("price_range") or {}
    return m.get("price") or m.get("price_from") or pr.get("min")


# ------------------------------ color merging ------------------------------

def merge_colors(models: list) -> list:
    groups: dict = {}
    order = []
    for m in models:
        name = name_of(m)
        stripped = strip_own_colors(name, color_names(m))
        # only candidate when the name actually embeds the colorway
        key = (stripped, price_of(m)) if stripped != name else (name, id(m))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(m)

    out = []
    for key in order:
        grp = groups[key]
        if len(grp) == 1:
            out.append(grp[0])
            continue
        base = grp[0]
        stripped = key[0]
        base["model"] = stripped
        base["handle"] = slugify(stripped)
        cols = []
        for m in grp:
            for c in ((m.get("options") or {}).get("colors")) or []:
                c = dict(c)
                c.setdefault("href", m.get("url"))   # each colorway keeps its page
                cols.append(c)
            for c in m.get("configurations") or []:
                if m is not base:
                    base.setdefault("configurations", []).append(c)
        base.setdefault("options", {})["colors"] = cols
        print(f"  merged {len(grp)} colorways -> {stripped!r}")
        out.append(base)
    return out


# --------------------------- frame-style families ---------------------------

def link_frame_families(brand: str, models: list) -> None:
    groups: dict = {}
    for m in models:
        name = name_of(m)
        base = _squash(_FRAME_TOKEN.sub("", name))
        if base and base != name:
            groups.setdefault(base, []).append(m)
        else:
            # unsignaled names can still anchor a family ("FLINT" vs "FLINT ST")
            groups.setdefault(name, []).append(m)
    for base, grp in groups.items():
        if len(grp) < 2:
            continue
        styles = {id(m): frame_style_of(name_of(m)) for m in grp}
        found = {s for s in styles.values() if s}
        if not found:
            continue
        fam = f"{brand}__{slugify(base)}"
        for m in grp:
            # a sibling without a token is the step-over variant of an ST model
            style = styles[id(m)] or STEP_OVER
            m.setdefault("family_id", fam)
            m.setdefault("tier", FRAME_LABEL[style])
            m.setdefault("frame_style", style)


def main():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        d = json.load(open(f))
        before = json.dumps(d, sort_keys=True)
        models = merge_colors(d.get("models", []))
        link_frame_families(brand, models)
        d["models"] = models
        d["model_count"] = len(models)
        if json.dumps(d, sort_keys=True) != before:
            json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
            print(f"{brand:<12} -> {len(models)} models")


if __name__ == "__main__":
    main()
