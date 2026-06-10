#!/usr/bin/env python3
"""
Normalize all per-brand *_ebikes.json into one combined, snake_case JSON that
adheres to a common schema: `ebikes_normalized.json`.

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

from bike_taxonomy import classify_product_types, pick_frame_style

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
    Records the touched fields under `curated_overrides` for transparency."""
    ov = MODEL_OVERRIDES.get(nm.get("id"))
    if ov:
        for k, v in ov.items():
            nm[k] = v
        nm["curated_overrides"] = sorted(ov.keys())
    return nm
from spec_groups import group_specs


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


def _frame_style(m: dict, name: str, raw_specs: dict) -> str | None:
    """Step-Thru vs Step-Over (Mid-Step): explicit field from the pipeline, else
    derived from tier/name/option values/frame spec rows via the shared taxonomy."""
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


# Mirrors the Mountain (eMTB) rule in bike_taxonomy._TYPE_RULES; used to scrub
# unreliable terrain words out of tire model names before classification.
_MTB_TERRAIN = re.compile(
    r"\bmtb\b|\bemtb\b|mountain|enduro|downhill|hard[\s-]?tail"
    r"|full[\s-]?sus|all[\s-]?terrain|off[\s-]?road|\btrail\b|\bdirt\b", re.I)


def _is_mid_drive(rows: dict) -> bool:
    """Mid-drive (vs hub) from the motor spec text -- mirrors analyze._drive_type."""
    motor = " ".join(str(v) for k, v in rows.items() if re.search(r"motor|drive", k, re.I))
    return bool(re.search(r"mid[\s-]?drive|mid[\s-]?motor|bottom bracket", motor, re.I))


def _max_wheel_in(rows: dict):
    """Largest wheel/tire diameter in inches (20-29) from the tire/wheel rows, or
    None. 700c road wheels count as ~28"."""
    text = " ".join(str(v) for k, v in rows.items() if re.search(r"tire|tyre|wheel", k, re.I))
    dias = [float(x) for x in re.findall(
        r"\b(2\d(?:\.\d)?)\s*(?:[\"”]|in\b|inch|×|x|\*)", text, re.I)]
    if re.search(r"\b700\s*c\b", text, re.I):
        dias.append(28.0)
    return max(dias) if dias else None


def _emtb_qualifies(rows: dict) -> bool:
    """An eMTB must be a mid-drive on >= 27.5" wheels."""
    w = _max_wheel_in(rows)
    return _is_mid_drive(rows) and w is not None and w >= 27.5


def _product_types(m: dict, name: str, raw_specs: dict) -> list[str]:
    """Vendor product_type strings are marketing junk; classify onto the shared
    taxonomy (every matching label, primary first) from the name + scraper
    types + vendor type + tire spec + vendor category option + tags + url."""
    rows = raw_specs.get("all") or {}
    # strip folding-bead wording so folding tires don't read as a folding bike
    tires = " ".join(str(v) for k, v in rows.items()
                     if "tire" in k.lower() and isinstance(v, str))
    tires = re.sub(r"fold\w*", " ", tires, flags=re.I)
    # Tire MODEL NAMES carry terrain words ("Continental Terra Trail", "All
    # Terrain Gravel Tire") that falsely read as eMTB; drop the Mountain-rule
    # keywords from the tire text. The tire still contributes fat-tire width and
    # legit "gravel". A real eMTB carries its mountain signal in name/tags.
    tires = _MTB_TERRAIN.sub(" ", tires)
    folds = "folding frame" if _is_folding(m, rows) else ""
    raw_type = " ".join(m.get("product_types") or []) or m.get("product_type") or ""
    tags = " ".join(str(t) for t in (m.get("tags") or []))
    # explicit vendor category options (e.g. Ride1Up's bike_type = "Gravel")
    options = m.get("options") or {}
    opt_types = " ".join(
        str(v) for k, vals in options.items()
        if isinstance(vals, list) and ("type" in k.lower() or "categor" in k.lower())
        for v in vals)
    extra = " ".join(t for t in (m.get("vehicle_type"), m.get("url"), folds,
                                 tires, opt_types, tags) if t)
    types = classify_product_types(name or "", raw_type, extra)
    # eMTB is reserved for a mid-drive on >= 27.5" wheels; demote keyword matches
    # that don't qualify (hub-drive "all-terrain"/fat bikes, small-wheel bikes).
    if "Mountain (eMTB)" in types and not _emtb_qualifies(rows):
        types = [t for t in types if t != "Mountain (eMTB)"] or ["Commuter / Urban"]
    return types


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


