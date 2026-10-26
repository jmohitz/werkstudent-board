# Operations

## Running the scraper

```bash
cd scraper
.venv/bin/python main.py                        # full run (~140 searches)
.venv/bin/python main.py --hours-old 72         # look back 3 days for JobSpy sources
.venv/bin/python main.py --only thesis          # only searches containing "thesis"
.venv/bin/python main.py --only startups        # only the startup career pages + Berlin Startup Jobs
.venv/bin/python main.py --only arbeitsagentur  # only the Arbeitsagentur extra searches
```

A full run takes about 3-5 hours, mostly scraping (each term is searched on every source with polite
pauses). Already-known jobs are skipped before classification, so repeat runs stay cheap on the LLM
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

cron skips runs while the Mac sleeps; launchd catches up after wake. Save as
`~/Library/LaunchAgents/de.werkstudent-board.scrape.plist` (adjust the path), then
`launchctl load ~/Library/LaunchAgents/de.werkstudent-board.scrape.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>de.werkstudent-board.scrape</string>
  <key>WorkingDirectory</key><string>/Users/YOU/projects/werkstudent-board/scraper</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>/Users/YOU/projects/werkstudent-board/scraper/.venv/bin/python</string><string>main.py</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/tmp/werkstudent-board-scrape.log</string>
  <key>StandardErrorPath</key><string>/tmp/werkstudent-board-scrape.log</string>
</dict></plist>
```

Docker (the database) must be running at that time.

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
| Ollama hangs | output is capped (`num_predict`) and timed out; if it still stalls, `ollama stop qwen2.5:3b` |

## Legacy

`scraper/app.py` (Streamlit) and `scraper/import_csv.py` are from the first CSV-based version.
The board in `frontend/` replaces the Streamlit app.
