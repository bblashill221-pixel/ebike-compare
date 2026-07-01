#!/usr/bin/env bash
#
# Offline rebuild of data/current/active/ebike.json from the existing
# per-brand scrape returns (data/current/*_ebikes.json) + curated artifacts
# (data/curated/*) — the compute tail only, NO scraping and NO network
# enrichment. This is the "safe regen" subset: deterministic and reproducible,
# useful for iterating on normalize/analyze or rebuilding after editing a curated
# override without re-hitting every brand site.
#
# Promotes the result to web/public/ only if validate_build.py passes, so a known
# good build isn't replaced by a broken one.
#
# Usage:  ./rebuild_offline.sh [--refresh-prices [scrape-args...]]
#
#   --refresh-prices   Before folding prices, run the component-price network refresh
#                      (resolve_component_prices.py scrape). Any args after it are
#                      forwarded to that subcommand (e.g. --date MM/DD/YYYY, --all,
#                      --categories ..., --limit N). Without this flag the rebuild is
#                      fully offline / cache-only (no network) — the default.
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"
[ -x "$PY" ] || PY=python3

# Parse: --refresh-prices toggles the price network step; everything else is forwarded
# to `resolve_component_prices.py scrape`.
REFRESH_PRICES=0
SCRAPE_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --refresh-prices) REFRESH_PRICES=1 ;;
        *) SCRAPE_ARGS+=("$1") ;;
    esac
    shift
done

run() { echo "--- $(date -Is) : $1"; "$PY" "$PROJECT_DIR/$1" "${@:2}"; }

run normalize.py
run component_catalog.py
# Optional NETWORK price refresh: scrape Worldwide Cyclery for due parts (unresolved
# always; researched re-checked per the forwarded --date/--all). Runs here so it sees the
# freshly rebuilt catalog's in-use parts. Skipped by default (offline / cache-only).
if [ "$REFRESH_PRICES" = 1 ]; then
    run resolve_component_prices.py scrape "${SCRAPE_ARGS[@]}"
fi
# Fold the catalog's component retail prices (researched or brand/spec estimate) into the
# freshly rebuilt catalog so analyze.py's value roll-up picks them up. No network.
run resolve_component_prices.py write-catalog
run analyze.py
run audit.py
# Correctness triage (advisory): flag likely-misclassified / misparsed bikes.
run audit_anomalies.py
# Per-scraper key/icon-field audit -> data/audits/<brand>.json (offline: refresh the
# resolution logs from this build; the resolver's network passes are opt-in via
# `audit_scrapers.py --resolve`).
run audit_scrapers.py

if "$PY" "$PROJECT_DIR/validate_build.py"; then
    run diff_changes.py
    # Rewrite the active build with the content-addressed `components` table + refs
    # (every component once, priced, linked to the catalog). Runs AFTER the readers
    # above (which use inline specs) and before the web payload.
    run intern_components.py
    # Emit the SLIM web payload (drops dead fields + minifies; the components table +
    # refs pass through) rather than copying the full record verbatim.
    run slim_web_build.py
    # the QA page (/qa) fetches anomalies.json from web/public — promote it too so
    # the triage list stays in sync with the data, not stale from a prior build
    cp "$PROJECT_DIR/data/current/anomalies.json" \
       "$PROJECT_DIR/web/public/anomalies.json"
    echo "$(date -Is) : validated + promoted to web/public/"
else
    echo "$(date -Is) : validation FAILED — web/public/ left untouched (last-good kept)" >&2
    exit 1
fi
