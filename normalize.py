#!/usr/bin/env python3
"""
Normalize all per-brand *_ebikes.json into one combined, snake_case JSON that
adheres to a common schema: `ebike.json`.

The raw per-brand files stay the source of truth; this is a simple, derived
build step (the wrapper runs it last). The output is a flat array of model
documents designed to be loaded into a React app and searched/filtered/grouped
client-side (e.g. with Orama).
"""
import glob
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bike_taxonomy import classify_product_types, frame_style_of, pick_frame_style, primary_type, STEP_OVER, STEP_THRU

# Curated frame-style verdicts (image-inferred) for bikes that don't state one,
# keyed by "<brand>__<source_id>". Applied only as a fallback in _frame_style.
try:
    FRAME_OVERRIDES = json.loads(
        (Path(__file__).parent / "data" / "frame_style_overrides.json").read_text())
except (FileNotFoundError, ValueError):
    FRAME_OVERRIDES = {}

# Curated per-model field overrides (authoritative: a human correction wins over
# the scrape), keyed by model id -> {field: value}. Survives daily re-scrapes
# because it lives outside the archived data/current/ dir. See _apply_overrides.
try:
    MODEL_OVERRIDES = json.loads(
        (Path(__file__).parent / "data" / "curated" / "model_overrides.json").read_text())
except (FileNotFoundError, ValueError):
    MODEL_OVERRIDES = {}

# Per-size rider heights read from a size-guide IMAGE via Claude vision
# (resolve_image_heights.py), keyed by model id -> {"frame_sizes": [...]}. These
# are authoritative for the rider-height gap that text can't fill.
try:
    IMAGE_HEIGHTS = json.loads(
        (Path(__file__).parent / "data" / "curated" / "image_heights.json").read_text())
except (FileNotFoundError, ValueError):
    IMAGE_HEIGHTS = {}


# A model is "new" only when the brand's site explicitly says so (a new-arrival
# product tag), never inferred from when it showed up in our catalog.
_NEW_TAG = re.compile(r"new[\s_-]?arrival|just[\s_-]?(?:dropped|launched|released)|^new$", re.I)


def _is_new(m: dict) -> bool:
    # enrich_new_flag.py sets this explicitly from the brand's product tags;
    # fall back to deriving it from any raw tags the scraper kept.
    if isinstance(m.get("is_new"), bool):
        return m["is_new"]
    return any(_NEW_TAG.search(str(t)) for t in (m.get("tags") or []))


def _apply_overrides(nm: dict) -> dict:
    """Stamp curated field corrections onto a normalized model (authoritative).
    Records the touched fields under `curated_overrides` for transparency. A
    `geometry` dict is MERGED into specs.geometry (so curated geometry / rider-height
    rows -- e.g. read off a spec image -- join the grouped specs the page renders and
    that analyze reads); every other key is set at the top level."""
    ov = MODEL_OVERRIDES.get(nm.get("id"))
    if ov:
        for k, v in ov.items():
            if k == "geometry" and isinstance(v, dict):
                geo = nm.setdefault("specs", {}).setdefault("geometry", {})
                geo.update(v)
            elif k == "motor" and isinstance(v, dict):
                # merge a motor correction into specs.ebike_system.motor (e.g. a
                # mid-drive whose placement/brand the page never stated)
                mo = nm.setdefault("specs", {}).setdefault("ebike_system", {}).setdefault("motor", {})
                mo.update(v)
            elif k == "add_included_accessories" and isinstance(v, list):
                # Append curated $0 bundled items the text scraper can't see -- e.g. a
                # PDP promo (Monarc's free Smart Helmet) that lives outside the spec
                # table. Deduped by name against the derived list; never replaces it.
                inc = nm.setdefault("included_accessories", [])
                have = {str(a.get("name", "")).lower() for a in inc}
                for a in v:
                    if str(a.get("name", "")).lower() not in have:
                        inc.append(a)
                        have.add(str(a.get("name", "")).lower())
            elif k == "specs" and isinstance(v, dict):
                # deep-merge a {group: {field: value}} spec patch (e.g. fix a
                # manufacturer typo like ENGWE X24's "600 mile" range -> 60)
                for grp, fields in v.items():
                    if isinstance(fields, dict):
                        nm.setdefault("specs", {}).setdefault(grp, {}).update(fields)
            else:
                nm[k] = v
        nm["curated_overrides"] = sorted(ov.keys())
    return nm
from spec_groups import group_specs
from spec_parse import height_range_in, is_mid_drive


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")

HERE = Path(__file__).parent
DATA = HERE / "data"
SCHEMA_VERSION = "1.0"

# Raw model keys that map onto canonical fields (everything else -> brand_extra).
_MAPPED = {
    "model", "title", "name", "handle", "slug", "sku", "id", "url", "product_type", "product_types",
    "price_from", "price_range", "currency", "warranty", "shipping", "specs",
    "spec_count", "geometry", "options", "available_options", "configurations",
    "free_accessories", "scrape_error", "configs", "regular_price",
    "compare_at_price", "accessories", "tier", "family_id", "frame_style",
    "available",
}


_AWD_RE = re.compile(r"dual[\s-]?motor|all[\s-]?wheel[\s-]?drive|\bawd\b|two motors|\b2wd\b", re.I)


# A "Size" variant option value that looks like a frame size: the S/M/L/XL family,
# or a numeric size that carries a LENGTH unit (26", 27.5", 20 inch) -- the unit
# requirement keeps battery "15Ah"/"10.4ah" options from reading as sizes. Excludes
# step-thru/over (handled as frame styles).
_SIZE_LIKE = re.compile(
    r'^(?:xx?s|s|sm|m|md|l|lg|xx?l|xl|small|medium|large'
    r'|regular|standard|compact|tall)\b'   # word sizes (Velotric: Regular/Large)
    r'|^\d{2}(?:\.\d)?\s*(?:"|in\b|inch|cm)', re.I)


def _frame_sizes_from_options(variant_options: dict) -> list | None:
    """Frame sizes from a multi-valued "Size"/"Frame Size" variant option, for
    bikes with no per-size rider-height chart (heights left null). Skips
    frame-TYPE/style options (step-thru/over) and single-value options."""
    for k, vals in (variant_options or {}).items():
        if not re.search(r"\bsize\b", k, re.I) or not isinstance(vals, list) or len(vals) < 2:
            continue
        labels = [str(v).replace("''", '"').strip() for v in vals]
        if all(_SIZE_LIKE.match(v) for v in labels):
            return [{"size": v, "height_min": None, "height_max": None} for v in labels]
    return None


