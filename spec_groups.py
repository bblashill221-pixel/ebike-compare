#!/usr/bin/env python3
"""
Canonical e-bike spec grouping, modeled on Aventon's PDP spec sections and
extended with Safety / Certifications / Water Resistance / Special Features.

`group_specs(all_specs, geometry)` reorganizes a model's flat `specs.all` map
into ordered, human-readable groups for the comparison site. The Geometry group
is taken straight from `model.geometry` (the Aventon geometry-data field set built
by add_geometry.py); page-chrome junk labels are dropped.

Used by normalize.py. Classification is case-insensitive substring matching in
**priority order** (first match wins) so specific groups beat broad ones.
"""
import re
from collections import OrderedDict

from parse_components import parse_component, unitize

# Brands write spec labels in wildly different cases ("BATTERY" / "Battery",
# "REAR BRAKE" / "Rear brake"). Normalize every field name to snake_case, to match
# the rest of the snake_case schema. NB: classification still runs on the original
# (spaced) label so multi-word keywords like "pedal assist" keep matching.
def snake(label: str) -> str:
    """Field-name -> snake_case (e.g. 'REAR BRAKE' / 'Rear brake' -> 'rear_brake')."""
    return re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")


_UNIT_SUFFIX = {"_kwh": "kWh", "_wh": "Wh", "_nm": "Nm", "_ah": "Ah",
                "_mm": "mm", "_mph": "mph", "_lb": "lb", "_mi": "mi",
                "_in": "in", "_deg": "deg", "_w": "W", "_v": "V"}


def _stringify(d: dict) -> str:
    """Rebuild a text-ish value from a parsed component dict, re-attaching units so
    the analysis/cost regexes still match (and marking peak watts as 'peak')."""
    parts = []
    for k, v in d.items():
        if k == "details" or v is None:
            continue
        if isinstance(v, bool):
            if v:
                parts.append(k.replace("_", " "))
            continue
        unit = next((u for suf, u in _UNIT_SUFFIX.items() if k.endswith(suf)), "")
        token = f"{v}{unit}"
        if k == "peak_w":
            token += " peak"
        parts.append(token)
    if d.get("details"):
        parts.append(d["details"])
    return " ".join(str(p) for p in parts)


def flatten_grouped(grouped: dict) -> dict:
    """Recover a flat label->value text map from the grouped view (parsed component
    dicts are stringified, re-attaching units; Geometry per-size dicts are skipped).
    Lets the analysis and cost-estimate steps keep working without `specs.all`."""
    out = {}
    for fields in (grouped or {}).values():
        for k, v in fields.items():
            if isinstance(v, str):
                out[k] = v
            elif isinstance(v, dict) and "details" in v:   # parsed component
                out[k] = _stringify(v)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                # unitized scalar (top_speed_mph: 28) -> re-attach unit for regexes
                unit = next((u for suf, u in _UNIT_SUFFIX.items() if k.endswith(suf)), "")
                out[k] = f"{v}{unit}"
    return out


# Page-chrome strings that leaked into the specs but aren't real specs -> dropped.
_JUNK_EXACT = {
    "color", "colors", "color(s)", "free", "free gift", "free gifts",
    "regular price", "sale price", "price", "q", "a", "q:", "a:",
    "shop all e-bikes", "additional", "default",
}
_JUNK_SUBSTR = ("ships within", "out of stock", "add to cart", "shop all",
                "eta:", "in stock")


def _is_junk(low: str) -> bool:
    return (low in _JUNK_EXACT or low.startswith("*")
            or any(s in low for s in _JUNK_SUBSTR))


