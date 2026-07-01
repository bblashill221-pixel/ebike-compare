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


# A geometry/measurement diagram numbers its callouts "A – Total Length", "B--Reach",
# "(C) Wheelbase", "D. Stack", ... — a single letter + separator before the name. These
# leading letters are ordering artifacts, not part of the spec name. We strip them, but
# only when a model carries a real legend (>=4 distinct such letters), so isolated
# compounds like "E-bike Class", "X-Fold System", "B.B. Drop", "N.W./G.W.", "L × W × H"
# (joined forms / no separating space / non-dash separators) are never touched.
_DIAGRAM_LABEL = re.compile(
    r"^(?:"
    r"\(\s*([A-Za-z])\s*\)\s*"          # (A)  ( A )
    r"|([A-Za-z])\s*(?:--|[-–—])\s*"    # A--  A-  A –  A -
    r"|([A-Za-z])[.):：]\s+"            # A.  A)  A:   (separator then a space)
    r")(?=[A-Za-z])")
_LABEL_KEEP = re.compile(r"^[A-Za-z][-–—](?:bike|fold)\b", re.I)


def _label_letter(k: str):
    """The diagram-label letter at the start of a key, or None (compounds excluded)."""
    m = _DIAGRAM_LABEL.match(k or "")
    if not m or _LABEL_KEEP.match(k):
        return None
    return (m.group(1) or m.group(2) or m.group(3)).upper()


def _legend_letters(*keysets) -> set:
    """The set of diagram-label letters when a model has a real legend, else empty."""
    letters = {L for keys in keysets for k in keys if (L := _label_letter(k))}
    return letters if len(letters) >= 4 else set()


def _strip_diagram_labels(specs: dict, legend: set) -> dict:
    """Drop the leading "A – "/"B--"/"(C) "/"D. " ordering label from legend keys."""
    if not specs or not legend:
        return specs
    out = OrderedDict()
    for k, v in specs.items():
        if _label_letter(k) in legend:
            out[_DIAGRAM_LABEL.sub("", k, 1).strip() or k] = v
        else:
            out[k] = v
    return out


_UNIT_SUFFIX = {"_kwh": "kWh", "_wh": "Wh", "_nm": "Nm", "_ah": "Ah",
                "_mm": "mm", "_mph": "mph", "_lb": "lb", "_mi": "mi",
                "_in": "in", "_deg": "deg", "_w": "W", "_v": "V",
                "_kg": "kg", "_kph": "kph", "_km": "km", "_cm": "cm"}


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
        elif k == "speeds":
            # "speeds: 10" -> "10-speed" so the gear-count regexes can see it
            # (a "Deore M6000" derailleur never says "speed" in words).
            token = f"{v}-speed"
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
            elif isinstance(v, dict) and ("_kind" in v or "details" in v):
                # parsed component (fully-parsed ones carry no details key)
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
    # Kept at top priority so a cert label isn't stolen by a component group;
    # the collected bucket is appended to the END of "General Info" (Key Aspects)
    # below, so certs render last in that section rather than as their own.
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
        "usb", "ecu", "pwr",
        # lighting + other electrical safety items (formerly the Safety group)
        # are consolidated here.
        "headlight", "tail light", "taillight", "rear light", "front light",
        "brake light", "daytime running", "drl", "reflector", "horn", "bell",
        "mirror", "anti-lock", "antilock", "turn signal", "blinker",
        "safety light", "lights", "light")),
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
    "General Info", "Ebike System", "Special Features",
    "Water Resistance", "Frameset", "Wheelset", "Brakes", "Drivetrain",
    "Cockpit", "Geometry", "Included Accessories", "General / Other",
]


