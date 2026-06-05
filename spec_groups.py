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
from collections import OrderedDict

# Page-chrome strings that leaked into specs.all but aren't real specs -> dropped.
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
    low = label.lower()
    for name, keywords in GROUPS:
        if any(k in low for k in keywords):
            return name
    return "General / Other"


def group_specs(all_specs: dict, geometry: dict | None = None) -> "OrderedDict":
    """Reorganize a flat label->value spec map into ordered canonical groups.

    Labels already present in `geometry` are routed to the Geometry group (built
    from `model.geometry`), not keyword-classified. Junk labels are dropped.
    Empty groups are omitted.
    """
    geometry = geometry or {}
    geo_labels = set(geometry)
    buckets: dict[str, "OrderedDict"] = {}
    for label, value in (all_specs or {}).items():
        if label in geo_labels:
            continue
        low = " ".join(label.split()).lower()
        if _is_junk(low):
            continue
        buckets.setdefault(classify(low), OrderedDict())[label] = value
    if geometry:
        buckets["Geometry"] = OrderedDict(geometry)
    out: "OrderedDict" = OrderedDict()
    for g in DISPLAY_ORDER:
        if buckets.get(g):
            out[g] = buckets[g]
    return out
