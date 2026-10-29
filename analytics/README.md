# Analytics (dbt)

A [dbt](https://docs.getdbt.com/) project on top of the board's Postgres. The scraper loads raw
jobs; dbt turns them into tested, documented tables for the [insights page](../frontend/insights.html)
(`/insights.html`, served by `GET /api/insights`).

```
public.jobs, public.applications          (written by the scraper and the app)
  └─ staging       stg_jobs, stg_applications           views: rename, clean, classifier bucket
      └─ intermediate  int_job_skills                    view: one row per (job, skill)
          └─ marts     mart_jobs_daily, mart_skills_demand, mart_companies, mart_sources  tables
  └─ snapshots     jobs_snapshot                         history that survives the 7-day expiry
      └─ marts     mart_jobs_history
```

Everything is built into separate schemas (`analytics_staging`, `analytics_intermediate`,
`analytics_marts`, `analytics_snapshots`), so dbt never touches the app's tables.

## Setup

dbt doesn't support Python 3.14 yet, so it has its own 3.12 environment:

```bash
cd analytics
uv venv -p 3.12 .venv && uv pip install -p .venv dbt-postgres
export DBT_PROFILES_DIR=.     # profiles.yml lives in this folder
.venv/bin/dbt debug           # checks the connection
```

`profiles.yml` reads `DBT_HOST`, `DBT_USER` and `DBT_PASSWORD`, falling back to the local Docker defaults.

## Daily use

Run after each scrape, snapshot first:

```bash
.venv/bin/dbt snapshot        # record new, changed and expired jobs
.venv/bin/dbt build           # build all models and run all tests
.venv/bin/dbt source freshness  # warns if the scraper hasn't added jobs for 2 days
```

The snapshot only records what it sees, so run it before jobs expire (the scraper deletes jobs
older than 7 days at the start of each run).

Useful selectors: `-s stg_jobs+` (a model and everything downstream), `-s +mart_companies`
(everything it needs), `-s test_type:singular`.

## Docs

```bash
.venv/bin/dbt docs generate && .venv/bin/dbt docs serve --port 8081
```

Model and column descriptions, compiled SQL and the lineage graph.

## Tests

- Generic tests in `models/*/_*.yml`: `unique`/`not_null` keys, `accepted_values` for classifier
  output, a `relationships` check from applications to jobs, and a grain test on `mart_jobs_daily`.
- Singular tests in `tests/`: `assert_no_future_postings` catches broken date parsing.
