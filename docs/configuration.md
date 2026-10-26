# Configuration

## Environment (`.env` in the repo root)

| Variable | Used by | Default |
|---|---|---|
| `GEMINI_API_KEY` | scraper, backend | required for Gemini; without it the scraper uses Ollama only |
| `DATABASE_URL` | scraper, backend | `postgresql://board:board@localhost:5432/board` |
| `GEN_MODELS` | backend | `gemini-3.8-flash,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite` (cover letters, tips, CV parsing) |
| `EMBED_MODEL` | backend | `gemini-embedding-001` |

Changing `EMBED_MODEL` makes old vectors incomparable: clear `job_embeddings` and re-upload the CV.

## `scraper/config.yaml`

### Scraping

| Key | Meaning |
|---|---|
| `location`, `country_indeed` | JobSpy location settings (Germany) |
| `sites` | JobSpy boards: `indeed`, `linkedin`, `glassdoor` |
| `hours_old` | only postings from the last N hours (26 = daily run with some slack). `main.py --hours-old` overrides it for one run |
| `results_per_search` | results per term per JobSpy site |
| `linkedin_fetch_description` | fetch full LinkedIn descriptions (slower, much better classification) |
| `extra_sites` | `arbeitnow`, `stepstone`, `xing`, `jobware`, `fraunhofer` |
| `html_board_max_jobs` | postings fetched per term per HTML board |
| `google` | Google Jobs via JobSpy |
| `sleep_between_searches` | seconds between terms |
| `searches` | search terms per bucket (`working_student`, `internship`, `thesis`); the bucket is only a hint, the LLM decides |

### Arbeitsagentur (`arbeitsagentur:`)

| Key | Meaning |
|---|---|
| `enabled` | on/off |
| `days` | its own posting window (7); few new postings per term per day |
| `size` | results per search (max 100) |
| `fetch_details` | one extra request per new job for the full description |
| `extra_searches` | Arbeitsagentur-only searches run after the main terms; broad German terms ("Werkstudent IT") work best there |

### Startup sources

| Key | Meaning |
|---|---|
| `company_boards` | list of `{company, ats, slug}`; `ats` is `greenhouse`, `ashby`, `lever` or `personio`. Only student titles in Germany/remote are kept. The file explains how to find a company's slug |
| `berlinstartupjobs` | Berlin Startup Jobs RSS feed on/off |

### Filtering

| Key | Meaning |
|---|---|
| `reject_title_patterns` | case-insensitive regexes on the title, rejected before the LLM (Senior, Lead, Ausbildung, mid-level, ...) |
| `drop_categories` | `full_time`, `other` |
| `drop_seniority` | `mid`, `senior` |
| `drop_fields` | `other` (non-technical) |
| `expire_days` | delete jobs posted more than this many days ago (7) at the start of each run; tracked jobs are kept. Career-page jobs count from the day found, so an open role drops off and is found again |

### LLM

| Key | Meaning |
|---|---|
| `gemini.models` | tried best-first per job |
| `gemini.rpm` | requests/minute per model, just under the free-tier quota; raise if billing is enabled |
| `gemini.max_workers` | parallel requests |
| `gemini.spill_after_s` | if a model's next free slot is further away, use the next model |
| `gemini.cooldown_s` | how long to skip a rate-limited or overloaded model |
| `gemini.timeout_s`, `gemini.max_description_chars` | request timeout, description length sent |
| `ollama.host`, `ollama.model` | local fallback (`qwen2.5:3b`) |

`profile` is no longer used: classification is profile-free and matching uses the uploaded CV.

Free-tier limits measured on our key (Oct 2026): 3.8-flash 20 requests/day, 3.5-flash 5/min,
3.5-flash-lite and 3.1-flash-lite 15/min, gemma-4-26b no limit hit at 30/min; embeddings
100 texts/min, 30,000 tokens/min, 1,000 requests/day.

## Backend constants

- `backend/matching.py`: `MATCH_LOW`, `MATCH_HIGH` map cosine similarity to the 0-100 match.
- `backend/ai.py`: the cover letter and tips prompts (`COVER_SYSTEM`, `TIPS_SYSTEM`).
