#!/usr/bin/env python3
"""
Expand multi-configuration e-bikes into sibling model entries.

Some models sell spec-bearing configurations under one product page. One entry
with `price_from` + base specs makes the other configurations invisible or wrong
downstream (search, BOM/value estimates, scores, compare). This step rewrites
data/current/*_ebikes.json in place, splitting each spec-bearing configuration
into its own model entry along three axes, in order:

  1. price tiers — allowlisted option keys (battery size / version / drive-train
     / package / type) whose values drive 2+ distinct prices;
  2. battery options — single vs dual battery or distinct Ah packs, split even
     when the signal hides inside another option's values (Blix encodes
     "Single Battery Teal" / "Dual Battery Teal" as colors) and even when the
     price happens to match;
  3. frame styles — Step-Thru vs Step-Over (high-/mid-step), split regardless
     of price so each style is its own card and searchable via `frame_style`.

For each split: the base entry keeps its identity (stable id) and becomes the
cheapest configuration; siblings get `handle = <base>--<slug>` and a
tier-suffixed model name; all carry `tier` + `family_id`; `configurations` (and
`options.colors`) are filtered per entry so prices and swatches are right.
Splits compose: a model already split on drive-train can split again on frame
style ("Chain · Step-Thru").

Color and frame-size price differences are deliberately NOT expanded — colors
stay one card (the UI's swatches show per-color upcharges) and sizes stay one
card.

After expansion, per-family spec fix-ups run:
  - when a model carries one battery row per tier ("Battery ($1095 Model)" /
    "Battery ($1,195 Model)"), each entry keeps only its own row, renamed
    "Battery";
  - battery tiers share the scraped range text, but a smaller pack can't do the
    headline miles: the stated figure is assumed to belong to the largest pack
    and smaller tiers' miles scale by their Wh ratio, marked "(est.)".

Idempotent: re-runs find nothing further to split and the spec fix-ups detect
already-patched rows.

Run after add_pricing.py, before normalize.py (run_scrape.sh wires this).
"""
import copy
import glob
import json
import re
from pathlib import Path

from bike_taxonomy import STEP_THRU, STEP_OVER, frame_style_of, pick_frame_style

HERE = Path(__file__).parent
DATA = HERE / "data"

# Option keys that denote a real spec/build tier when they drive distinct prices.
# Strict full-match allowlist: looks/fit keys (color, size, frame-type) and junk
# keys never match. Frame styles split separately (price-independent) below.
TIER_KEY = re.compile(
    r"^(battery[\s_-]?size|version|drive[\s_-]?train|gearing(?:[\s_-]?system)?"
    r"|package|bike[\s_-]?type|variant|type)$", re.I)

# Some stores prefix option keys with a step number ("Step 1 Select Your Gearing
# System") — strip it so the key matches the TIER_KEY allowlist.
_STEP_PREFIX = re.compile(r"^step\s*\d+\s*[:.\-]?\s*select\s*(?:your\s*)?", re.I)


def _norm_key(k: str) -> str:
    return _STEP_PREFIX.sub("", (k or "").strip()).strip()


def _tier_label(v) -> str:
    """Drop a trailing price parenthetical from a tier value ("Enviolo ($3499)"
    -> "Enviolo") for the model-name suffix / tier label."""
    s = str(v or "")
    return re.sub(r"\s*\(\$[\d,]+\)\s*$", "", s).strip() or s

# Short labels for tier text / model-name suffixes; the searchable bucket name
# lives in `frame_style`.
FRAME_LABEL = {STEP_THRU: "Step-Thru", STEP_OVER: "Step-Over"}


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def base_source_id(m: dict) -> str:
    name = m.get("model") or m.get("title") or m.get("name") or m.get("handle")
    return (m.get("handle") or m.get("slug") or m.get("sku") or slugify(name) or "")


def cfg_color(c: dict):
    if isinstance(c.get("color"), dict) and c["color"].get("name"):
        return c["color"]["name"]
    for k, v in (c.get("options") or {}).items():
        kl = k.strip().lower()
        if "color" in kl or "colour" in kl:   # "Color" or "Step 2 Select Your Color"
            return v
    return None


# ----------------------------- battery spec patching -----------------------------

def _battery_row(specs_all: dict):
    for k, v in (specs_all or {}).items():
        if "batter" in k.lower() and isinstance(v, str) and re.search(r"\d", v):
            return k
    return None


