#!/usr/bin/env python3
"""
Field-values report: every distinct value of a parsed component kind's fields
(plus the typed/search fields derived from it), with counts and example models.
A parsing-quality audit artifact -- odd values, singletons, and cross-layer
disagreements are where parser bugs live.

Usage:
  python report_field_values.py                 # motor (default)
  python report_field_values.py --kind frame
Output: data/current/field_values_<kind>.md (+ the same table on stdout)
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data"

# typed/search fields associated with each component kind (extend as needed)
TYPED_FIELDS = {
    "motor": ["motor_w", "motor_peak_w", "torque_nm", "drive_type"],
    "battery": ["battery_wh", "cell_brand", "removable_battery"],
    "frame": ["frame_material"],
    "brake": ["brake_type"],
    "display": ["display_type"],
}


def fmt_val(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def sort_key(v: str):
    try:
        return (0, float(v), "")
    except ValueError:
        return (1, 0.0, v.lower())


def fields_summary(models) -> list[str]:
    """Per component kind: every field, models with a real value, models with a
    false/empty placeholder, and distinct value count."""
    present: dict = defaultdict(Counter)
    falsy: dict = defaultdict(Counter)
    values: dict = defaultdict(set)
    for m in models:
        seen = set()
        for rows in (m.get("specs") or {}).values():
            for v in rows.values():
                if not (isinstance(v, dict) and v.get("_kind")):
                    continue
                kind = v["_kind"]
                for fk, fv in v.items():
                    if fk == "_kind" or (kind, fk, m["id"]) in seen:
                        continue
                    seen.add((kind, fk, m["id"]))
                    if fv in (None, "", [], False):
                        falsy[kind][fk] += 1
                    else:
                        present[kind][fk] += 1
                        values[(kind, fk)].add(fmt_val(fv) if not isinstance(fv, (list, dict))
                                               else str(fv))
    lines = ["| component | field | models | empty/false | distinct values |",
             "|---|---|---:|---:|---:|"]
    for kind in sorted(present):
        for fk, n in present[kind].most_common():
            lines.append(f"| {kind} | {fk} | {n} | {falsy[kind].get(fk, 0)} "
                         f"| {len(values[(kind, fk)])} |")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="motor")
    ap.add_argument("--fields", action="store_true",
                    help="field-level summary across ALL component kinds")
    ap.add_argument("--examples", type=int, default=3)
    ap.add_argument("-i", "--input",
                    default=str(DATA / "current" / "active" / "ebikes_normalized.json"))
    args = ap.parse_args()

    if args.fields:
        doc = json.load(open(args.input))
        lines = [f"# Component fields — {len(doc.get('models', []))} models, "
                 f"{datetime.now(timezone.utc).date()}", ""]
        lines += fields_summary(doc.get("models", []))
        out = DATA / "current" / "component_fields.md"
        out.write_text("\n".join(lines) + "\n")
        print("\n".join(lines))
        print(f"\n[*] wrote {out}")
        return

    doc = json.load(open(args.input))
    models = doc.get("models", [])

    # (layer, field, value) -> [model names]; plus per-model layer values for
    # the cross-layer disagreement check
    occ: dict = defaultdict(list)
    comp_by_model: dict = {}
    for m in models:
        name = f"{m['brand']} {m['model']}"
        for rows in (m.get("specs") or {}).values():
            for v in rows.values():
                if isinstance(v, dict) and v.get("_kind") == args.kind:
                    comp_by_model.setdefault(m["id"], v)
                    for fk, fv in v.items():
                        if fk in ("_kind", "details", "by_size") or fv is None:
                            continue
                        if isinstance(fv, list):
                            for item in fv:
                                occ[("component", fk, fmt_val(item))].append(name)
                        else:
                            occ[("component", fk, fmt_val(fv))].append(name)
        t = (m.get("analysis") or {}).get("specs_typed") or {}
        for fk in TYPED_FIELDS.get(args.kind, []):
            if t.get(fk) is not None:
                occ[("typed", fk, fmt_val(t[fk]))].append(name)

    lines = [f"# {args.kind} field values — {len(models)} models, "
             f"{datetime.now(timezone.utc).date()}", "",
             "| layer | field | value | models | examples |",
             "|---|---|---|---:|---|"]
    by_field: dict = defaultdict(list)
    for (layer, field, val), names in occ.items():
        by_field[(layer, field)].append((val, names))
    for (layer, field) in sorted(by_field, key=lambda x: (x[0], x[1])):
        for val, names in sorted(by_field[(layer, field)], key=lambda x: sort_key(x[0])):
            ex = "; ".join(sorted(set(names))[: args.examples])
            lines.append(f"| {layer} | {field} | {val} | {len(names)} | {ex} |")

    # anomalies: singletons + cross-layer disagreements
    lines += ["", "## Anomalies", "", "### Singleton values (1 model — typo/misparse candidates)"]
    for (layer, field) in sorted(by_field):
        for val, names in sorted(by_field[(layer, field)], key=lambda x: sort_key(x[0])):
            if len(set(names)) == 1:
                lines.append(f"- {layer}.{field} = `{val}` — {names[0]}")

    if args.kind == "motor":
        lines += ["", "### Cross-layer disagreements (component vs typed)"]
        pairs = [("power_w", "motor_w"), ("peak_w", "motor_peak_w"),
                 ("torque_nm", "torque_nm"), ("placement", "drive_type")]
        n = 0
        for m in models:
            comp = comp_by_model.get(m["id"])
            if not comp:
                continue
            t = (m.get("analysis") or {}).get("specs_typed") or {}
            for cf, tf in pairs:
                cv, tv = comp.get(cf), t.get(tf)
                if cv is not None and tv is not None and fmt_val(cv) != fmt_val(tv):
                    lines.append(f"- {m['id']}: component {cf}={fmt_val(cv)} "
                                 f"vs typed {tf}={fmt_val(tv)}")
                    n += 1
        if not n:
            lines.append("- none")

    out = DATA / "current" / f"field_values_{args.kind}.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n[*] wrote {out}")


if __name__ == "__main__":
    main()
