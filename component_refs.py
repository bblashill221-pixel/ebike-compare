#!/usr/bin/env python3
"""
Content-addressed component table for ebike.json.

`intern(doc, catalog)` extracts every parsed COMPONENT (a spec value that is a dict
carrying a component `_kind`) into a doc-level `components` table — ONE entry per
content-distinct component — and replaces each `model.specs[group][field]` with the
string key of its entry. Every entry is enriched with `catalog_key` (a link to
component_catalog.json) and `retail_usd` (researched-or-estimated; NEVER null), so a
reference always resolves to a complete, priced component.

Keys are the catalog key (`category|manufacturer|model`) for branded parts, or
`category||<spec_class>` for unbranded ones, with a `#N` suffix appended only when a
base key has more than one content-distinct component (so it stays lossless — the 33
distinct `chain|kmc|` chains become `chain|kmc|#1..#33`). A unique part keeps the plain
key. A few entries will be referenced by a single model (the exception, not the rule);
that's fine — it guarantees safe, consistent access.

`rehydrate(doc)` is the inverse for any consumer that wants inline components back
(restores the original component shape, dropping the table-only annotations). It is a
no-op when `components` is absent, so pipeline scripts can call it defensively right
after loading regardless of whether the file is interned.
"""
from __future__ import annotations

import json
import re

# NB: component_catalog / resolve_component_prices are imported lazily inside intern()'s
# helpers (not at module top) so that component_catalog.py can `from component_refs import
# rehydrate` without a circular import. rehydrate() itself has no heavy dependencies.

# Parsed-dict `_kind`s that are NOT bike components (structures, not parts).
_NON_COMPONENT_KINDS = {"cert", "pedal_assist", None}
# annotations the table adds on top of the original parsed component
_ANNOTATIONS = ("catalog_key", "retail_usd")


def _is_component(v) -> bool:
    return isinstance(v, dict) and "_kind" in v and v.get("_kind") not in _NON_COMPONENT_KINDS


def _attrs(part: dict) -> dict:
    return {k: v for k, v in part.items()
            if k not in ("manufacturer", "model", "details", "_kind") and v not in (None, "")}


def _catalog_key_for(field: str, part: dict) -> str:
    """Branded -> the `category|manufacturer|model` catalog key; unbranded ->
    `category||<spec_class>` (a stable default so the link is never null)."""
    from component_catalog import category_of, spec_class, component_key
    cat = category_of(field)
    man = part.get("manufacturer")
    if man:
        return component_key(cat, man, part.get("model"))
    return f"{cat}||{spec_class(cat, _attrs(part))}"


def _price(catalog_key: str, field: str, part: dict, catalog: dict) -> int:
    """The part's retail price: the catalog's researched/estimated price when the part
    is in the catalog, else the brand/spec estimate. Never null."""
    from component_catalog import category_of, spec_class
    from resolve_component_prices import heuristic_retail, _GENERIC_PART
    e = catalog.get(catalog_key)
    if e:
        r = (e.get("aftermarket") or {}).get("retail_usd")
        if r is not None:
            return r
    cat = category_of(field)
    attrs = _attrs(part)
    val, _ = heuristic_retail({"category": cat, "manufacturer": part.get("manufacturer"),
                               "model": part.get("model"), "attributes": attrs,
                               "spec_class": spec_class(cat, attrs),
                               "sample_details": part.get("details")})
    return int(val) if val is not None else _GENERIC_PART


def _content(part: dict) -> str:
    return json.dumps(part, sort_keys=True, ensure_ascii=False)


# Build a short, READABLE disambiguator from a component's distinguishing specs, so a
# colliding base key gets `..._750w-hub` / `..._720wh-48v` instead of an opaque `#24`.
_DISAMBIG_FMT = {
    "power_w": "{}w", "peak_w": "{}wpk", "torque_nm": "{}nm", "capacity_wh": "{}wh",
    "voltage_v": "{}v", "amphours_ah": "{}ah", "travel_mm": "{}mm", "diameter_mm": "{}mm",
    "diameter_in": "{}in", "width_in": "{}in", "speeds": "{}spd", "gears": "{}spd",
}
# value-only fields (no unit), in slug order
_DISAMBIG_PLAIN = ("model", "placement", "type", "kind", "material", "actuation")


def _slug(s: str, maxlen: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:maxlen].strip("-")


def _disambig(part: dict) -> str:
    """A readable token that distinguishes this component from its same-base-key siblings."""
    bits = []
    for k in _DISAMBIG_PLAIN:
        v = part.get(k)
        if v not in (None, "", False):
            bits.append(str(v))
    for k, fmt in _DISAMBIG_FMT.items():
        v = part.get(k)
        if v not in (None, "", False):
            bits.append(fmt.format(v))
    if not bits and part.get("details"):     # fall back to the human spec text
        bits.append(part["details"])
    return _slug(" ".join(bits)) or "variant"


def _iter_component_fields(doc: dict):
    """Yield (fields_dict, field_name, value) for every component-bearing spec field."""
    for m in doc.get("models", []):
        for group, fields in (m.get("specs") or {}).items():
            if group == "geometry" or not isinstance(fields, dict):
                continue
            for field in list(fields):
                yield fields, field, fields[field]


def intern(doc: dict, catalog: dict) -> dict:
    """Replace inline components with refs into a new doc-level `components` table."""
    if "components" in doc:                      # already interned
        return doc
    # Pass 1: group content-distinct components under their base (un-suffixed) key.
    base_contents: dict[str, dict] = {}          # base_key -> {content: (field, part)}
    for _fields, field, v in _iter_component_fields(doc):
        if _is_component(v):
            bk = _catalog_key_for(field, v)
            base_contents.setdefault(bk, {})[_content(v)] = (field, v)
    # Assign final keys (suffix only when a base key has >1 content) + build the table.
    content_to_key: dict[str, str] = {}
    components: dict[str, dict] = {}
    for bk, contents in base_contents.items():
        items = sorted(contents.items())         # stable: by content
        multi = len(items) > 1
        used: dict[str, int] = {}                # readable-slug -> count (for de-dup)
        for content, (field, part) in items:
            if multi:
                slug = _disambig(part)
                n = used[slug] = used.get(slug, 0) + 1
                key = f"{bk}_{slug}" if n == 1 else f"{bk}_{slug}-{n}"
            else:
                key = bk                          # unique part keeps the plain key
            content_to_key[content] = key
            entry = dict(part)
            entry["catalog_key"] = bk            # link to component_catalog.json
            entry["retail_usd"] = _price(bk, field, part, catalog)
            components[key] = entry
    # Pass 2: rewrite every component spec value to its ref.
    for fields, field, v in _iter_component_fields(doc):
        if _is_component(v):
            fields[field] = content_to_key[_content(v)]
    doc["components"] = components
    return doc


def rehydrate(doc: dict) -> dict:
    """Inverse of intern: put the original inline component back on each spec field.
    No-op if the doc isn't interned. Strips the table-only annotations so the restored
    shape matches the pre-intern component exactly."""
    comps = doc.get("components")
    if not comps:
        return doc
    for m in doc.get("models", []):
        for group, fields in (m.get("specs") or {}).items():
            if not isinstance(fields, dict):
                continue
            for field, v in fields.items():
                if isinstance(v, str) and v in comps:
                    fields[field] = {k: val for k, val in comps[v].items()
                                     if k not in _ANNOTATIONS}
    return doc