def _battery_pack_rows(sec: dict) -> list:
    """Rows that describe a battery pack (have an Ah/Wh figure)."""
    return [k for k, v in (sec or {}).items()
            if "batter" in k.lower() and isinstance(v, str)
            and re.search(r"\d+(?:\.\d+)?\s*[AW][hH]", v)]


def patched_battery_text(text: str, tier_value: str):
    """New battery row text for this tier, or None when nothing is derivable.

    1. Ah-style values ("15Ah", "15Ah+20Ah"): rebuild the figures around the tier's
       (combined) Ah at the pack voltage; dual setups gain an explicit
       "(...Wh) combined dual battery" so battery_system_wh treats it as the total.
    2. Version-style values where the base text embeds per-version Wh
       ("956.8Wh (Single Battery Ver.)1913.6Wh (Dual Battery Ver.)"): pick the Wh
       figure attached to this tier's label.
    """
    text = text or ""
    ahs = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*A[hH]", tier_value)]
    if ahs:
        total_ah = sum(ahs)
        vm = re.search(r"(\d{2,3})\s*V\b", text, re.I)
        volts = float(vm.group(1)) if vm else 48.0
        total_wh = round(volts * total_ah)
        label = (f"{total_ah:g}Ah ({total_wh}Wh) combined dual battery"
                 if len(ahs) > 1 else f"{total_ah:g}Ah ({total_wh}Wh)")
        # drop any pre-existing Wh figure first so the new one is unambiguous
        cleaned = re.sub(r"\(?\s*\d{3,4}(?:\.\d+)?\s*W[hH]\s*\)?", "", text)
        if re.search(r"\d+(?:\.\d+)?\s*A[hH]", cleaned):
            return re.sub(r"\d+(?:\.\d+)?\s*A[hH]", label, cleaned, count=1)
        return (cleaned.strip(" ,;") + " — " if cleaned.strip() else "") + label
    m = re.search(r"(\d{3,4}(?:\.\d+)?)\s*W[hH]\s*\(\s*" + re.escape(tier_value),
                  text, re.I)
    if m:
        return f"{m.group(1)}Wh total — {tier_value}"
    return None


def apply_battery_patch(model: dict, tier_value: str) -> None:
    specs = model.get("specs") or {}
    # one battery row per tier is handled by select_tier_battery_row instead
    if len(_battery_pack_rows(specs.get("all") or {})) > 1:
        return
    row = _battery_row(specs.get("all") or {})
    if not row:
        return
    new = patched_battery_text(specs["all"][row], tier_value)
    if not new:
        return
    for section in ("all", "physical", "technical"):
        sec = specs.get(section)
        if isinstance(sec, dict) and row in sec:
            sec[row] = new


# ------------------------------- axis detection -------------------------------

def tier_axis(cfgs: list):
    """(option_key, {value: price}) when one allowlisted option key cleanly drives
    2+ distinct prices, else None."""
    priced = [c for c in cfgs or [] if isinstance(c, dict) and c.get("price") is not None]
    if len({c["price"] for c in priced}) < 2:
        return None
    keys = {k for c in priced for k in (c.get("options") or {})}
    for k in sorted(keys):
        if not TIER_KEY.match(_norm_key(k)):
            continue
        v2p: dict = {}
        for c in priced:
            v = (c.get("options") or {}).get(k)
            if v is not None:
                v2p.setdefault(str(v), set()).add(c["price"])
        if len(v2p) < 2:
            continue
        # Tier on the cheapest price per value (a colour upcharge inside a tier must
        # not block detection); valid when the tiers' base prices actually differ.
        mins = {v: min(ps) for v, ps in v2p.items()}
        if len(set(mins.values())) > 1:
            return k, mins
    return None


def battery_bucket(value):
    """Battery-option bucket of one option value, or None: "Single Battery" /
    "Dual Battery" / "<N>Ah". Catches battery choices hiding inside other
    option axes (Blix "Single Battery Teal" colors)."""
    s = str(value or "")
    m = re.search(r"\b(single|dual|double|triple)\s+batter", s, re.I)
    if m:
        return f"{m.group(1).title()} Battery"
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*ah\b", s, re.I)
    if m:
        return f"{m.group(1)}Ah"
    return None