def _parse_labeled_sizes(s: str, sizes: list) -> dict | None:
    """Parse a per-size value written as labeled segments — "Large: 58 lbs |
    Medium: 57 lbs" — into {size_label: value}, keyed by the model's own size
    labels. Returns None unless every segment's label matches a known size and all
    sizes are covered."""
    by_lc = {sz.lower(): sz for sz in sizes}
    out = {}
    for seg in s.split("|"):
        mt = re.match(r"^\s*([^:]+?)\s*:\s*(.+?)\s*$", seg)
        if not mt:
            return None
        label = mt.group(1).strip().lower()
        if label not in by_lc:
            return None
        out[by_lc[label]] = mt.group(2).strip()
    return out if set(out) == set(sizes) else None


_TRADEMARK = re.compile(r"\s*[®™℠]")


def _clean_tm(s: str) -> str:
    return re.sub(r"\s{2,}", " ", _TRADEMARK.sub("", s)).strip()


def _strip_trademarks(obj):
    """Drop ®/™/℠ symbols (with any leading space) from every spec string so brand and
    component names read cleanly ("Zoom® Adjustable Stem" -> "Zoom Adjustable Stem").
    Recurses dict KEYS and values + lists; collapses any double space the removal leaves."""
    if isinstance(obj, dict):
        return {(_clean_tm(k) if isinstance(k, str) else k): _strip_trademarks(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_trademarks(v) for v in obj]
    if isinstance(obj, str):
        return _clean_tm(obj)
    return obj


def _split_geometry_by_size(grouped: dict, frame_sizes: list | None) -> None:
    """Geometry usually differs per frame size; the scrape bundles the per-size
    figures into one value — either space-separated ("432mm 470mm" for the 17"/19"
    frames) or labeled ("Large: 58 lbs | Medium: 57 lbs"). Split each into a
    {size_label: value} map so the per-size geometry is structured data, not a blob
    (an un-split labeled string renders as one smeared cell). Single-figure values
    stay as strings; a stray chart-header row ("Rider Height Inseam") is dropped."""
    geo = grouped.get("geometry")
    sizes = [s.get("size") for s in (frame_sizes or []) if s.get("size")]
    if not isinstance(geo, dict) or len(sizes) < 2:
        return
    for k in list(geo):
        v = geo[k]
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not re.search(r"\d", s):
            if re.search(r"rider|height|inseam", s, re.I):   # chart header captured as a row
                geo.pop(k, None)
            continue
        # labeled per-size form first ("<Size>: v | <Size>: v")
        if ":" in s:
            labeled = _parse_labeled_sizes(s, sizes)
            if labeled:
                geo[k] = labeled
                continue
        toks = s.split()
        if len(toks) == len(sizes):
            geo[k] = {sz: tok for sz, tok in zip(sizes, toks)}


_DT_BELT_RE = re.compile(r"belt|gates|cvt|enviolo|carbon drive|pinion|rohloff", re.I)


def _narrow_drivetrain_configs(grouped: dict, configs: list) -> None:
    """Ride1Up lists BOTH drivetrain options in one spec block, suffixing each field
    by config code (…_lx_ls = belt/CVT, …_xr_st = chain). After the config split a
    model still carries both, so a Chain bike wrongly reads as belt + internal-gear.
    Narrow the drivetrain group to this model's actual drive-train (from its own
    configurations) by dropping the non-matching config's suffixed fields."""
    dt = grouped.get("drivetrain")
    if not isinstance(dt, dict):
        return
    # classifier rows: drivetrain_<suffix> -> "belt" | "chain"
    suffix_type = {k[len("drivetrain_"):]: ("belt" if _DT_BELT_RE.search(str(v)) else "chain")
                   for k, v in dt.items()
                   if k.startswith("drivetrain_") and k != "drivetrain"}
    if len(suffix_type) < 2:
        return
    # this model's drive-train, from its (post-split) configurations
    dtrains = {str(c.get("options", {}).get("drive-train", "")).lower()
               for c in (configs or []) if c.get("options", {}).get("drive-train")}
    if len(dtrains) != 1:
        return
    want = "belt" if _DT_BELT_RE.search(next(iter(dtrains))) else "chain"
    drop = {s for s, t in suffix_type.items() if t != want}
    keep = next((s for s, t in suffix_type.items() if t == want), None)
    if not drop or not keep:
        return
    for k in list(dt):
        if any(k.endswith("_" + s) for s in drop):
            del dt[k]
    # collapse the ambiguous bare "drivetrain" row to the kept config's value
    if f"drivetrain_{keep}" in dt:
        dt["drivetrain"] = dt[f"drivetrain_{keep}"]


def _style_bucket(s: str) -> str | None:
    """Coarse frame-style bucket for matching a rider-height dict key to a model's
    frame style. Ride1Up codes its frame tabs ST (step-thru) / XR (high-step)."""
    s = (s or "").strip().lower()
    if s == "st" or "thru" in s or "mid-step" in s or "mid step" in s:  # mid-step -> thru bucket
        return "thru"
    if s in ("xr", "hs") or "over" in s or "high" in s or "diamond" in s:
        return "over"
    return None


def _collapse_rider_height(grouped: dict, frame_style: str) -> None:
    """A geometry rider-height value can arrive as a per-frame dict. Collapse it to
    a single string so it never displays as a bundled "ST: … · XR: …" blob:
      - keyed by FRAME STYLE (ST/XR on a style-split model): keep this model's own
        style's range;
      - keyed by SIZE (SM/MD/LG…) or a single variant: reduce to the overall
        rider-height envelope (the per-size detail is shown via frame_sizes)."""
    geo = grouped.get("geometry")
    if not isinstance(geo, dict):
        return
    key = next((k for k in geo if "rider" in k.lower() and "height" in k.lower()), None)
    if not key or not isinstance(geo[key], dict):
        return
    val = geo[key]
    if len(val) > 1:
        bucket = _style_bucket(frame_style)
        if bucket:
            for dk, dv in val.items():
                if _style_bucket(dk) == bucket:
                    geo[key] = dv
                    return
    if len(val) == 1:
        geo[key] = next(iter(val.values()))
        return
    r = height_range_in(val)
    if r:
        fmt = lambda i: f"{int(i) // 12}'{int(i) % 12}\""
        geo[key] = f"{fmt(r[0])} - {fmt(r[1])}"


def _collapse_geometry_by_frame(grouped: dict, frame_style: str) -> None:
    """On a frame-style-split card, any spec row that bundles both frames' figures
    in one labeled string ("DIAMOND: 18\" | STEP-THROUGH: 17\"") collapses to THIS
    card's frame style, so each card shows only its own values instead of a smeared
    blob. Scans EVERY group (not just geometry) -- a per-frame "Approx. Height" can
    land under general/special-features too. Only fires when every segment label
    maps to a frame style."""
    if not frame_style:
        return
    for group in grouped.values():
        if not isinstance(group, dict):
            continue
        for k in list(group):
            v = group[k]
            if not isinstance(v, str) or "|" not in v or ":" not in v:
                continue
            segs = []
            for seg in v.split("|"):
                mt = re.match(r"^\s*([^:]+?)\s*:\s*(.+?)\s*$", seg)
                if not mt:
                    segs = []
                    break
                segs.append((mt.group(1).strip(), mt.group(2).strip()))
            if len(segs) < 2:
                continue
            styled = [(frame_style_of(lbl), val) for lbl, val in segs]
            if any(st is None for st, _ in styled):
                continue  # not frame-labeled (e.g. size labels) — leave for the size splitter
            match = next((val for st, val in styled if st == frame_style), None)
            if match is not None:
                group[k] = match
            elif len({val for _, val in styled}) == 1:
                group[k] = styled[0][1]   # both frames share the figure


def _awd_motor_rows(rows: dict, name: str = "") -> None:
    """For an all-wheel-drive (dual-motor) bike, split the motor specs into
    'Front Motor' / 'Rear Motor' rows so the detail page shows both instances
    (the same front/rear treatment brakes get), and drop the now-redundant
    combined 'Motor' row. Mutates the flat label->value spec map in place; a
    no-op for single-motor bikes."""
    motor_keys = [k for k, v in rows.items() if isinstance(v, str) and "motor" in k.lower()]
    if not motor_keys:
        return
    has_front = any(re.match(r"\s*front\s+motor\b", k, re.I) for k in rows)
    has_rear = any(re.match(r"\s*rear\s+motor\b", k, re.I) for k in rows)
    controllers = " ".join(v for k, v in rows.items()
                           if isinstance(v, str) and "controller" in k.lower())
    combined_key = next((k for k in motor_keys if k.strip().lower() == "motor"), None)
    combined = rows.get(combined_key) or " ".join(rows[k] for k in motor_keys)
    # a per-side controller ("Front 18A + Rear 22A") is itself a dual-motor tell
    dual_controller = bool(re.search(r"front\s*\d{1,3}\s*a\b", controllers, re.I)
                           and re.search(r"rear\s*\d{1,3}\s*a\b", controllers, re.I))
    if not ((has_front and has_rear) or dual_controller
            or _AWD_RE.search(f"{combined} {controllers} {name}")):
        return

    # (A) the scraper already provides Front/Rear Motor rows -> drop the summary.
    if has_front and has_rear:
        if combined_key:
            rows.pop(combined_key, None)
        return

    # (B) one combined string names each side's motor ("Rear ... 2000W ... Front ... 1500W").
    rear_seg = re.search(r"rear\b[^.]*?\(?\d{3,4}\s*w[^.]*", combined, re.I)
    front_seg = re.search(r"front\b[^.]*?\(?\d{3,4}\s*w[^.]*", combined, re.I)
    if rear_seg and front_seg:
        rows["Rear Motor"] = rear_seg.group(0).strip()
        rows["Front Motor"] = front_seg.group(0).strip()
        if combined_key:
            rows.pop(combined_key, None)
        return

    # (C) no per-side power published (shared rating) -> carry the system rating on
    # both, differentiated by the per-side controller current where stated.
    fa = re.search(r"front\s*(\d{1,3})\s*a\b", controllers, re.I)
    ra = re.search(r"rear\s*(\d{1,3})\s*a\b", controllers, re.I)
    base = combined.strip() or "Hub motor"
    rows["Front Motor"] = base + (f"; {fa.group(1)}A controller" if fa else "")
    rows["Rear Motor"] = base + (f"; {ra.group(1)}A controller" if ra else "")
    if combined_key:
        rows.pop(combined_key, None)


def _frame_style(m: dict, name: str, raw_specs: dict) -> str | None:
    """Step-Thru vs Step-Over (Mid-Step): explicit field from the pipeline, else
    derived from tier/name/option values/frame spec rows via the shared taxonomy.
    Returns None when nothing signals a style, so the caller can fall back to a
    curated override and then the conventional Step-Over default."""
    if m.get("frame_style"):
        return m["frame_style"]
    option_vals = [str(v) for c in m.get("configurations") or []
                   for v in (c.get("options") or {}).values()]
    frame_rows = [str(v) for k, v in (raw_specs.get("all") or {}).items()
                  if "frame" in k.lower() and isinstance(v, str)]
    return pick_frame_style(m.get("tier"), name, *option_vals, *frame_rows)


# Parts that fold without making the bike a folding bike — a folding kickstand,
# pedals, stem, lock, basket, or folding-bead tires are not a folding FRAME.
_FOLD_RED_HERRING = re.compile(
    r"kickstand|pedal|\bstem\b|\block\b|basket|tire|tyre|handlebar|mirror", re.I)


def _is_folding(m: dict, rows: dict) -> bool:
    """True only when the FRAME / whole bike folds (Ride1Up Portola's "Foldable"
    frame, Lectric XP's "foldable: yes" + "bike folded" dimensions), not when an
    accessory merely folds or the tires have folding beads (Specialized Vado)."""
    # raw spec rows + geometry that could describe the bike folding
    sources = list(rows.items()) + list((m.get("geometry") or {}).items())
    for k, v in sources:
        if _FOLD_RED_HERRING.search(k):
            continue
        text = f"{k} {v}".lower()
        if "frame" in k.lower() and re.search(r"fold", text):
            return True
        # whole-bike signals: a "foldable" row, a folded/folding size, time, or
        # dimensions (Tern's "Folding Size"/"Folding Time", Heybike's "Folded
        # Dimensions"), "fully fold", or an explicit folding bike/frame.
        if re.search(r"\bfoldable\b|fully\s*fold"
                     r"|fold(?:ed|ing)?\s*(?:dimension|size|time)"
                     r"|folding\s*(?:frame|e-?bike|bike)", text):
            return True
    return False


def _folding(m: dict, rows: dict, name: str) -> bool:
    """Whether the bike folds — the `folding` FEATURE flag. True when the frame/whole
    bike folds (_is_folding) OR the brand names/tags/url it a folder (the name signal the
    old "Folding" product type relied on, so name-only folders like "Velotric Fold 1"
    aren't lost). \\bfold matches fold/folding/foldable but not unrelated substrings."""
    if _is_folding(m, rows):
        return True
    hay = " ".join(str(x) for x in (name, m.get("url") or "", *(m.get("tags") or [])))
    return bool(re.search(r"\bfold", hay, re.I))


# Mirrors the Mountain (eMTB) rule in bike_taxonomy._TYPE_RULES; used to scrub
# unreliable terrain words out of tire model names before classification.
_MTB_TERRAIN = re.compile(
    r"\bmtb\b|\bemtb\b|mountain|enduro|downhill|hard[\s-]?tail"
    r"|full[\s-]?sus|all[\s-]?terrain|off[\s-]?road|\btrail\b|\bdirt\b", re.I)


def _is_mid_drive(rows: dict) -> bool:
    """Mid-drive (vs hub) from the motor spec text -- mirrors analyze._drive_type
    (brand/model-aware: Bosch CX, Shimano EP, Bafang M-series, etc.)."""
    motor = " ".join(str(v) for k, v in rows.items() if re.search(r"motor|drive", k, re.I))
    return is_mid_drive(motor)


def _max_wheel_in(rows: dict):
    """Largest wheel/tire diameter in inches (20-29) from the tire/wheel/rim rows, or
    None. 700c road wheels count as ~28". Also reads the ISO pairing some brands use
    on rim/rim-strip rows ("27.5/650", "29/622") — Trek lists the size only there on
    some bikes. The unit-anchored match still ignores "28mm hook" / "30 rim" noise."""
    text = " ".join(str(v) for k, v in rows.items() if re.search(r"tire|tyre|wheel|rim", k, re.I))
    dias = [float(x) for x in re.findall(
        r"\b(2\d(?:\.\d)?)\s*(?:[\"”]|in\b|inch|×|x|\*|/\s*\d{3}\b)", text, re.I)]
    if re.search(r"\b700\s*c\b", text, re.I):
        dias.append(28.0)
    return max(dias) if dias else None


def _emtb_qualifies(rows: dict) -> bool:
    """An eMTB must be a mid-drive on >= 27.5" wheels."""
    w = _max_wheel_in(rows)
    return _is_mid_drive(rows) and w is not None and w >= 27.5


def _fork_travel_mm(rows: dict) -> int:
    """Largest front-fork travel (mm) from the raw fork spec rows, else 0. Used to
    tell a trail-grade suspension fork (>=120mm) from a commuter/comfort one."""
    best = 0
    for k, v in rows.items():
        if not isinstance(v, str):
            continue
        if "fork" in k.lower() or "fork" in v.lower():
            for n in re.findall(r"(\d{2,3})\s*mm", v):
                if 60 <= int(n) <= 220:
                    best = max(best, int(n))
    return best


# A bike the brand explicitly names as one of these is NOT an eMTB, even with a
# mid-drive + big wheel + long fork (e.g. Himiway "A7 Pro Commuter" -- a 27.5"
# mid-drive with a 120mm fork but street Super Moto-X tires). Blocks structural
# eMTB promotion; a real eMTB never carries these words.
_NOT_EMTB_NAME = re.compile(
    r"commuter|urban|\bcity\b|cargo|trike|moped|touring|cruiser|\bgravel\b|\broad\b"
    r"|hybrid|fitness|step[-\s]?thr", re.I)

# Unambiguous "the brand calls this a mountain bike" terms. When one of these is in
# the name/tags/vendor type, the eMTB label STAYS even if the bike doesn't meet the
# structural definition (mid-drive + big wheels) -- a brand may label its own model
# an eMTB. Deliberately excludes "full suspension" / "all-terrain" / "trail" / "dirt"
# / "off-road": those ride on fat cruisers and tire tread names, so they still need
# the structural gate to qualify.
_EMTB_STRONG = re.compile(r"\bmtb\b|\bemtb\b|mountain|enduro|downhill|hard[\s-]?tail"
                          r"|\blevo\b|\bkenevo\b", re.I)


def _product_types(m: dict, name: str, raw_specs: dict) -> list[str]:
    """Vendor product_type strings are marketing junk; classify onto the shared
    taxonomy (every matching label, primary first) from the name + scraper
    types + vendor type + tire spec + vendor category option + tags + url."""
    rows = raw_specs.get("all") or {}
    # strip folding-bead wording so folding tires don't read as a folding bike
    tires = " ".join(str(v) for k, v in rows.items()
                     if "tire" in k.lower() and isinstance(v, str))
    tires = re.sub(r"fold\w*", " ", tires, flags=re.I)
    # Tire MODEL NAMES carry use-category words — terrain ("Continental Terra
    # Trail", "All Terrain Gravel Tire") that falsely read as eMTB, and "Urban
    # Hybrid"/"Fitness" tread names that falsely read as Hybrid / Fitness (e.g.
    # ENGWE L20 3.0's "Urban Hybrid Tires"). Drop those keywords from the tire
    # text; the tire still contributes fat-tire width and legit "gravel". A real
    # eMTB / hybrid carries that signal in its name/tags, not the tire tread name.
    tires = _MTB_TERRAIN.sub(" ", tires)
    tires = re.sub(r"hybrid|fitness", " ", tires, flags=re.I)
    # NB folding is a FEATURE (the `folding` boolean), not a use category — it is no
    # longer fed to the classifier, so a folding bike keeps its real type (commuter,
    # fat tire, ...). _is_folding still drives the boolean in the model build below.
    raw_type = " ".join(m.get("product_types") or []) or m.get("product_type") or ""
    tags = " ".join(str(t) for t in (m.get("tags") or []))
    # explicit vendor category options (e.g. Ride1Up's bike_type = "Gravel")
    options = m.get("options") or {}
    opt_types = " ".join(
        str(v) for k, vals in options.items()
        if isinstance(vals, list) and ("type" in k.lower() or "categor" in k.lower())
        for v in vals)
    extra = " ".join(t for t in (m.get("vehicle_type"), m.get("url"),
                                 tires, opt_types, tags) if t)
    types = classify_product_types(name or "", raw_type, extra)
    # eMTB is reserved for a mid-drive on >= 27.5" wheels; demote keyword matches
    # that don't qualify (hub-drive "all-terrain"/fat bikes, small-wheel bikes) --
    # UNLESS the brand unambiguously names it a mountain bike (_EMTB_STRONG in the
    # model NAME), in which case the brand's label wins and the eMTB tag stays. Only
    # the name counts here -- vendor tags/collections file fat cruisers under broad
    # "Mountain"/"All-Terrain" buckets and would over-promote.
    if ("Mountain (eMTB)" in types and not _emtb_qualifies(rows)
            and not _EMTB_STRONG.search(name or "")):
        types = [t for t in types if t != "Mountain (eMTB)"] or ["Commuter / Urban"]
    # Structural promotion: a mid-drive on >= 27.5" wheels with a trail-grade
    # suspension fork (>= 120mm) is an eMTB even when the name/tags/description
    # don't say so (e.g. Ride1Up "TrailRush", Cyke "Falcon X" -- glued/keyword-less
    # names whose mountain signal is only in geometry/components). But a bike already
    # carrying a high-confidence non-MTB category (Cargo / Trike) is NOT an eMTB just
    # because it has a suspension fork -- Trek's Fetch+ cargo line runs a 130mm+ fork.
    elif ("Mountain (eMTB)" not in types and _emtb_qualifies(rows)
          and _fork_travel_mm(rows) >= 120
          and not {"Cargo", "Trike"} & set(types)
          and not _NOT_EMTB_NAME.search(name or "")):
        types = ["Mountain (eMTB)"] + [t for t in types if t != "Commuter / Urban"]
    # "Cargo" is a high-confidence category: require an explicit cargo word in the
    # name or raw signals (tags / url / vendor category / tires), never solely the
    # prior product_types label fed back into the classifier. This strips spurious
    # Cargo (stale fed-back labels, trikes, mislabeled step-thrus) while keeping
    # genuinely-named cargo bikes (Abound, XPedition, Packa Genie, Cargowagen, …).
    # NB checks name + `extra` (not generic spec rows, where "cargo capacity" would
    # false-positive, and not the echoed label).
    if "Cargo" in types and not re.search(
            r"cargo|\bhaul|utility|long[\s-]?tail|xpedition", f"{name or ''} {extra}", re.I):
        types = [t for t in types if t != "Cargo"] or ["Commuter / Urban"]
    # ONE type per e-bike (deliberate simplification): keep only the MOST-SPECIFIC
    # label. A bike that's both Cargo and Commuter is just "Cargo"; the multi-label
    # set was dropped to avoid the complexity of a bike living under several types.
    return [primary_type(types)]


def _prices(m: dict, configs: list) -> tuple:
    cp = [c["price"] for c in configs if c.get("price") is not None]
    pr = m.get("price_range") or {}
    if cp:
        lo, hi = min(cp), max(cp)
    elif m.get("price_from") is not None:
        lo = hi = m["price_from"]
    else:
        lo, hi = pr.get("min"), pr.get("max")
    currency = m.get("currency") or pr.get("currency") or "USD"
    return lo, hi, currency


def _configurations(brand: str, m: dict) -> list:
    cfgs = m.get("configurations")
    if cfgs:
        return cfgs
    # Lectric stores per-config data under `configs` (label/price/specs); map the
    # priced part into the canonical shape so every config carries a price.
    out = []
    for c in m.get("configs") or []:
        if c.get("price") is not None:
            out.append({"options": {"configuration": c.get("label")},
                        "price": c.get("price")})
    return out


# Bundled-equipment spec fields -> a canonical accessory name. Only the value-add
# gear a buyer thinks of as "comes with it" (not standard small parts like
# kickstand/bell). Many scrapers list these only as descriptive spec strings
# rather than in free_accessories, so we derive them so every brand's Accessories
# card is populated, not just the ones whose scraper builds free_accessories.
_ACC_SPEC_MAP = [
    ("Fenders",      re.compile(r"^fenders?(?:_|\b)")),
    ("Front Rack",   re.compile(r"^front_rack")),
    ("Rear Rack",    re.compile(r"^(?:rear_)?rack(?:_|\b)")),
    ("Lights",       re.compile(r"^(?:head_?light|tail_?light|lights?)(?:_|\b)")),
    ("Turn Signals", re.compile(r"^turn_?signals?")),
    ("Basket",       re.compile(r"^basket(?:_|\b)")),
    ("Phone Mount",  re.compile(r"^phone_?mount")),
]
# Value indicates the item is NOT bundled (absent, optional, or a paid add-on).
_ACC_NEG_VAL = re.compile(
    r"^\s*(?:n/?a|none|no\b|not\s+(?:included|available|equipped|standard)|optional|"
    r"\$|tbd|—|–|-|\bsold separately\b)", re.I)


def _included_from_specs(m: dict) -> list:
    """Bundled gear derived from descriptive spec rows (fenders/rack/lights/...),
    for scrapers that don't emit free_accessories. Deduped to canonical names;
    skips rows whose value says optional/absent/priced (a paid add-on)."""
    allspecs = (m.get("specs") or {}).get("all") or {}
    found = {}
    for k, v in allspecs.items():
        if not isinstance(v, str) or not v.strip() or _ACC_NEG_VAL.match(v):
            continue
        if re.search(r"\b(optional|sold separately|separate purchase|additional purchase)\b", v, re.I):
            continue
        kl = k.lower().replace(" ", "_")
        for name, pat in _ACC_SPEC_MAP:
            if pat.match(kl):
                found.setdefault(name, {"name": name, "price": 0})
                break
    return list(found.values())


def _included_accessories(m: dict) -> list:
    """The $0 items bundled with the bike: per-model free_accessories, any
    Lectric-style accessories.included, plus gear inferred from spec rows.
    Deduped by name (explicit free_accessories win over spec-derived)."""
    src = list(m.get("free_accessories") or [])
    src += ((m.get("accessories") or {}).get("included")) or []
    src += _included_from_specs(m)
    out, seen = [], set()
    for a in src:
        n = a.get("name")
        if n and n not in seen:
            seen.add(n)
            out.append({"name": n, "price": a.get("price", 0) or 0})
    return out


def _pricing(m: dict, price: float | None) -> dict:
    """Discount info from a regular/compare-at price (set by add_pricing.py)."""
    regular = m.get("regular_price")
    on_sale = (regular is not None and price is not None and regular > price)
    return {
        "price": price,
        "regular_price": regular if on_sale else None,
        "on_sale": on_sale,
        "discount_amount": round(regular - price, 2) if on_sale else None,
        "discount_pct": round((regular - price) / regular * 100) if on_sale else None,
    }


def _merge_scraped_availability(av: dict, m: dict | None) -> dict:
    """Fold a scraper-provided `sold_out_options` (+ optional `in_stock`) into the
    config-derived availability. Custom / non-generic-Shopify scrapers set these
    directly on the model (via scraper_common.shopify_sold_out_options or their own
    platform's stock signal) since they don't feed `configurations` to add_configurations."""
    if not m:
        return av
    so = m.get("sold_out_options")
    ins = m.get("in_stock")
    if not so and ins is None:
        return av
    merged = {k: list(v) for k, v in (av.get("sold_out_options") or {}).items()}
    for axis, vals in (so or {}).items():
        merged[axis] = sorted(set(merged.get(axis, [])) | set(vals))
    status = av.get("status")
    in_stock = av.get("in_stock")
    if status == "unknown":                              # no config flags -> use the scraped signal
        in_stock = True if ins is None else bool(ins)
        status = "in_stock" if in_stock else "sold_out"
    return {"status": status, "in_stock": in_stock, "sold_out_options": merged}


def _availability(configs: list, m: dict | None = None) -> dict:
    """Summarize stock from per-configuration `available` flags.

    status: "in_stock" (some config available), "sold_out" (all configs
    unavailable), or "unknown" (the scraper didn't report availability).
    `sold_out_options` groups the unavailable configs' option values by axis
    (Color / Frame / Size / ...) so the UI can say which colors/sizes are out
    even when the model overall is buyable. An option value is only listed when
    EVERY config carrying it is unavailable (a color sold out in one size but
    fine in another is still orderable, so not flagged). A scraper-provided
    `sold_out_options`/`in_stock` on `m` is merged in (custom scrapers)."""
    flags = [c.get("available") for c in configs
             if isinstance(c, dict) and c.get("available") is not None]
    if not flags:
        return _merge_scraped_availability(
            {"status": "unknown", "in_stock": None, "sold_out_options": {}}, m)
    any_in = any(flags)
    # value -> still available somewhere?  (keyed by "axis::value")
    val_ok: dict = {}
    for c in configs:
        if not isinstance(c, dict) or c.get("available") is None:
            continue
        for axis, val in (c.get("options") or {}).items():
            key = (axis, str(val))
            val_ok[key] = val_ok.get(key, False) or bool(c.get("available"))
    sold_out: dict = {}
    for (axis, val), ok in val_ok.items():
        if not ok:
            sold_out.setdefault(axis, []).append(val)
    for axis in sold_out:
        sold_out[axis] = sorted(dict.fromkeys(sold_out[axis]))
    return _merge_scraped_availability({
        "status": "in_stock" if any_in else "sold_out",
        "in_stock": any_in,
        "sold_out_options": sold_out,
    }, m)


def _cfg_color(c: dict):
    """The color name an entry's configuration selects, or None."""
    for k, v in (c.get("options") or {}).items():
        if k.strip().lower() in ("color", "colour", "colors"):
            return str(v)
    return None


def _resolve_colors(colors: list, configs: list) -> list:
    """Reconcile a model's color list against its configurations.

    After tier expansion an entry's `configurations` are narrowed to its own
    package/frame, so they are the source of truth for which colors (and which
    per-variant photos) belong to this entry. When a config references a color
    the stale `options.colors` doesn't list — e.g. Heybike's Hero step-thru
    sibling, whose colors weren't re-partitioned on the frame split — rebuild
    the list from the configs (keeping hex/swatch from any name match). In the
    common case (colors already match) just prefer each config's own photo."""
    cfg_order, cfg_img = [], {}
    for c in configs or []:
        nm = _cfg_color(c)
        if nm and nm not in cfg_img:
            cfg_order.append(nm)
            cfg_img[nm] = c.get("image")
    if not cfg_order:
        return colors
    by_name = {c.get("name"): c for c in colors}
    if not set(cfg_order).issubset(by_name):
        # stale color list — rebuild it from the configs
        return [{"name": nm,
                 "hex": by_name.get(nm, {}).get("hex"),
                 "swatch_image": by_name.get(nm, {}).get("swatch_image"),
                 "image": cfg_img.get(nm) or by_name.get(nm, {}).get("image")}
                for nm in cfg_order]
    # colors match the configs — keep them, just prefer each config's own photo
    return [{**c, "image": cfg_img.get(c.get("name")) or c.get("image")}
            for c in colors]


# ENGWE-style single/dual battery spec rows: several redundant per-version rows and
# a combined-capacity row, with no clean "Battery" row — so no battery component is
# parsed and a battery-split card can't tell which pack it ships.
_BATT_VER_KEY = re.compile(r"(?:single|dual|\d+\s*ah)[\s_-]*batter\w*[\s_-]*version"
                           r"|batter\w*[\s_-]*version", re.I)
_BATT_CAP_KEY = re.compile(r"^\s*battery\s*capacity\s*$", re.I)
_WH_VAH = re.compile(r"(\d+(?:\.\d+)?)\s*wh\s*\(\s*(\d+(?:\.\d+)?)\s*v\s*[,\s]*"
                     r"(\d+(?:\.\d+)?)\s*ah", re.I)


# Detail-driven backfill of predefined component fields, run AFTER group_specs so it
# applies uniformly whether a component was freshly parsed or arrived pre-parsed from the
# scrape. Only fills a field when it's empty — never overwrites the primary parse.
_BELT_RE = re.compile(r"gates|carbon\s*drive|\bcd[xn]\b|center\s?track|\bbelt\b", re.I)
_THRU_AXLE_RE = re.compile(r"thru[\s-]?axle|\b(?:12|15|20)\s*[x×]\s*\d{2,3}\b|\bboost\b", re.I)


# Some brands' geometry tables prefix every VALUE with the column header / model name
# (Ride1Up Portola: "Portola: 59lbs", "Portola: 38.2in"). Strip a leading "<label>: "
# when a measurement (a digit) follows, so the value is just the figure.
_GEO_LABEL_PREFIX = re.compile(r"^[A-Za-z][A-Za-z .&'/+-]{0,30}:\s*")


def _strip_geo_label_prefix(geo: dict) -> None:
    def fix(s):
        m = _GEO_LABEL_PREFIX.match(s)
        return s[m.end():].strip() if m and re.search(r"\d", s[m.end():]) else s
    for k, v in list((geo or {}).items()):
        if isinstance(v, str):
            geo[k] = fix(v)
        elif isinstance(v, dict):
            for kk, vv in list(v.items()):
                if isinstance(vv, str):
                    v[kk] = fix(vv)


def _backfill_component_fields(grouped: dict) -> None:
    for group in (grouped or {}).values():
        if not isinstance(group, dict):
            continue
        for c in group.values():
            if not isinstance(c, dict) or not c.get("_kind"):
                continue
            kind = c["_kind"]
            txt = " ".join(str(c.get(k) or "") for k in ("manufacturer", "model", "details"))
            # the drive can be a roller chain OR a (carbon) belt — record which.
            if kind == "chain" and not c.get("type"):
                c["type"] = "belt" if _BELT_RE.search(txt) else "chain"
            # a fork stating a thru-axle dimension (12x148, 15x110, Boost) IS a thru-axle.
            elif kind == "fork" and c.get("thru_axle") is not True and _THRU_AXLE_RE.search(txt):
                c["thru_axle"] = True


# Heybike's Mars 2.0 family states the motor PER VERSION — either only in the tier label
# ("750W (Peak 1400W)" / "1000W (Peak 1800W)") or in one multi-version "Hub rear" row
# ("750W Version: 80Nm torque, … 1400W (peak) 1000W Version: 100Nm torque, … 1800W
# (peak)") — and never as a plain Motor row, so nominal/peak/torque don't parse for the
# right variant. Using the tier's nominal, pull THIS variant's block out of the
# multi-version row (keeping its torque) and emit one clean Motor row; if there's no such
# row, synthesize from the tier label. Gated to heybike (hub — its mid-drives, e.g. the
# Alpha, already carry their own Motor row and never reach here).
_TIER_MOTOR_RE = re.compile(r"(\d{3,4})\s*W\s*\(\s*Peak\s*(\d{3,4})\s*W\s*\)", re.I)
_VER_MOTOR_KEY = re.compile(r"\d{3,4}\s*W\s*Version\s*:", re.I)


def _synth_motor_from_tier(rows: dict, tier, brand: str | None) -> None:
    if brand != "heybike" or any(k.lower() == "motor" for k in rows):
        return
    ver_key = next((k for k, v in rows.items()
                    if isinstance(v, str) and _VER_MOTOR_KEY.search(v)), None)
    mt = _TIER_MOTOR_RE.search(str(tier or ""))
    if ver_key:
        # choose this variant's nominal from the tier label, else the LOWEST version
        # (the untiered base card defaults to its cheapest motor option)
        if mt:
            nominal = mt.group(1)
        else:
            ws = sorted(int(w) for w in re.findall(r"(\d{3,4})\s*W\s*Version", rows[ver_key], re.I))
            nominal = str(ws[0]) if ws else None
        blk = (re.search(rf"{nominal}\s*W\s*Version\s*:(.*?)(?={_VER_MOTOR_KEY.pattern}|$)",
                         rows[ver_key], re.I | re.S) if nominal else None)
        del rows[ver_key]
        if blk:
            b = blk.group(1)
            pk = re.search(r"(\d{3,4})\s*W\s*\(\s*peak", b, re.I)
            tq = re.search(r"(\d{2,3})\s*N", b)
            rows["Motor"] = (f"{nominal}W Hub Motor"
                             + (f" (Peak {pk.group(1)}W)" if pk else "")
                             + (f", {tq.group(1)}Nm torque" if tq else ""))
    elif mt:   # no multi-version row, motor stated only in the tier label
        rows["Motor"] = f"{mt.group(1)}W Hub Motor (Peak {mt.group(2)}W)"


# A bike sold in Single- vs Dual-battery TIERS (Blix Packa Genie) lists the dual capacity
# in ONE Battery row ("672Wh (48V) 1st battery, front 672Wh (48V) 2nd battery, rear"), so
# the SINGLE tier wrongly parses as dual (pack_count 2, 1344Wh). When the tier ships one
# pack, trim the row to the first battery's capacity so it parses as a single 672Wh pack.
_BATT_DUAL_DESC = re.compile(r"2nd\s+battery|second\s+battery|\bdual\b|\+\s*\d{3,4}\s*wh", re.I)
_BATT_FIRST_CAP = re.compile(r"\s*(\d{3,4}(?:\.\d+)?\s*wh(?:\s*\(\s*\d+\s*v\s*\))?)", re.I)


def _resolve_single_battery_tier(rows: dict, tier) -> None:
    if not tier or "single" not in str(tier).lower():
        return
    bk = next((k for k in rows if k.lower() == "battery"), None)
    if not bk or not isinstance(rows[bk], str) or not _BATT_DUAL_DESC.search(rows[bk]):
        return
    m = _BATT_FIRST_CAP.match(rows[bk])
    if m:
        rows[bk] = m.group(1)


def _resolve_belt_tier(rows: dict, tier) -> None:
    """The "belt" drivetrain VARIANT (Ride1Up Roadster V3) inherits the geared variants'
    scraped chain spec ("9-speed chain" + a derailleur), so it reads as a derailleur bike
    and the belt is never detected or valued. When the tier IS the belt option, drop the
    derailleur and swap the drivetrain for a (single-speed) Gates belt."""
    if not tier or not re.fullmatch(r"\s*belt(?:\s*drive)?\s*", str(tier), re.I):
        return
    # a single-speed belt has no derailleur/shifter/cassette and no multi-speed chain — drop
    # all of those geared rows, then add ONE clean belt drivetrain row.
    drop = ("derailleur", "shifter", "cassette", "freewheel", "drivetrain",
            "gearing", "transmission")
    for k in [k for k in rows if any(t in k.lower() for t in drop)]:
        del rows[k]
    rows["Drivetrain"] = "Gates belt drive, single-speed"


def _consolidate_battery_versions(rows: dict, tier, name: str = "") -> None:
    """Collapse redundant per-version battery rows into one canonical "Battery" row
    for THIS battery tier's pack, so a clean battery component is parsed and the
    single/dual card reports its own capacity. Only fires when per-version rows are
    present (the ENGWE M20 family), so ordinary "Battery Capacity" rows are untouched.

    Packs are gathered as (total_wh, volts, total_ah) from a combined-capacity row
    ("1200Wh (60V 20Ah) 2400Wh (60V 40Ah)") AND from each per-version row, where the
    pack count comes from a "*N"/"xN" suffix ("48V13Ah ... *2" => 2 x 13Ah at 48V).
    The smallest pack is the single-battery card, the largest the dual."""
    ver_keys = [k for k in rows if _BATT_VER_KEY.search(k)]
    if not ver_keys:
        return
    cap_keys = [k for k in rows if _BATT_CAP_KEY.search(k)]
    packs = {(float(wh), float(v), float(ah))
             for ck in cap_keys for wh, v, ah in _WH_VAH.findall(str(rows[ck]))}
    for k in ver_keys:
        val = str(rows[k])
        mv, ma = re.search(r"(\d+(?:\.\d+)?)\s*v", val, re.I), re.search(r"(\d+(?:\.\d+)?)\s*ah", val, re.I)
        if mv and ma:
            v, ah = float(mv.group(1)), float(ma.group(1))
            n = int(m.group(1)) if (m := re.search(r"[x*]\s*(\d+)", val)) else 1
            packs.add((round(v * ah * n, 1), v, round(ah * n, 1)))
    is_dual = "dual" in f"{tier or ''} {name}".lower()
    ordered = sorted(packs)
    if ordered:
        wh, v, ah = ordered[-1] if is_dual else ordered[0]
        clean = f"{v:g}V {ah:g}Ah Lithium-Ion Battery, {wh:g}Wh"
    else:                                        # unparseable -> keep a verbatim row
        clean = str(rows[ver_keys[0]])
    for k in ver_keys + cap_keys:
        rows.pop(k, None)
    rows["Battery"] = clean


def normalize_model(brand: str, m: dict) -> dict:
    name = m.get("model") or m.get("title") or m.get("name") or m.get("handle")
    source_id = (m.get("handle") or m.get("slug") or m.get("sku")
                 or slugify(name) or None)
    configs = _configurations(brand, m)
    lo, hi, currency = _prices(m, configs)
    shipping = m.get("shipping") or {}
    options = m.get("options") or {}
    raw_specs = m.get("specs") or {}
    colors = _resolve_colors(options.get("colors") or [], configs)
    # A curated image-inferred override is AUTHORITATIVE (a human verified the photo, so it
    # wins over a scraped/baked or text-derived style); else the text-derived style; else the
    # conventional Step-Over default (every ebike is step-thru or step-over). Keyed brand+source_id.
    frame_style = (FRAME_OVERRIDES.get(f"{brand}__{source_id}")
                   or _frame_style(m, name, raw_specs)
                   or STEP_OVER)
    if frame_style in ("Step-Over (Mid-Step)",):   # collapse legacy labels baked in old data
        frame_style = STEP_OVER
    elif frame_style in ("Step-Thru (Mid-Step)", "Step-Thru"):  # legacy/override -> canonical
        frame_style = STEP_THRU
    variant_options = {k: v for k, v in options.items() if k != "colors"}
    brand_extra = {k: v for k, v in m.items() if k not in _MAPPED}
    if m.get("configs"):
        brand_extra["configs"] = m["configs"]
    # The detailed grouping + component parsing happens here, during normalization,
    # from each scraper's verbatim flat `specs.all`. Geometry becomes one of the
    # groups (`specs.geometry`) — not a separate top-level field.
    _consolidate_battery_versions(raw_specs.get("all") or {}, m.get("tier"), name)
    _resolve_single_battery_tier(raw_specs.get("all") or {}, m.get("tier"))
    _resolve_belt_tier(raw_specs.get("all") or {}, m.get("tier"))
    _awd_motor_rows(raw_specs.get("all") or {}, name)
    _synth_motor_from_tier(raw_specs.get("all") or {}, m.get("tier"), brand)
    _strip_geo_label_prefix(m.get("geometry") or {})
    grouped = group_specs(raw_specs.get("all") or {}, m.get("geometry") or {}, brand)
    _backfill_component_fields(grouped)
    _collapse_rider_height(grouped, frame_style)
    _collapse_geometry_by_frame(grouped, frame_style)
    product_types = _product_types(m, name, raw_specs)
    # per-frame-size chart (enrich/scraper) wins; else derive sizes from a multi-
    # valued "Size" variant option (heights left null when no per-size chart).
    # rider heights read from a size-guide image win for the rider-height gap
    img_h = (IMAGE_HEIGHTS.get(f"{brand}__{source_id}") or {}).get("frame_sizes")
    frame_sizes = img_h or m.get("frame_sizes") or _frame_sizes_from_options(variant_options)
    _split_geometry_by_size(grouped, frame_sizes)
    _narrow_drivetrain_configs(grouped, configs)
    # "Zoom® Stem" -> "Zoom Stem": strip ®/™ from EVERY string in the model (specs,
    # included/free accessories, brand_extra, …), applied once to the whole record.
    return _strip_trademarks({
        "id": f"{brand}__{source_id}",
        "brand": brand,
        "model": name,
        "tier": m.get("tier"),
        "family_id": m.get("family_id"),
        # some Lectric entries only carry their URL on the config (Lectric ONE)
        "url": m.get("url") or next(
            (c.get("url") for c in (m.get("configs") or []) if c.get("url")), None),
        "source_id": source_id,
        "product_type": product_types[0],
        "product_types": product_types,
        # folding is a FEATURE, not a use category: a boolean derived from the frame /
        # whole-bike fold signal + name/tags (drives the "Folds" filter, feature score, chip).
        "folding": _folding(m, raw_specs.get("all") or {}, name),
        "frame_style": frame_style,
        # explicit "new" from a site new-arrival tag (not a catalog-diff guess)
        "is_new": _is_new(m),
        # per-frame-size rider-height chart (enrich_frame_sizes / aventon scraper);
        # bikes without one are a single frame size.
        "frame_sizes": frame_sizes or None,
        "frame_size_count": len(frame_sizes) if frame_sizes else 1,
        "price": lo,
        "price_min": lo,
        "price_max": hi,
        "currency": currency,
        "pricing": _pricing(m, lo),
        "warranty": m.get("warranty"),
        "shipping_free": shipping.get("free"),
        "shipping_cost": shipping.get("cost"),
        "spec_count": m.get("spec_count", 0),
        # Specs as an Aventon-style grouped map (group -> {field: value|parsed
        # component}), snake_case throughout. Geometry is one of the groups.
        "specs": grouped,
        "colors": colors,
        "color_names": [c["name"] for c in colors if c.get("name")],
        "variant_options": variant_options,
        "available_options": m.get("available_options") or [],
        "availability": _availability(configs, m),
        "configurations": configs,
        "free_accessories": m.get("free_accessories") or [],
        "included_accessories": _included_accessories(m),
        "scrape_error": m.get("scrape_error"),
        "brand_extra": brand_extra,
    })


# Brands intentionally excluded from the catalog (their scraped file may still exist, but
# their models are dropped from the combined output). Lowercase brand keys.
EXCLUDE_BRANDS = {"vivi"}


def main():
    models, brands = [], []
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        if f.endswith("_normalized.json"):
            continue
        brand = Path(f).stem.replace("_ebikes", "")
        if brand.lower() in EXCLUDE_BRANDS:
            continue
        d = json.load(open(f))
        brands.append({
            "brand": brand,
            "source": d.get("source"),
            "logo": d.get("logo"),
            "model_count": d.get("model_count"),
            "available_accessories": d.get("available_accessories", []),
        })
        for m in d.get("models", []):
            if m.get("spec_count"):
                models.append(_apply_overrides(normalize_model(brand, m)))

    # Carry "new" across a bike's frame-style siblings: if either the step-thru
    # or the step-over variant is a site-declared new arrival, both are (they're
    # the same bike, linked by family_id).
    new_families = {m["family_id"] for m in models if m.get("family_id") and m.get("is_new")}
    for m in models:
        if m.get("family_id") in new_families:
            m["is_new"] = True

    out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brand_count": len(brands),
        "model_count": len(models),
        "brands": brands,
        "models": models,
    }
    path = DATA / "current" / "active" / "ebike.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    # Light self-check against the required canonical fields.
    required = ("id", "brand", "model", "price", "currency", "specs",
                "colors", "available_options")
    bad = [r["id"] for r in models if any(r.get(k) is None and k != "price" for k in required)]
    print(f"Wrote {path.name}: {len(models)} models from {len(brands)} brands"
          f"{'' if not bad else f' ({len(bad)} missing required fields)'}")


if __name__ == "__main__":
    main()
