# Werkstudent Board

A personal job board for **Werkstudent, internship and thesis roles in Germany** in software, data and AI/ML.

A daily scraper collects postings from job boards, the Arbeitsagentur and startup career pages,
an LLM describes each one (job type, field, German required, stack, ...), and a small web app lets
you filter them, rank them against your CV, track applications and draft cover letters.

```
 job boards ─┐
 Arbeitsagentur ─┼─▶ scraper ─▶ Gemini / Ollama ─▶ Postgres ─▶ FastAPI ─▶ web board
 career pages ─┘   (daily)      (classify)                    (+ matching, cover letters)
```

## Features

- **~140 searches per run** across LinkedIn, Indeed, Glassdoor, Xing, StepStone, Jobware, Arbeitnow,
  Fraunhofer, the Arbeitsagentur, 26 startup career pages and Berlin Startup Jobs
- **Profile-free classification** with Gemini (several models, each kept under its free quota), local
  Ollama as fallback; full-time, mid/senior and non-technical roles are dropped
- **Board** in a dense, dark, foorilla-style UI: filters for category, posting date, field, source,
  work mode and German requirement, plus search over title, company, stack and summary
- **Resume matching**: upload your CV, jobs get a match % and a "Best match" sort
- **Per-job help**: resume tips (fit, strengths, gaps, concrete CV edits) and a tailored cover letter in
  English or German, using only facts from your CV
- **Application tracker**: saved / applied / interview / offer / rejected
- **Housekeeping**: cross-site duplicates are merged, jobs older than 20 days expire (tracked ones stay)

## Quick start

Requirements: Docker, Python 3.12+, a [Gemini API key](https://aistudio.google.com/apikey) (free tier
works) and, optionally, [Ollama](https://ollama.com) as a local fallback.

```bash
# 1. database
docker compose up -d

# 2. API key
cp .env.example .env            # then put your key in .env

# 3. scraper
cd scraper
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ollama pull qwen2.5:3b          # optional fallback model
.venv/bin/python main.py        # first run: a few hours (see docs/operations.md)
cd ..

# 4. board
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/uvicorn app:app --app-dir backend --port 8000
```

Open <http://localhost:8000>, upload your CV in the sidebar and switch the sort to **Best match**.

## Repository layout

```
scraper/      daily pipeline: scrape -> classify -> save (Python)
  main.py       entry point (--hours-old, --only)
  scrape.py     all sources
  classify.py   Gemini/Ollama classification
  db.py         Postgres writes, expiry
  config.yaml   search terms, sources, models, filters
backend/      FastAPI app: API, resume matching, cover letters; serves the frontend
frontend/     plain HTML/CSS/JS board, no build step
db/           schema (init.sql) and migrations
docs/         architecture, configuration, API, operations
```

## Documentation

- [Architecture](docs/architecture.md): how the pipeline, database, matching and AI features fit together
- [Configuration](docs/configuration.md): every setting in `scraper/config.yaml` and the environment
- [API](docs/api.md): the HTTP endpoints the frontend uses
- [Operations](docs/operations.md): daily runs, quotas, migrations, troubleshooting

## Notes

- **Personal use.** Postings are collected from public pages and official/public APIs and feeds. HTML
  scrapers are best-effort and can break when a site changes; sources that block automated access are
  not worked around. Check each site's terms before relying on it.
- **Privacy.** Your CV and job postings are sent to Google Gemini. On the free tier Google may use this
  data to improve its products. The API key lives in `.env`, which is git-ignored.
- **AI output is a draft.** Read and edit cover letters and tips before using them.