def classify(label: str) -> str:
    low = label.lower().replace("_", " ")   # tolerant of snake_case or spaced labels
    # Physical pedals belong in Drivetrain. The keyword loop only catches plural
    # "pedals", so a singular "Pedal" spec falls through to General Info (Key Aspects);
    # route any bare-pedal label here. Excludes motor-system attributes ("pedal assist/
    # sensor/mode/...", which are Ebike System) and saddle-to-pedal geometry (Cockpit).
    if "pedal" in low and not re.search(
            r"assist|sensor|mode|range|level|type|response|xperience|experience"
            r"|intelligent|saddle|seat|distance", low):
        return "Drivetrain"
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
    # strip "A – "/"B--"/"C. " diagram ordering labels from both spec sources first
    legend = _legend_letters(all_specs or {}, geometry or {})
    all_specs = _strip_diagram_labels(all_specs or {}, legend)
    geometry = _strip_diagram_labels(geometry or {}, legend)
    geo_labels = set(geometry)
    snaked = {snake(k): v for k, v in (all_specs or {}).items()}  # for sibling lookup
    # "Drive Unit" / "Mid Drive Motor" / "Hub Motor" are synonyms for "Motor" (a single
    # motor named by its placement); listings often carry both a generic "Motor" row and
    # one of these, yielding two identical motor components (double-counts the motor in the
    # value base + shows twice). Fold them onto `motor` so a single-motor bike has one motor
    # field. Skip on AWD bikes, where _awd_motor_rows already split the motor into Front/Rear
    # rows (those keep their own field names and aren't folded).
    has_side_motor = any(re.match(r"\s*(front|rear)\s+motor\b", k, re.I)
                         for k in (all_specs or {}))
    _MOTOR_SYNONYMS = {"drive_unit", "mid_drive_motor", "hub_motor"}
    buckets: dict[str, "OrderedDict"] = {}
    horn_present = False
    for label, value in (all_specs or {}).items():
        if label in geo_labels:
            continue
        low = " ".join(label.split()).lower()
        if _is_junk(low):
            continue
        # A horn is its own item; note it wherever it is mentioned (often buried in
        # a light spec like "White Light with Horn") so it can be emitted as a
        # standalone Ebike System field below rather than inside the light.
        if re.search(r"\bhorn\b", f"{label} {value}", re.I):
            horn_present = True
        # classify on the original (spaced) label; emit a snake_case field name.
        field = snake(label)
        if field in _MOTOR_SYNONYMS and not has_side_motor:
            field = "motor"
        group = buckets.setdefault(classify(low), OrderedDict())
        parsed = parse_component(field, value, brand, siblings=snaked)
        if parsed:
            group[field] = parsed
        else:
            # unitize a standalone measurement (top_speed -> top_speed_mph +
            # top_speed_kph) or keep the original string. unitize returns a dict of
            # one or more suffixed fields (toggle-able dims carry both units).
            uf = unitize(field, value)
            if uf:
                group.update(uf)
            else:
                group[field] = value
    if horn_present:
        esys = buckets.setdefault("Ebike System", OrderedDict())
        if not any("horn" in k for k in esys):   # skip if a dedicated horn field exists
            esys["horn"] = True
    # Relocate Certifications to the BOTTOM of "General Info" (the Key Aspects
    # section) rather than rendering them as their own section.
    cert_bucket = buckets.pop("Certifications", None)
    if cert_bucket:
        gi = buckets.setdefault("General Info", OrderedDict())
        for k, v in cert_bucket.items():
            gi[k] = v
    # The battery's own weight belongs inside the battery component, not as a
    # sibling field. Fold battery_weight[_lb/_kg] (and primary_/secondary_ for
    # dual-battery bikes) into specs.ebike_system.battery as weight[_lb/_kg]. The
    # "battery_weight" anchor naturally excludes bike weights like
    # "bike_weight_without_battery_lb".
    sys_bucket = buckets.get("Ebike System")
    if isinstance(sys_bucket, dict) and isinstance(sys_bucket.get("battery"), dict):
        bat = sys_bucket["battery"]
        for fld in [f for f in sys_bucket
                    if re.match(r"(?:(primary|secondary)_)?battery_weight(?:_(lb|kg))?$", f)]:
            m = re.match(r"(?:(primary|secondary)_)?battery_weight(?:_(lb|kg))?$", fld)
            prefix = (m.group(1) + "_") if m.group(1) else ""
            unit = ("_" + m.group(2)) if m.group(2) else ""
            bat[f"{prefix}weight{unit}"] = sys_bucket.pop(fld)
    # A single suspension row can bundle a front fork AND a rear shock ("Front: …
    # Fork … Rear: Horst Link Suspension"); that parses as only a fork, so the rear
    # shock never gets its own value/cost line. Mint it as a separate rear_shock
    # component and trim the fork's details to the front (so the fork is no longer
    # priced as a whole full-suspension system). Only when the Frameset has a fork
    # that names a rear shock and no shock component yet.
    fs = buckets.get("Frameset")
    if isinstance(fs, dict) and not any(
            isinstance(c, dict) and c.get("_kind") == "shock" for c in fs.values()):
        for c in list(fs.values()):
            if not (isinstance(c, dict) and c.get("_kind") == "fork"):
                continue
            det = c.get("details") or ""
            if not (re.search(r"\bfront\b", det, re.I) and re.search(
                    r"\brear\b[^.]*?(suspension|shock|spring|link|horst)", det, re.I)):
                continue
            front, _, rear = (re.split(r"(\brear\b\s*:?\s*)", det, maxsplit=1, flags=re.I) + ["", ""])[:3]
            sh = parse_component("rear_shock", rear, brand)
            if sh and sh.get("_kind") == "shock":
                fs["rear_shock"] = sh
                front = re.sub(r"\bfront\b\s*:?\s*", "", front, flags=re.I).strip(" ,;:")
                if front:
                    c["details"] = front
                else:
                    c.pop("details", None)
            break
    if geometry:
        buckets["Geometry"] = OrderedDict((snake(k), v) for k, v in geometry.items())
    out: "OrderedDict" = OrderedDict()
    for g in DISPLAY_ORDER:
        if buckets.get(g):
            out[snake(g)] = buckets[g]   # snake_case group names too
    return out