def bucket_axis(cfgs: list, bucket_of):
    """(option_key, {bucket: set(values)}) for the first option key whose values
    map onto 2+ buckets via bucket_of, else None."""
    keys = sorted({k for c in cfgs or [] for k in (c.get("options") or {})})
    for k in keys:
        buckets: dict = {}
        for c in cfgs or []:
            v = (c.get("options") or {}).get(k)
            b = bucket_of(v) if v is not None else None
            if b:
                buckets.setdefault(b, set()).add(str(v))
        if len(buckets) > 1:
            return k, buckets
    return None


# ------------------------------- expansion -------------------------------

def make_sibling(base: dict, base_name: str, label: str, slug_value: str) -> dict:
    sid = base_source_id(base)
    sib = copy.deepcopy(base)
    sib["handle"] = f"{sid}--{slugify(slug_value)}"
    sib["model"] = f"{base_name} — {label}"
    sib["regular_price"] = None  # recomputed per tier from its own configs below
    return sib


def tier_regular_price(configs: list):
    """The sale's compare-at for one tier: the max per-config regular_price among
    the tier's own configurations (the scraper records it per variant), or None."""
    vals = [c["regular_price"] for c in configs
            if isinstance(c, dict) and c.get("regular_price")]
    return max(vals) if vals else None


def split_meta(m: dict, brand: str):
    """(family_id, old_tier, base_name) for a model about to split (again)."""
    fam = m.get("family_id") or f"{brand}__{base_source_id(m)}"
    old_tier = m.get("tier")
    name = m.get("model") or m.get("title") or m.get("name") or base_source_id(m)
    if old_tier and name.endswith(f" — {old_tier}"):
        name = name[: -len(f" — {old_tier}")]
    return fam, old_tier, name


def filter_colors(entry: dict) -> None:
    """Keep only the color options that still have a configuration on this entry."""
    cols = ((entry.get("options") or {}).get("colors")) or []
    if not cols:
        return
    names = {str(cfg_color(c)) for c in entry.get("configurations") or [] if cfg_color(c)}
    if not names:
        return
    kept = [c for c in cols if str(c.get("name") or c.get("label")) in names]
    if kept and len(kept) < len(cols):
        entry["options"]["colors"] = kept


def expand_generic(brand: str, m: dict) -> list:
    """Split along an allowlisted price-tier option key."""
    axis = tier_axis(m.get("configurations") or [])
    if not axis:
        return [m]
    key, value_prices = axis
    fam, old_tier, base_name = split_meta(m, brand)
    ordered = sorted(value_prices.items(), key=lambda kv: kv[1])
    # Siblings must be cut from the model as it was BEFORE the i==0 pass turns
    # `m` itself into the base entry (filtering its configurations/colors in
    # place) — otherwise later tiers inherit the base's narrowed data and end
    # up with no configurations at all.
    pristine = copy.deepcopy(m)
    out = []
    for i, (value, price) in enumerate(ordered):
        disp = _tier_label(value)
        label = f"{old_tier} · {disp}" if old_tier else disp
        entry = m if i == 0 else make_sibling(pristine, base_name, label, value)
        if i == 0 and old_tier:
            entry["model"] = f"{base_name} — {label}"
        entry["tier"] = label
        entry["family_id"] = fam
        entry["price_from"] = price
        entry["configurations"] = [
            c for c in (pristine.get("configurations") or [])
            if str((c.get("options") or {}).get(key)) == value
        ]
        entry["regular_price"] = tier_regular_price(entry["configurations"])
        filter_colors(entry)
        apply_battery_patch(entry, value)
        out.append(entry)
    return out


