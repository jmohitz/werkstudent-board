# Architecture

Three parts share one Postgres database:

| Part | Runs | Does |
|---|---|---|
| `scraper/` | once a day (or on demand) | finds postings, classifies them, saves them, expires old ones |
| `backend/` | while you use the board | JSON API, resume matching, cover letters/tips, serves `frontend/` |
| `frontend/` | in the browser | the board UI (plain HTML/CSS/JS) |

## Scraper pipeline

`scraper/main.py` runs these steps:

1. **Expire** jobs posted more than `expire_days` (7) ago, except jobs you track in the application tracker.
2. **Load known jobs** (URLs and title+company) from the database and CSV backups, so nothing is
   classified twice.
3. **For each search** (`config.yaml` `searches`, then Arbeitsagentur-only searches, then the startup
   sources):
   1. scrape every source for the term **in parallel**, each site at its own pace (a failing source is
      logged and skipped)
   2. drop known jobs and in-run duplicates
   3. drop titles matching `reject_title_patterns` (Senior, Lead, Ausbildung, ...) without an LLM call
   4. **classify** the rest in parallel (see below)
   5. drop `full_time` / `other` categories, `mid` / `senior` seniority and non-technical (`other`) fields
   6. **save** right away to Postgres and to `output/*.csv`, so a crash or network outage never loses
      finished searches

### Sources

| Source | How | Notes |
|---|---|---|
| LinkedIn, Indeed, Glassdoor | [JobSpy](https://github.com/speedyapply/JobSpy) | Glassdoor/LinkedIn sometimes rate-limit (429) |
| Google Jobs | JobSpy | currently returns nothing; kept, failures are skipped |
| Arbeitsagentur | documented public Jobsuche API (`/pc/v6/jobs`, details via `/pc/v4/jobdetails`) | own 7-day window + 20 broad German extra searches |
| Arbeitnow | public JSON API | ignores search terms, so it's read once per run and filtered to student titles |
| Jooble | official REST API (`JOOBLE_API_KEY`) | short snippets only; the free key has 500 requests in total, capped per run |
| StepStone | the search page's embedded result JSON (title, company, date, snippet) | posting pages time out for scripts, so they aren't fetched |
| Xing, Jobware, Fraunhofer | search page + each posting's schema.org `JobPosting` data (JSON-LD or microdata) | best-effort HTML; up to 35 new postings per term, known ones skipped before fetching |
| Startup career pages | public ATS feeds: Greenhouse, Ashby, Lever, Personio | 26 companies; only student titles in Germany/remote are kept |
| Berlin Startup Jobs | official RSS feed (engineering) | mostly full-time, filtered out later |

Not included: Jobvector and DFKI (Cloudflare challenge), get-in-it.de (filters only client-side, few
student roles), JobTeaser university portals (login required). Blocks are never worked around.

### Classification (`scraper/classify.py`)

Each job's title, company, location, a keyword hint from the title and up to 4,000 characters of the
description go to an LLM, which must answer with a fixed JSON schema:

`category`, `seniority`, `field` (14 values), `german_required`, `work_mode`, `city`,
`hours_per_week`, `stack` (≤ 8), `summary` (one sentence).

It is **profile-free**: it describes the job, it does not judge fit. Backends, tried in order per job:

1. **Gemini models** from `gemini.models`, best first. Free-tier quotas are per model, so each model
   is throttled to its own requests-per-minute and a busy model hands the job to the next one; the
   quotas add up (~25 jobs/min). A model over its daily quota is skipped for the rest of the run.
2. **Ollama** (`qwen2.5:3b`), local, if every Gemini model is unavailable.
3. **Keyword fallback**: category from the title, everything else unknown.

Guards: output length is capped and requests time out (small models can loop forever inside a JSON
string), and a clear title ("Werkstudent ...") overrides a model that says full-time or senior.
`classified_by` records which backend labelled each job.

## Database (`db/init.sql`)

| Table | Holds |
|---|---|
| `jobs` | one row per posting; `dedupe_key` (title + company + city, case-insensitive) is unique, so the same job from two sites is stored once |
| `applications` | your tracker status per job; tracked jobs never expire |
| `resume` | the uploaded CV (single row): text, extracted profile, embedding |
| `job_embeddings` | one vector per job for matching |
| `job_ai` | cached cover letters and resume tips per job, language and resume version |

`relevance` and `reason` in `jobs` are legacy (from profile-based scoring) and empty for new rows.

## Backend (`backend/`)

- `app.py`: routes (see [API](api.md)); serves `frontend/` with `Cache-Control: no-cache`.
- `llm.py`: Gemini client, generation with a model fallback chain, embeddings.
- `matching.py`:
  - **Resume**: PDF/text -> plain text -> Gemini extracts a structured profile (skills, experience,
    languages, German level, target roles) -> embedded as the query vector.
  - **Jobs**: a background thread embeds jobs without a vector (`gemini-embedding-001`, 768 dims),
    newest fully-classified jobs first, batches sized under the free tier's 30k tokens/min, pausing
    for an hour when the 1,000/day quota is used up.
  - **Scoring**: cosine similarity between the resume and each job, mapped to 0-100
    (`MATCH_LOW`/`MATCH_HIGH`, calibrated on this board). Jobs without a vector sort last.
- `ai.py`: resume tips (structured: fit level, strengths, gaps, CV edits, keywords, interview prep) and
  cover letters (plain text, English/German, 250-350 words). Prompts only allow facts from the CV.
  Results are cached in `job_ai`.

## Frontend (`frontend/`)

No framework and no build step. `insights.html` reads `/api/insights`, which selects from the dbt
marts (see [analytics/README.md](../analytics/README.md)). `app.js` keeps the filter state, calls `/api/jobs` and `/api/stats`,
renders the list, the sidebar filters, the resume block and the job detail panel.
