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

from spec_groups import group_specs


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")

HERE = Path(__file__).parent
DATA = HERE / "data"
SCHEMA_VERSION = "1.0"

# Raw model keys that map onto canonical fields (everything else -> brand_extra).
_MAPPED = {
    "model", "title", "name", "handle", "slug", "sku", "id", "url", "product_type",
    "price_from", "price_range", "currency", "warranty", "shipping", "specs",
    "spec_count", "geometry", "options", "available_options", "configurations",
    "free_accessories", "scrape_error", "configs", "regular_price",
    "compare_at_price", "accessories", "tier", "family_id",
}


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


def normalize_model(brand: str, m: dict) -> dict:
    name = m.get("model") or m.get("title") or m.get("name") or m.get("handle")
    source_id = (m.get("handle") or m.get("slug") or m.get("sku")
                 or slugify(name) or None)
    configs = _configurations(brand, m)
    lo, hi, currency = _prices(m, configs)
    shipping = m.get("shipping") or {}
    options = m.get("options") or {}
    colors = options.get("colors") or []
    variant_options = {k: v for k, v in options.items() if k != "colors"}
    brand_extra = {k: v for k, v in m.items() if k not in _MAPPED}
    if m.get("configs"):
        brand_extra["configs"] = m["configs"]
    raw_specs = m.get("specs") or {}
    # The detailed grouping + component parsing happens here, during normalization,
    # from each scraper's verbatim flat `specs.all`. Geometry becomes one of the
    # groups (`specs.geometry`) — not a separate top-level field.
    grouped = group_specs(raw_specs.get("all") or {}, m.get("geometry") or {}, brand)
    return {
        "id": f"{brand}__{source_id}",
        "brand": brand,
        "model": name,
        "tier": m.get("tier"),
        "family_id": m.get("family_id"),
        "url": m.get("url"),
        "source_id": source_id,
        "product_type": m.get("product_type"),
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
                models.append(normalize_model(brand, m))

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