def expand_buckets(brand: str, m: dict, bucket_of, label_of, field=None) -> list:
    """Split along bucketed option values (battery options, frame styles) —
    price-independent: distinct buckets are distinct cards even at equal price."""
    cfgs = m.get("configurations") or []
    axis = bucket_axis(cfgs, bucket_of)
    if not axis:
        return [m]
    key, buckets = axis
    fam, old_tier, base_name = split_meta(m, brand)

    def bucket_price(vals):
        ps = [c["price"] for c in cfgs
              if c.get("price") is not None
              and str((c.get("options") or {}).get(key)) in vals]
        return min(ps) if ps else None

    ordered = sorted(buckets.items(),
                     key=lambda kv: (bucket_price(kv[1]) is None,
                                     bucket_price(kv[1]) or 0, label_of(kv[0])))
    # As in expand_generic: cut siblings from the pre-mutation model, not from
    # the base entry whose colors the i==0 pass narrows in place.
    pristine = copy.deepcopy(m)
    out = []
    for i, (bucket, vals) in enumerate(ordered):
        label = f"{old_tier} · {label_of(bucket)}" if old_tier else label_of(bucket)
        entry = m if i == 0 else make_sibling(pristine, base_name, label, label_of(bucket))
        if i == 0 and old_tier:
            entry["model"] = f"{base_name} — {label}"
        entry["tier"] = label
        entry["family_id"] = fam
        if field:
            entry[field] = bucket
        price = bucket_price(vals)
        if price is not None:
            entry["price_from"] = price
        entry["configurations"] = [
            c for c in cfgs
            if key not in (c.get("options") or {})
            or str((c.get("options") or {}).get(key)) in vals
        ]
        entry["regular_price"] = tier_regular_price(entry["configurations"])
        filter_colors(entry)
        out.append(entry)
    return out


def expand_battery(brand: str, m: dict) -> list:
    out = expand_buckets(brand, m, battery_bucket, lambda b: b)
    for e in out:
        if len(out) > 1:
            apply_battery_patch(e, e["tier"].rsplit(" · ", 1)[-1])
    return out


def expand_frames(brand: str, m: dict) -> list:
    out = expand_buckets(brand, m, frame_style_of, FRAME_LABEL.get, field="frame_style")
    if len(out) == 1 and not m.get("frame_style"):
        # no split, but tag the searchable style when the model carries a signal
        b = pick_frame_style(
            m.get("tier"), m.get("model"),
            *(str(v) for c in m.get("configurations") or []
              for v in (c.get("options") or {}).values()))
        if b:
            m["frame_style"] = b
    return out


def expand_lectric(brand: str, m: dict) -> list:
    """Lectric captures per-config specs in `configs`; one entry per battery tier
    AND frame style, each carrying its config's full data."""
    cfgs = [c for c in (m.get("configs") or []) if c.get("price") is not None]
    # per-(frame|battery) sold-out colours from the scraper (removed so it isn't copied
    # onto siblings); each split card looks up its own tier below.
    tiers = m.pop("sold_out_by_tier", None) or {}
    if not cfgs:
        return [m]
    name = m.get("model") or ""

    def battery_of(c, i=0):
        return (c.get("battery") or
                (c.get("label") or "").replace(name, "").strip(" -—") or
                f"config {i + 1}")

    groups: dict = {}
    for c in cfgs:
        key = (battery_of(c), frame_style_of(c.get("label")))
        if key not in groups or c["price"] < groups[key]["price"]:
            groups[key] = c
    if len(groups) < 2:
        b = frame_style_of(cfgs[0].get("label")) or frame_style_of(name)
        if b and not m.get("frame_style"):
            m["frame_style"] = b
        return [m]
    fam = m.get("family_id") or f"{brand}__{base_source_id(m)}"
    # family-level colors carry name+hex+image; configs only list label/href/hex
    fam_colors = ((m.get("options") or {}).get("colors")) or []
    ordered = sorted(groups.items(),
                     key=lambda kv: (kv[1]["price"], kv[0][1] == STEP_OVER))
    out = []
    for i, ((battery, bucket), c) in enumerate(ordered):
        parts = [p for p in (battery, FRAME_LABEL.get(bucket)) if p]
        tier_label = " · ".join(parts) or f"config {i + 1}"
        entry = m if i == 0 else make_sibling(m, name, tier_label, tier_label)
        entry["tier"] = tier_label
        entry["family_id"] = fam
        if bucket:
            entry["frame_style"] = bucket
        # the config carries its own full data — use it verbatim
        if c.get("specs"):
            entry["specs"] = copy.deepcopy(c["specs"])
            entry["spec_count"] = len((c["specs"] or {}).get("all") or {})
        if c.get("geometry"):
            entry["geometry"] = copy.deepcopy(c["geometry"])
        if c.get("url"):
            entry["url"] = c["url"]
        if c.get("colors"):
            # keep the image-bearing family entries, narrowed to this config's palette
            wanted = {cc.get("label") or cc.get("name") for cc in c["colors"]}
            kept = [fc for fc in fam_colors
                    if (fc.get("name") or fc.get("label")) in wanted]
            entry.setdefault("options", {})["colors"] = (
                copy.deepcopy(kept) if kept else copy.deepcopy(c["colors"]))
        if c.get("accessories"):
            entry["accessories"] = copy.deepcopy(c["accessories"])
        entry["price_range"] = {"min": c["price"], "max": c["price"],
                                "currency": (m.get("price_range") or {}).get("currency", "USD")}
        entry["configs"] = [copy.deepcopy(c)]
        # per-tier sold-out: a colour can be out on THIS battery/frame only. Keyed the same
        # way build_model wrote it: f"{frame_style}|{battery}".
        tier = tiers.get(f"{bucket or ''}|{battery or ''}")
        if tier is not None:
            entry["sold_out_options"] = {"Colors": tier["Colors"]} if tier.get("Colors") else {}
            entry["in_stock"] = tier.get("in_stock")
        out.append(entry)
    return out


