#!/usr/bin/env python3
"""
Shared bike taxonomy used by the scrapers and the pipeline.

Two classifiers live here so every brand maps onto the same vocabulary:

  - classify_product_types(): every matching PRODUCT_TYPES label (vendor
    `product_type` strings are marketing junk — "Zebra", "D5 2.0",
    "Electric_Bicycles"); classify_product_type() is its primary label;
  - frame_style_of() / pick_frame_style(): "Step-Thru" vs "Step-Over
    (Mid-Step)" from option values, config labels, or model names. The site
    filters on these two buckets (low/mid/high-step all read as one of them).

Scrapers should call these when building a model dict; normalize.py applies
them again as a backstop so already-captured data classifies the same way.
"""
import re

# ------------------------------ product type ------------------------------

PRODUCT_TYPES = [
    "Commuter / Urban",
    "Mountain (eMTB)",
    "Road / Gravel",
    "Cargo",
    "Folding",
    "Trike",
    "Cruiser",
    "eMoto",
    "Fat Tire",
    "Hybrid / Fitness",
]

# A bike can belong to several categories ("folding cargo fat bike" is Cargo +
# Folding + Fat tire); rule order ranks the primary label — utility categories
# trump terrain, an explicit "fat" name trumps all-terrain marketing copy, and
# the tire-width fallback only catches fat bikes that never say so.
_TYPE_RULES = [
    # "xpedition": Lectric's cargo line carries no cargo word in name/specs.
    # NB a trike is a wheel configuration, not a use category — a *cargo* trike
    # still matches "cargo"/"hauler"; a plain trike classifies on its other signals.
    ("Cargo", re.compile(r"cargo|long[\s-]?tail|utility|hauler|xpedition", re.I)),
    ("Folding", re.compile(r"fold", re.I)),
    # A trike has 3 wheels — identified by name ("trike"/"tricycle"/"e-trike"/
    # "triker"); no spec carries a wheel count. The (?<!s) keeps "strike" out.
    ("Trike", re.compile(r"(?<!s)trike|tricycle", re.I)),
    # Motorcycle-styled e-bikes (Super73/Sur-Ron/moped-style): the moto identity
    # is more defining than the fat tires they usually ride on, so it outranks
    # Fat tire and the terrain rules. \be-?moto\b matches "moto"/"e-moto" as whole
    # tokens only — it must NOT fire on "motor", "motorcycle"(below), or the
    # "Cemoto" brand, so motorcycle/motorbike are spelled out separately.
    ("eMoto", re.compile(
        r"\be-?moto\b|motorcycle|motor[\s-]?bike|moped|scrambler|chopper|harley"
        r"|dirt[\s-]?bike|caf[eé][\s-]?racer", re.I)),
    ("Fat Tire", re.compile(r"\bfat\b", re.I)),
    ("Mountain (eMTB)", re.compile(
        r"\bmtb\b|\bemtb\b|mountain|enduro|downhill|hard[\s-]?tail"
        r"|full[\s-]?sus|all[\s-]?terrain|off[\s-]?road|\btrail\b|\bdirt\b", re.I)),
    ("Road / Gravel", re.compile(r"\broad\b|gravel|\bracer\b|all[\s-]?road", re.I)),
    ("Cruiser", re.compile(r"cruiser|beach", re.I)),
    ("Hybrid / Fitness", re.compile(r"hybrid|fitness", re.I)),
    ("Fat Tire", re.compile(r"[2-9]\d?\s*[\"”']?\s*[x×]\s*4(?:\.\d)?\b", re.I)),
    # NB: no step-thru pattern here — that's a frame style, not a use category,
    # and step-thru-with-no-other-signal already lands here via the fallback.
    ("Commuter / Urban", re.compile(r"commut|urban|city", re.I)),
]


def classify_product_types(name: str, raw_type: str = "", extra_text: str = "") -> list[str]:
    """Map a bike onto every matching PRODUCT_TYPES label (primary first) from
    its name, the vendor's product_type, and any extra text worth scanning
    (tags, tire spec, description)."""
    text = " ".join(t for t in (name, raw_type, extra_text) if t)
    labels = []
    for label, rx in _TYPE_RULES:
        if label not in labels and rx.search(text):
            labels.append(label)
    return labels or ["Commuter / Urban"]


def classify_product_type(name: str, raw_type: str = "", extra_text: str = "") -> str:
    """The primary (highest-ranked) label from classify_product_types()."""
    return classify_product_types(name, raw_type, extra_text)[0]


# ------------------------------ frame style ------------------------------

STEP_THRU = "Step-Thru"
STEP_OVER = "Step-Over (Mid-Step)"
FRAME_STYLES = [STEP_THRU, STEP_OVER]

# Bare "ST"/"XR" are brand shorthands (Ride1Up, Velowave "Asphalt ST",
# Himiway "D3 ST"); matched only as standalone tokens.
_THRU = re.compile(r"step[\s_-]?thr(u|ough)|low[\s_-]?step|easy[\s_-]?entry|\bst\b", re.I)
_THRU_GLUED = re.compile(r"(?<=[a-z])ST\b")  # camel-glued shorthand: "CruiserST"
_OVER = re.compile(r"step[\s_-]?over|high[\s_-]?step|mid[\s_-]?step|\bxr\b|\bhs\b", re.I)


def frame_style_of(text) -> str | None:
    """Bucket a single option value / label / name, or None when it carries
    no frame-style signal."""
    t = str(text or "")
    if _THRU.search(t) or _THRU_GLUED.search(t):
        return STEP_THRU
    if _OVER.search(t):
        return STEP_OVER
    return None


def pick_frame_style(*texts) -> str | None:
    """First frame-style signal across several candidate strings."""
    for t in texts:
        b = frame_style_of(t)
        if b:
            return b
    return None
