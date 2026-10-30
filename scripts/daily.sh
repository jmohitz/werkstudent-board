#!/bin/sh
# Daily job: scrape, then record history and rebuild the analytics tables.
# The snapshot runs after the scrape, before the next run's 7-day expiry deletes anything.
# Used by the launchd schedule in docs/operations.md; also fine to run by hand.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/scraper" && .venv/bin/python main.py "$@"

if [ -x "$ROOT/analytics/.venv/bin/dbt" ]; then
  cd "$ROOT/analytics" && export DBT_PROFILES_DIR=. &&
    .venv/bin/dbt snapshot && .venv/bin/dbt build
fi