# --------------------------- per-family spec fix-ups ---------------------------

def select_tier_battery_row(model: dict) -> None:
    """When a model carries one battery row per price tier (Portola:
    "Battery ($1095 Model)" / "Battery ($1,195 Model)"), keep only the row whose
    Ah matches this entry's tier and rename it "Battery"."""
    m_ah = re.search(r"(\d+(?:\.\d+)?)\s*ah\b", model.get("tier") or "", re.I)
    if not m_ah:
        return
    ah = m_ah.group(1)
    specs = model.get("specs") or {}
    for section in ("all", "physical", "technical"):
        sec = specs.get(section)
        if not isinstance(sec, dict):
            continue
        rows = _battery_pack_rows(sec)
        if len(rows) < 2:
            continue
        keep = [k for k in rows
                if re.search(rf"\b{re.escape(ah)}\s*A[hH]\b", sec[k])]
        if len(keep) != 1:
            continue
        renamed = {}
        for k, v in sec.items():
            if k == keep[0]:
                renamed["Battery"] = v
            elif k in rows:
                continue            # the other tiers' packs
            else:
                renamed[k] = v
        sec.clear()
        sec.update(renamed)


# "<value> (<Version label> Ver.)" segments packed into one spec value
# (Heybike Saturn: "956.8Wh (Single Battery Ver.)1913.6Wh (Dual Battery Ver.)").
_VER_SEG = re.compile(r"([^()]+?)\s*\(\s*([^()]*?)\s*Ver\.?\s*\)", re.I)


def select_version_segments(model: dict) -> None:
    """When a spec value packs per-version segments and this entry's tier names
    exactly one of those versions, keep only that version's segment. Applies to
    every such row (Battery, Max Range, ...). Idempotent: a sliced value has a
    single segment and is skipped."""
    tier = (model.get("tier") or "").lower()
    if not tier:
        return
    specs = model.get("specs") or {}
    for section in ("all", "physical", "technical"):
        sec = specs.get(section)
        if not isinstance(sec, dict):
            continue
        for k, v in list(sec.items()):
            if not isinstance(v, str):
                continue
            segs = _VER_SEG.findall(v)
            if len(segs) < 2:
                continue
            mine = [(val, label) for val, label in segs if label.lower() in tier]
            if len(mine) == 1:
                val, label = mine[0]
                sec[k] = f"{val.strip()} ({label} Ver.)"


# A trailing "(<qualifier>)" on a spec label, e.g. "Fork (Suspension Frame)".
_TIER_QUAL = re.compile(r"\s*\(([^)]*)\)\s*$")
# qualifier/tier words that don't identify a tier on their own
_QUAL_GENERIC = {"frame", "model", "ver", "version", "edition"}


def _qual_words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower())
            if w not in _QUAL_GENERIC}


