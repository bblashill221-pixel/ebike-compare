#!/usr/bin/env python3
"""
LLM component extraction: parse every raw component spec row with Claude into
the same structured dicts parse_components produces, cached by content hash so
each unique (kind, brand, text) row is parsed once, ever. parse_components
consults the cache FIRST (LLM is the primary engine); the regex parsers remain
the fallback for cache misses, so the pipeline never blocks on the network.

Workflow:
  python llm_parse_components.py --plan          # rows pending, cost estimate, sample prompt
  python llm_parse_components.py --run           # submit a Message Batch, poll, write cache
  python llm_parse_components.py --check-golden  # LLM vs golden-corpus contradictions

Needs ANTHROPIC_API_KEY (or any credential the anthropic SDK resolves).
Model: claude-opus-4-8 via the Batches API (50% price).

Cache: data/curated/llm_components.json
  {hash: {kind, brand, text, parsed: {...}, model, at}}
Registry (allowed fields per kind, generated from the current build):
  data/curated/component_field_registry.json
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from spec_groups import snake
from parse_components import _resolver

DATA = Path(__file__).parent / "data"
CACHE_PATH = DATA / "curated" / "llm_components.json"
REGISTRY_PATH = DATA / "curated" / "component_field_registry.json"
GOLDEN_PATH = DATA / "golden" / "component_parse_cases.json"
MODEL = "claude-opus-4-8"
ROWS_PER_REQUEST = 25

LIST_FIELDS = {"mounts", "standards", "connectivity"}


def row_key(kind: str, brand: str, text: str) -> str:
    return hashlib.sha256(f"{kind}|{brand}|{text}".encode()).hexdigest()[:20]


def collect_rows() -> list[dict]:
    """Every unique component row across the per-brand scrape files."""
    seen, rows = set(), []
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        try:
            doc = json.load(open(f))
        except ValueError:
            continue
        for m in doc.get("models", []):
            for label, value in ((m.get("specs") or {}).get("all") or {}).items():
                if not isinstance(value, str) or not value.strip():
                    continue
                fn = _resolver(snake(label))
                if fn is None:
                    continue
                kind = fn.__name__.lstrip("_")
                key = row_key(kind, brand, value)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"key": key, "kind": kind, "brand": brand, "text": value})
    return rows


def build_registry() -> dict:
    """kind -> field -> type, surveyed from the current build's parsed
    components (the LLM may only emit fields the pipeline already knows)."""
    doc = json.load(open(DATA / "current" / "active" / "ebike.json"))
    reg: dict = defaultdict(dict)
    for m in doc.get("models", []):
        for rows in (m.get("specs") or {}).values():
            for v in rows.values():
                if not (isinstance(v, dict) and v.get("_kind")):
                    continue
                for fk, fv in v.items():
                    if fk in ("_kind", "by_size") or fv is None:
                        continue
                    t = ("list" if isinstance(fv, list) else
                         "bool" if isinstance(fv, bool) else
                         "number" if isinstance(fv, (int, float)) else "string")
                    reg[v["_kind"]].setdefault(fk, t)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=1, sort_keys=True))
    return reg


def load_registry() -> dict:
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return build_registry()


def fewshot_examples(registry: dict, per_kind: int = 1) -> list[dict]:
    """One worked example per kind, drawn from the golden corpus, so the model
    learns the value conventions (snake_case enums, units stripped, etc.)."""
    try:
        cases = json.loads(GOLDEN_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return []
    out, used = [], set()
    for c in cases:
        if c["kind"] in used or c["kind"] not in registry:
            continue
        exp = {k: v for k, v in c["expected"].items() if k != "_kind"}
        if len(exp) < 3:
            continue  # prefer instructive examples
        used.add(c["kind"])
        out.append({"kind": c["kind"], "text": c["text"], "fields": exp})
    return out


def system_prompt(registry: dict) -> str:
    lines = [
        "You extract structured fields from e-bike component spec text.",
        "For each numbered row you receive (kind | brand | text), emit the row id",
        "and the fields you can read from the text. Rules:",
        "- Only use field names listed for that kind below; omit fields the text",
        "  does not state. NEVER guess or use outside knowledge: if a value is",
        "  not in the text, leave the field out.",
        "- Values are strings: numbers as plain digits (no units), booleans as",
        "  'true'/'false' (emit only when true or explicitly stated false),",
        "  lists joined with '|'. Enum-ish values use lowercase snake_case",
        "  matching the examples (e.g. 'hydraulic', 'square_taper', 'mid').",
        "- 'details': the leftover descriptive text AFTER removing everything",
        "  you extracted into other fields (empty if nothing meaningful left).",
        "- 'manufacturer' is a component maker (Shimano, Tektro, Bafang, Fizik,",
        "  ...), 'model' its product/series name.",
        "",
        "Fields per kind:",
    ]
    for kind in sorted(registry):
        fields = ", ".join(f"{f}({t})" for f, t in sorted(registry[kind].items()))
        lines.append(f"  {kind}: {fields}")
    ex = fewshot_examples(registry)
    if ex:
        lines.append("\nWorked examples:")
        for e in ex:
            lines.append(f"  [{e['kind']}] {e['text']!r}")
            lines.append(f"    -> {json.dumps(e['fields'], ensure_ascii=False)}")
    return "\n".join(lines)


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"},
                                           "value": {"type": "string"}},
                            "required": ["name", "value"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "fields"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rows"],
    "additionalProperties": False,
}


def coerce(kind: str, fields: list[dict], registry: dict) -> dict:
    """Validate + type-coerce an LLM row against the registry; drop unknowns."""
    allowed = registry.get(kind) or {}
    out: dict = {}
    for f in fields:
        name, raw = f.get("name"), str(f.get("value", "")).strip()
        if name not in allowed or not raw:
            continue
        t = allowed[name]
        try:
            if t == "number":
                v = float(raw.replace(",", ""))
                out[name] = int(v) if v.is_integer() else v
            elif t == "bool":
                if raw.lower() in ("true", "false"):
                    out[name] = raw.lower() == "true"
            elif t == "list" or name in LIST_FIELDS:
                items = [s.strip() for s in raw.split("|") if s.strip()]
                if items:
                    out[name] = sorted(items)
            else:
                out[name] = raw
        except ValueError:
            continue
    out["_kind"] = kind
    if not out.get("details"):
        out.pop("details", None)
    return out


def chunk_requests(rows: list[dict], registry: dict) -> list[dict]:
    """Batch API request payloads: rows grouped by brand, ROWS_PER_REQUEST each."""
    sysprompt = system_prompt(registry)
    by_brand: dict = defaultdict(list)
    for r in rows:
        by_brand[r["brand"]].append(r)
    requests = []
    for brand in sorted(by_brand):
        items = by_brand[brand]
        for i in range(0, len(items), ROWS_PER_REQUEST):
            chunk = items[i:i + ROWS_PER_REQUEST]
            body = "\n".join(f"{r['key']} | {r['kind']} | {r['brand']} | {r['text']}"
                             for r in chunk)
            requests.append({
                "custom_id": f"{brand}-{i // ROWS_PER_REQUEST}",
                "params": {
                    "model": MODEL,
                    "max_tokens": 8000,
                    "system": [{"type": "text", "text": sysprompt,
                                "cache_control": {"type": "ephemeral"}}],
                    "messages": [{"role": "user", "content": body}],
                    "output_config": {"format": {"type": "json_schema",
                                                 "schema": OUTPUT_SCHEMA}},
                },
            })
    return requests


def load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def pending_rows() -> tuple[list[dict], dict]:
    cache = load_cache()
    rows = [r for r in collect_rows() if r["key"] not in cache]
    return rows, cache


def cmd_plan():
    registry = load_registry()
    rows, cache = pending_rows()
    reqs = chunk_requests(rows, registry)
    sys_tokens = len(system_prompt(registry)) // 4
    in_tokens = sum(len(json.dumps(r)) for r in reqs) // 4
    print(f"cached rows: {len(cache)} | pending rows: {len(rows)} "
          f"| batch requests: {len(reqs)}")
    print(f"~system prompt: {sys_tokens} tok (cached across requests)")
    print(f"~input: {in_tokens / 1000:.0f}K tok, ~output: {len(rows) * 90 / 1000:.0f}K tok")
    est = (in_tokens / 1e6 * 2.5) + (len(rows) * 90 / 1e6 * 12.5)
    print(f"~cost at {MODEL} batch prices: ${est:.2f}")
    if reqs:
        print("\n--- sample request body (first 3 rows) ---")
        print(reqs[0]["params"]["messages"][0]["content"][:600])


def cmd_run():
    import anthropic
    client = anthropic.Anthropic()
    registry = load_registry()
    rows, cache = pending_rows()
    if not rows:
        print("[*] nothing pending — cache is complete")
        return
    by_key = {r["key"]: r for r in rows}
    reqs = chunk_requests(rows, registry)
    print(f"[*] submitting batch: {len(reqs)} requests / {len(rows)} rows", file=sys.stderr)
    batch = client.messages.batches.create(requests=reqs)
    print(f"[*] batch {batch.id}; polling...", file=sys.stderr)
    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        time.sleep(30)
    ok = parsed_n = errors = 0
    now = datetime.now(timezone.utc).isoformat()
    for result in client.messages.batches.results(batch.id):
        if result.result.type != "succeeded":
            errors += 1
            continue
        ok += 1
        msg = result.result.message
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except ValueError:
            errors += 1
            continue
        for row in data.get("rows", []):
            src = by_key.get(row.get("id"))
            if not src:
                continue
            parsed = coerce(src["kind"], row.get("fields") or [], registry)
            if len(parsed) <= 1:    # only _kind -> nothing extracted; keep regex
                continue
            cache[src["key"]] = {"kind": src["kind"], "brand": src["brand"],
                                 "text": src["text"], "parsed": parsed,
                                 "model": MODEL, "at": now}
            parsed_n += 1
    CACHE_PATH.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    print(f"[*] requests ok: {ok}, errored: {errors}; rows cached: {parsed_n}")
    print(f"[*] wrote {CACHE_PATH}")


def cmd_check_golden():
    """Contradictions between LLM parses and the golden corpus (shared fields
    with different values). The LLM may legitimately be RIGHT — review, then
    either fix the cache entry or regenerate the corpus."""
    cache = load_cache()
    by_kt = {(e["kind"], e["text"]): e["parsed"] for e in cache.values()}
    cases = json.loads(GOLDEN_PATH.read_text())
    n = miss = contra = 0
    for c in cases:
        llm = by_kt.get((c["kind"], c["text"]))
        if not llm:
            miss += 1
            continue
        n += 1
        for k, v in c["expected"].items():
            if k in ("details", "_kind"):
                continue
            if k in llm and llm[k] != v:
                contra += 1
                print(f"  {c['kind']:<12} {k:<16} regex={v!r} llm={llm[k]!r} "
                      f"| {c['text'][:55]}")
    print(f"\n[golden-vs-llm] compared {n} cases ({miss} not in cache); "
          f"contradicting field values: {contra}")


def _regex_yield(row: dict) -> int:
    """How many real fields the regex parser extracts for this row -- used to
    order the in-session extraction by expected lift (weak parses first)."""
    from parse_components import _resolver as res
    fn = res(row["kind"]) or res("_" + row["kind"])
    try:
        from parse_components import parse_component
        # NOTE: bypasses the LLM cache implicitly only when entry absent
        p = parse_component(row["kind"], row["text"], row["brand"]) or {}
    except Exception:  # noqa: BLE001
        p = {}
    return sum(1 for k, v in p.items()
               if k not in ("_kind", "details") and v not in (None, "", [], False))


def cmd_export_chunk(n: int, out: str):
    """Next N pending rows (weakest regex parses first) -> a work file for
    in-session extraction by Claude (no API key: the assistant parses the rows
    and feeds them back via --ingest, same wire format as the batch API)."""
    rows, cache = pending_rows()
    rows.sort(key=_regex_yield)
    chunk = rows[:n]
    Path(out).write_text(json.dumps(chunk, indent=1, ensure_ascii=False))
    print(f"[*] exported {len(chunk)} of {len(rows)} pending -> {out}")


def cmd_ingest(path: str):
    """Ingest [{'id': key, 'fields': [{'name','value'}...]}] -- the same wire
    format the batch API returns -- through the same registry validation."""
    registry = load_registry()
    cache = load_cache()
    by_key = {r["key"]: r for r in collect_rows()}
    data = json.loads(Path(path).read_text())
    now = datetime.now(timezone.utc).isoformat()
    n = skipped = 0
    for row in data:
        src = by_key.get(row.get("id"))
        if not src:
            skipped += 1
            continue
        parsed = coerce(src["kind"], row.get("fields") or [], registry)
        if len(parsed) <= 1 and row.get("fields"):
            skipped += 1   # fields were given but none validated -- recheck
            continue
        # explicit fields: [] means "reviewed, nothing extractable" (N/A rows,
        # junk-keyed values) -- cache {_kind} so the row is done and the UI
        # hides the empty component
        cache[src["key"]] = {"kind": src["kind"], "brand": src["brand"],
                             "text": src["text"], "parsed": parsed,
                             "model": "claude-in-session", "at": now}
        n += 1
    CACHE_PATH.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    pend = len([r for r in by_key.values() if r["key"] not in cache])
    print(f"[*] ingested {n} rows ({skipped} skipped); cache {len(cache)}; pending {pend}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--run", action="store_true")
    g.add_argument("--check-golden", action="store_true")
    g.add_argument("--rebuild-registry", action="store_true")
    g.add_argument("--export-chunk", type=int, metavar="N")
    g.add_argument("--ingest", metavar="PARSED_JSON")
    ap.add_argument("-o", "--out", default="/tmp/llm_chunk.json")
    args = ap.parse_args()
    if args.rebuild_registry:
        reg = build_registry()
        print(f"[*] registry: {sum(len(v) for v in reg.values())} fields "
              f"across {len(reg)} kinds -> {REGISTRY_PATH}")
    elif args.plan:
        cmd_plan()
    elif args.run:
        cmd_run()
    elif args.check_golden:
        cmd_check_golden()
    elif args.export_chunk:
        cmd_export_chunk(args.export_chunk, args.out)
    elif args.ingest:
        cmd_ingest(args.ingest)


if __name__ == "__main__":
    main()
