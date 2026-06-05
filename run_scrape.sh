#!/usr/bin/env bash
#
# Cron-friendly wrapper for the e-bike scrapers (Aventon + Lectric + Ride1Up +
# Specialized + Velotric + Heybike + Mokwheel + EVELO + Himiway + Euphree + Vvolt
# + Blix + Tern).
# For each scraper it:
#   - runs it with the project's venv,
#   - writes the latest result to <brand>_ebikes.json,
#   - archives a dated snapshot to data/<brand>_ebikes_YYYY-MM-DD.json,
#   - appends stdout/stderr to logs/scrape.log.
# One scraper failing does not stop the other; the script exits non-zero if any
# scraper failed.
#
# Usage:  ./run_scrape.sh
# Cron:   0 6 * * 1  /home/bblashill/ebike-compare/run_scrape.sh
#
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PY="$PROJECT_DIR/.venv/bin/python"
STAMP="$(date +%F)"                        # YYYY-MM-DD
LOG="$PROJECT_DIR/logs/scrape.log"
# Snapshots: the newest per brand lives in data/current/, older ones in data/legacy/.
CURRENT_DIR="$PROJECT_DIR/data/current"
LEGACY_DIR="$PROJECT_DIR/data/legacy"
mkdir -p "$CURRENT_DIR" "$LEGACY_DIR" "$PROJECT_DIR/logs"

# scraper script | output basename | extra args
SCRAPERS=(
    "scrape_aventon.py|aventon_ebikes|--concurrency 4"
    "scrape_lectric.py|lectric_ebikes|"
    "scrape_ride1up.py|ride1up_ebikes|"
    "scrape_specialized.py|specialized_ebikes|--concurrency 3"
    "scrape_velotric.py|velotric_ebikes|"
    "scrape_heybike.py|heybike_ebikes|"
    "scrape_mokwheel.py|mokwheel_ebikes|"
    "scrape_evelo.py|evelo_ebikes|"
    "scrape_himiway.py|himiway_ebikes|"
    "scrape_euphree.py|euphree_ebikes|"
    "scrape_vvolt.py|vvolt_ebikes|"
    "scrape_blix.py|blix_ebikes|"
    "scrape_tern.py|tern_ebikes|"
)

run_all() {
    local rc=0
    echo "===== $(date -Is) : starting scrape run ====="
    for entry in "${SCRAPERS[@]}"; do
        IFS='|' read -r script base args <<< "$entry"
        local latest="$PROJECT_DIR/data/${base}.json"
        local archive="$CURRENT_DIR/${base}_${STAMP}.json"
        echo "--- $(date -Is) : $script ---"
        if "$PY" "$PROJECT_DIR/$script" -o "$latest" $args; then
            # Rotate any prior current snapshot(s) for this brand into legacy/,
            # then write the new one to current/ (current/ = newest per brand).
            for prev in "$CURRENT_DIR/${base}_"*.json; do
                [ -e "$prev" ] && [ "$prev" != "$archive" ] && mv -f "$prev" "$LEGACY_DIR/"
            done
            cp "$latest" "$archive"
            echo "$(date -Is) : OK -> $latest  (snapshot: $archive)"
        else
            echo "$(date -Is) : FAILED -> $script"
            rc=1
        fi
    done
    # Fill any missing per-model warranty (brand-level policy) and refresh the
    # component cost estimates from the final data.
    echo "--- $(date -Is) : fill_warranty + shipping/accessories + component costs ---"
    "$PY" "$PROJECT_DIR/fill_warranty.py" || true
    "$PY" "$PROJECT_DIR/enrich_shipping_accessories.py" || true
    "$PY" "$PROJECT_DIR/add_geometry.py" || true
    "$PY" "$PROJECT_DIR/add_configurations.py" || true
    "$PY" "$PROJECT_DIR/add_config_colors.py" || true
    "$PY" "$PROJECT_DIR/add_available_options.py" || true
    "$PY" "$PROJECT_DIR/add_pricing.py" || true
    # Normalize unifies all brands AND does the detailed spec grouping + component
    # parsing into ebikes_normalized.json (the single transform step).
    "$PY" "$PROJECT_DIR/normalize.py" || true
    # Metrics last: BOM cost estimates, then the typed-fact + scoring analysis layer.
    "$PY" "$PROJECT_DIR/estimate_component_costs.py" \
        -o "$PROJECT_DIR/data/component_cost_estimates.json" || true
    "$PY" "$PROJECT_DIR/analyze.py" || true
    echo "===== $(date -Is) : run complete (rc=$rc) ====="
    echo
    return $rc
}

run_all >> "$LOG" 2>&1
exit $?