# (group, keyword substrings) in PRIORITY order — first match wins. Specific
# groups (Certifications, Water Resistance, Special Features, Safety) come before
# the broad component groups so overlaps resolve the way Aventon groups them.
GROUPS = [
    ("Certifications", (
        "certif", "ul 2271", "ul 2849", "ul 2580", "ul2271", "ul2849",
        "ul listed", "iso standard", "din tested", "din rated", "emtb safety",
        "tuv", "tüv", "compliance", "complies with", "gcc")),
    ("Water Resistance", (
        "water resist", "waterproof", "water-resist", "water rating",
        "ip rating", "ipx", "ip67", "ip66", "ip65", "ip64", "ip54",
        "ingress protection")),
    ("Special Features", (
        "regen", "radar", "blind spot", "connectivity", "bluetooth", "gps",
        "anti-theft", "anti theft", "theft", "alarm", "keyless", "fingerprint",
        "walk mode", "walk-mode", "walk assist", "smart", "over-the-air",
        "ota ", "find my", "riding mode", "ride mode", "co-pilot", "auto-shift",
        "auto shift", "navigation", "e-lock", "bike lock", "wheel lock",
        "frame lock", "connect module", "app", "security", "adaptive",
        "traction control", "cloud", "wireless", "digital key", "nfc", "rfid",
        "esim", "self-balancing", "stability control")),
    ("Safety", (
        "headlight", "tail light", "taillight", "rear light", "front light",
        "brake light", "daytime running", "drl", "reflector", "horn", "bell",
        "mirror", "anti-lock", "antilock", "turn signal", "blinker",
        "safety light", "lights", "light")),
    ("Drivetrain", (
        "derailleur", "shifter", "shift lever", "cassette", "freewheel",
        "chainring", "crankset", "crank", "bottom bracket", "pedals", "groupset",
        "gearing", "gearbox", "gear inches", "belt", "sprocket", "drivetrain",
        "transmission", "chainguard", "chain", "speeds", "-speed", "cog")),
    ("Ebike System", (
        "motor", "battery", "cell", "charger", "charging", "display",
        "controller", "throttle", "sensor", "pedal assist", "watt", "voltage",
        "kwh", "ui/remote", "ui ", "remote", "drive unit", "torque", "power",
        "top speed", "max speed", "assist", "wattage", "wiring", "harness",
        "usb", "ecu", "pwr")),
    ("Brakes", ("brake", "rotor", "caliper", "lever")),
    ("Wheelset", (
        "wheel", "rim", "spoke", "tire", "tyre", "tube", "hub", "valve",
        "axle", "nipple")),
    ("Cockpit", (
        "saddle", "seatpost", "seat post", "seat binder", "binder", "clamp",
        "handlebar", "handlepost", "grip", "headset", "stem", "bar tape", "seat")),
    ("Frameset", ("frame", "fork", "suspension", "shock", "spacing")),
    ("Included Accessories", (
        "kickstand", "rack", "fender", "basket", "pump", "storage bag",
        "trunk", "cargo", "mount", "accessor", "luggage", "swat")),
    ("General Info", (
        "model", "ideal use", "generation", "ebike class", "e-bike class",
        "class", "pedal", "weight", "payload", "capacity", "limit",
        "product id", "sku", "warranty", "speed", "fold", "size", "range",
        "length")),
]

# Order groups appear in the output (nice reading order, distinct from match order).
DISPLAY_ORDER = [
    "General Info", "Ebike System", "Special Features", "Safety",
    "Certifications", "Water Resistance", "Frameset", "Drivetrain", "Brakes",
    "Wheelset", "Cockpit", "Geometry", "Included Accessories", "General / Other",
]


def classify(label: str) -> str:
    low = label.lower().replace("_", " ")   # tolerant of snake_case or spaced labels
    for name, keywords in GROUPS:
        if any(k in low for k in keywords):
            return name
    return "General / Other"


def group_specs(all_specs: dict, geometry: dict | None = None,
                brand: str | None = None) -> "OrderedDict":
    """Reorganize a flat label->value spec map into ordered canonical groups.

    Labels already present in `geometry` are routed to the Geometry group (built
    from `model.geometry`), not keyword-classified. Junk labels are dropped.
    Recognized component values are parsed into structured dicts (manufacturer,
    speeds, travel, …) with a `details` remainder. Empty groups are omitted.
    """
    geometry = geometry or {}
    geo_labels = set(geometry)
    snaked = {snake(k): v for k, v in (all_specs or {}).items()}  # for sibling lookup
    buckets: dict[str, "OrderedDict"] = {}
    for label, value in (all_specs or {}).items():
        if label in geo_labels:
            continue
        low = " ".join(label.split()).lower()
        if _is_junk(low):
            continue
        # classify on the original (spaced) label; emit a snake_case field name.
        field = snake(label)
        group = buckets.setdefault(classify(low), OrderedDict())
        parsed = parse_component(field, value, brand, siblings=snaked)
        if parsed:
            group[field] = parsed
        else:
            # unitize a standalone measurement (top_speed -> top_speed_mph: 28) or
            # keep the original string.
            uf = unitize(field, value)
            if uf:
                group[uf[0]] = uf[1]
            else:
                group[field] = value
    if geometry:
        buckets["Geometry"] = OrderedDict((snake(k), v) for k, v in geometry.items())
    out: "OrderedDict" = OrderedDict()
    for g in DISPLAY_ORDER:
        if buckets.get(g):
            out[snake(g)] = buckets[g]   # snake_case group names too
    return out