def _included_accessories(m: dict) -> list:
    """The $0 items bundled with the bike: per-model free_accessories plus any
    Lectric-style accessories.included. Deduped by name."""
    src = list(m.get("free_accessories") or [])
    src += ((m.get("accessories") or {}).get("included")) or []
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


def _availability(configs: list) -> dict:
    """Summarize stock from per-configuration `available` flags.

    status: "in_stock" (some config available), "sold_out" (all configs
    unavailable), or "unknown" (the scraper didn't report availability).
    `sold_out_options` groups the unavailable configs' option values by axis
    (Color / Frame / Size / ...) so the UI can say which colors/sizes are out
    even when the model overall is buyable. An option value is only listed when
    EVERY config carrying it is unavailable (a color sold out in one size but
    fine in another is still orderable, so not flagged)."""
    flags = [c.get("available") for c in configs
             if isinstance(c, dict) and c.get("available") is not None]
    if not flags:
        return {"status": "unknown", "in_stock": None, "sold_out_options": {}}
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
    return {
        "status": "in_stock" if any_in else "sold_out",
        "in_stock": any_in,
        "sold_out_options": sold_out,
    }


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


def normalize_model(brand: str, m: dict) -> dict:
    name = m.get("model") or m.get("title") or m.get("name") or m.get("handle")
    source_id = (m.get("handle") or m.get("slug") or m.get("sku")
                 or slugify(name) or None)
    configs = _configurations(brand, m)
    lo, hi, currency = _prices(m, configs)
    shipping = m.get("shipping") or {}
    options = m.get("options") or {}
    colors = _resolve_colors(options.get("colors") or [], configs)
    variant_options = {k: v for k, v in options.items() if k != "colors"}
    brand_extra = {k: v for k, v in m.items() if k not in _MAPPED}
    if m.get("configs"):
        brand_extra["configs"] = m["configs"]
    raw_specs = m.get("specs") or {}
    # The detailed grouping + component parsing happens here, during normalization,
    # from each scraper's verbatim flat `specs.all`. Geometry becomes one of the
    # groups (`specs.geometry`) — not a separate top-level field.
    grouped = group_specs(raw_specs.get("all") or {}, m.get("geometry") or {}, brand)
    product_types = _product_types(m, name, raw_specs)
    return {
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
        # text-derived style wins; else a curated image-inferred override (for
        # bikes the vendor never labels). Keyed by model id.
        "frame_style": _frame_style(m, name, raw_specs)
        or FRAME_OVERRIDES.get(f"{brand}__{source_id}"),
        # explicit "new" from a site new-arrival tag (not a catalog-diff guess)
        "is_new": _is_new(m),
        # per-frame-size rider-height chart (enrich_frame_sizes / aventon scraper);
        # bikes without one are a single frame size.
        "frame_sizes": m.get("frame_sizes") or None,
        "frame_size_count": len(m["frame_sizes"]) if m.get("frame_sizes") else 1,
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
        "availability": _availability(configs),
        "configurations": configs,
        "free_accessories": m.get("free_accessories") or [],
        "included_accessories": _included_accessories(m),
        "scrape_error": m.get("scrape_error"),
        "brand_extra": brand_extra,
    }


def main():
    models, brands = [], []
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        if f.endswith("_normalized.json"):
            continue
        brand = Path(f).stem.replace("_ebikes", "")
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
    path = DATA / "current" / "active" / "ebikes_normalized.json"
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