def select_tier_qualified_rows(entries: list) -> None:
    """For a family split into tiers, a spec row labelled "<base> (<qualifier>)"
    belongs only to the tier its qualifier names. Drop rows whose qualifier names
    a SIBLING tier, and rename a row matching this entry's own tier to "<base>"
    (overriding any unqualified base row). Fixes Ride1Up Roadster V3, whose page
    lists "Fork (Rigid)" + "Fork (Suspension Frame)" against both tier entries so
    the rigid bike wrongly inherits the suspension fork. Idempotent: once a row is
    renamed to its base it has no qualifier and is skipped."""
    fam_words = set()
    for m in entries:
        fam_words |= _qual_words(m.get("tier"))
    if len(fam_words) < 2:
        return
    for m in entries:
        own = _qual_words(m.get("tier"))
        sibling = fam_words - own
        if not own:
            continue
        specs = m.get("specs") or {}
        for section in ("all", "physical", "technical"):
            sec = specs.get(section)
            if not isinstance(sec, dict):
                continue
            for k in list(sec.keys()):
                mq = _TIER_QUAL.search(k)
                if not mq:
                    continue
                qual = _qual_words(mq.group(1))
                base = _TIER_QUAL.sub("", k).strip()
                if qual & own:
                    sec[base] = sec.pop(k)          # this tier's row -> canonical
                elif qual & sibling:
                    sec.pop(k, None)                # a sibling tier's row


def _entry_wh(model: dict):
    specs = model.get("specs") or {}
    for section in ("all", "physical", "technical"):
        sec = specs.get(section)
        if not isinstance(sec, dict):
            continue
        for k in _battery_pack_rows(sec):
            t = sec[k]
            m_wh = re.search(r"(\d{3,4}(?:\.\d+)?)\s*W[hH]\b", t)
            if m_wh:
                return float(m_wh.group(1))
            m_v = re.search(r"(\d{2,3})\s*V\b", t, re.I)
            m_a = re.search(r"(\d+(?:\.\d+)?)\s*A[hH]\b", t)
            if m_v and m_a:
                return float(m_v.group(1)) * float(m_a.group(1))
    return None


def scale_family_ranges(entries: list) -> None:
    """Battery tiers share the scraped range text, but a smaller pack can't do
    the headline miles. Assume the stated figure belongs to the largest pack and
    scale the smaller tiers' miles by their Wh ratio, marked "(est.)"."""
    whs = [_entry_wh(e) for e in entries]
    known = [w for w in whs if w]
    if len(entries) < 2 or len(known) != len(entries) or len(set(known)) < 2:
        return
    # Per-tier range text already differs (e.g. version-sliced exact figures):
    # the shared-headline premise doesn't hold, so estimating would corrupt it.
    def range_texts(e):
        return tuple(sorted(v for k, v in ((e.get("specs") or {}).get("all") or {}).items()
                            if "range" in k.lower() and isinstance(v, str)))
    if len({range_texts(e) for e in entries}) > 1:
        return
    max_wh = max(known)
    for e, wh in zip(entries, whs):
        if wh >= max_wh:
            continue
        ratio = wh / max_wh
        specs = e.get("specs") or {}
        for section in ("all", "physical", "technical"):
            sec = specs.get(section)
            if not isinstance(sec, dict):
                continue
            for k, v in list(sec.items()):
                if "range" not in k.lower() or not isinstance(v, str) or "est." in v:
                    continue
                new = re.sub(
                    r"(\d{2,3})(\s*(?:miles?|mi\b))",
                    lambda mm: f"{round(float(mm.group(1)) * ratio)}{mm.group(2)}", v)
                if new != v:
                    sec[k] = f"{new} (est. for this battery size)"


# ------------------------------------ main ------------------------------------

def expand_model(brand: str, m: dict) -> list:
    if brand == "lectric":
        return expand_lectric(brand, m)
    out = []
    for e in expand_generic(brand, m):
        for e2 in expand_battery(brand, e):
            out.extend(expand_frames(brand, e2))
    return out


def main():
    grand = 0
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        d = json.load(open(f))
        before = json.dumps(d, sort_keys=True)
        out = []
        for m in d.get("models", []):
            out.extend(expand_model(brand, m))
        added = len(out) - len(d.get("models", []))
        # per-tier battery rows, then family-wide range scaling
        fams: dict = {}
        for m in out:
            if m.get("tier"):
                select_tier_battery_row(m)
                select_version_segments(m)
            if m.get("family_id"):
                fams.setdefault(m["family_id"], []).append(m)
        for entries in fams.values():
            select_tier_qualified_rows(entries)
            scale_family_ranges(entries)
        d["models"] = out
        d["model_count"] = len(out)
        if json.dumps(d, sort_keys=True) != before:
            json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
            print(f"{brand:<12} expanded {added:+d} -> {len(out)} models")
            grand += added
    print(f"total new tier entries: {grand}")


if __name__ == "__main__":
    main()
