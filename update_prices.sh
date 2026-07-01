#!/usr/bin/env bash
#
# Standalone component-PRICE refresh — independent of brand scraping. Refreshes per-part
# retail prices (key-free Worldwide Cyclery scrape) for parts that are UNRESOLVED or whose
# researched price is older than PRICE_MAX_AGE_DAYS, then rebuilds + publishes the active
# build via the shared offline pipeline. It does NOT re-scrape any brand or touch the
# per-brand scrape returns (data/current/*_ebikes.json) — only the price cache + catalog.
#
# Usage:
#   ./update_prices.sh                     # default: unresolved + researched > 60 days
#   PRICE_MAX_AGE_DAYS=90 ./update_prices.sh
#   ./update_prices.sh --all               # re-price every in-use part
#   ./update_prices.sh --date 01/01/2026   # explicit cutoff (+ --categories b,f / --limit N)
#
# Cron (independent of run_scrape.sh, e.g. monthly):
#   0 5 1 * *  /home/bblashill/ebike-compare/update_prices.sh
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
LOG="$PROJECT_DIR/logs/prices.log"
mkdir -p "$PROJECT_DIR/logs"

refresh() {
    echo "===== $(date -Is) : starting component-price refresh ====="
    if [ "$#" -gt 0 ]; then
        # Explicit selection args (--all / --date / --categories / --limit) forwarded as-is.
        "$PROJECT_DIR/rebuild_offline.sh" --refresh-prices "$@"
    else
        # Default scope: unresolved + researched prices older than N days.
        local cutoff
        cutoff="$(date -d "${PRICE_MAX_AGE_DAYS:-60} days ago" +%m/%d/%Y)"
        echo "$(date -Is) : default scope = unresolved + researched before $cutoff"
        "$PROJECT_DIR/rebuild_offline.sh" --refresh-prices --date "$cutoff"
    fi
    local rc=$?
    echo "===== $(date -Is) : price refresh complete (rc=$rc) ====="
    echo
    return $rc
}

refresh "$@" >> "$LOG" 2>&1
exit $?
