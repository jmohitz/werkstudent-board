# Operations

## Running the scraper

```bash
cd scraper
.venv/bin/python main.py                        # full run (~140 searches)
.venv/bin/python main.py --hours-old 72         # look back 3 days for JobSpy sources
.venv/bin/python main.py --only thesis          # only searches containing "thesis"
.venv/bin/python main.py --only startups        # once-per-run sources: career pages, Berlin Startup Jobs, Arbeitnow
.venv/bin/python main.py --only arbeitsagentur  # only the Arbeitsagentur extra searches
.venv/bin/python main.py --sources stepstone,xing # all terms, only these sources (comma-separated)
```

Within each term the sources run in parallel (they are different sites); each site keeps its own pace
(`site_gap_s`), so no site gets more than one request at a time. A term takes about 25-40 s plus
classification, so a daily run takes roughly 1-1.5 hours; after a long break (many new jobs) the
Gemini quotas make classification the slow part. Already-known jobs are skipped before classification, so repeat runs stay cheap on the LLM
side. Logs go to the console and `scraper/output/run.log`.

On macOS run it under `caffeinate -i` so the machine doesn't idle-sleep. Closing the lid or losing
Wi-Fi still interrupts requests: the run survives (sources fail softly, classification falls back to
Ollama), but that hour's results are thin.

## Running the board

```bash
docker compose up -d
backend/.venv/bin/uvicorn app:app --app-dir backend --port 8000   # add --reload while developing
```

The backend embeds new jobs in the background while it runs, so keep it running for a while after a
scrape for "Best match" to cover the new jobs.

## Daily schedule (macOS, launchd)

`scripts/daily.sh` runs the scraper and then `dbt snapshot && dbt build`, so the insights page and the
job history stay current. cron skips runs while the Mac sleeps; launchd catches up after wake. Save as
`~/Library/LaunchAgents/de.werkstudent-board.scrape.plist` (adjust the path), then
`launchctl load ~/Library/LaunchAgents/de.werkstudent-board.scrape.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>de.werkstudent-board.scrape</string>
  <key>WorkingDirectory</key><string>/Users/YOU/projects/werkstudent-board</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>/Users/YOU/projects/werkstudent-board/scripts/daily.sh</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/tmp/werkstudent-board-scrape.log</string>
  <key>StandardErrorPath</key><string>/tmp/werkstudent-board-scrape.log</string>
</dict></plist>
```

Docker (the database) must be running at that time. Without the dbt setup (`analytics/.venv`), the
script only scrapes.

## Database migrations

A fresh database (empty Docker volume) is created from `db/init.sql`, which includes everything.
An existing database is upgraded by applying the migrations in order:

```bash
docker exec -i board-db psql -U board -d board < db/migrations/001_dedupe_jobs.sql
docker exec -i board-db psql -U board -d board < db/migrations/002_classification_and_tracker.sql
docker exec -i board-db psql -U board -d board < db/migrations/003_resume_matching_ai.sql
```

## Quotas (Gemini free tier)

| What | Limit | Effect |
|---|---|---|
| Classification | per model per minute (see [configuration](configuration.md)) | throttled; spills over to other models, then Ollama |
| `gemini-3.8-flash` | 20 requests/day | used up early; cover letters and tips fall back to 3.5-flash |
| Embeddings | 100 texts/min, 30k tokens/min, 1,000 requests/day | backlog clears over a few days; unmatched jobs sort last and the sidebar says so |

Enabling billing on the key removes most of this; raise `gemini.rpm` accordingly.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Arbeitsagentur `403 No match found` | the old `/pc/v4/jobs` route; search must use `/pc/v6/jobs` (already done) |
| "Matching ready for X of Y" doesn't grow | daily embedding quota used up; resumes the next day (~09:00 CET) |
| Cover letter/tips: "All Gemini models are busy" | per-minute or daily quota; try again in a minute or tomorrow |
| Gemini calls fail with `nodename nor servname provided` | no network (Wi-Fi or sleep); the run continues on Ollama |
| Scrape seems stuck on one term | a hanging HTTP request during a network drop; it resumes when the connection is back |
| Frontend changes don't show | hard-reload once (Cmd+Shift+R); the server now sends `no-cache` |
| Names like `KÃ¶ster` | encoding from pages without a charset; fixed in the scraper, old rows were repaired |
| `[stepstone] result JSON not found` | StepStone changed its search page layout; `_stepstone()` in `scrape.py` needs the new marker |
| `[jooble] no results` for every term after the first 20 | expected: `jooble_max_requests` per run is used up (the free key has 500 in total) |
| Insights page: "Run `dbt build` ... first" | the marts don't exist yet; run `dbt build` in `analytics/` |
| Ollama hangs | output is capped (`num_predict`) and timed out; if it still stalls, `ollama stop qwen2.5:3b` |

## Public demo

A read-only demo is safer than hosting the real board: it doesn't republish scraped posting text and
doesn't expose the Gemini-backed features.

```bash
# on your machine: export ~150 recent jobs (title, company, tags, link; no descriptions)
backend/.venv/bin/python scripts/demo_data.py export 150      # -> db/demo_jobs.json (git-ignored)

# on the demo host: fresh database from db/init.sql, then
DATABASE_URL=postgresql://... backend/.venv/bin/python scripts/demo_data.py import
DEMO_MODE=1 DATABASE_URL=postgresql://... backend/.venv/bin/uvicorn app:app --app-dir backend --port 8000
```

`DEMO_MODE=1` blocks every non-GET request to the resume, tracker and AI endpoints (403), turns off
background embedding, and the frontend hides those controls and shows a demo note.

### Recording a 1-2 minute video instead

On macOS: QuickTime Player -> File -> New Screen Recording (or Cmd+Shift+5), record the browser window.
A good flow: the board and filters (10 s) -> upload a sample CV and switch to Best match (20 s) ->
open a job, Analyse fit, Write cover letter (40 s) -> set a status in the tracker (10 s). Use a sample
CV rather than your real one if the video will be public.
