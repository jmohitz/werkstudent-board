# Job Radar

Daily scraper for Werkstudent / internship / thesis jobs in Germany.
JobSpy scrapes → a small Ollama model categorises → CSV → Streamlit page.

```
config.yaml    search terms, sites, model, your profile
scrape.py      JobSpy wrapper + dedup across sites
classify.py    Ollama structured output (JSON schema) + keyword fallback
main.py        daily pipeline, writes output/jobs_<date>.csv and output/all_jobs.csv
app.py         Streamlit frontend
```

## Setup
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
ollama pull qwen2.5:3b
python main.py                     # first run
streamlit run app.py               # browse results
```

## Output columns
`date_found, category, field, relevance (1-5), german_required, title, company, location, site, date_posted, job_url, job_url_direct, reason, search_term`

## Run daily in the morning
The machine must be on and Ollama running at that time.

**Linux / macOS (cron)** – `crontab -e`:
```
30 7 * * * cd /path/to/job-radar && .venv/bin/python main.py >> output/run.log 2>&1
```
(On macOS, a sleeping laptop skips cron jobs; launchd with `StartCalendarInterval` catches up after wake.)

**Windows (Task Scheduler)**: Create Basic Task → Daily 07:30 → Action "Start a program":
- Program: `C:\path\to\job-radar\.venv\Scripts\python.exe`
- Arguments: `main.py`
- Start in: `C:\path\to\job-radar`
Tick "Run task as soon as possible after a scheduled start is missed".

## Tuning tips
- Add/remove search terms in `config.yaml`; German terms (Werkstudent, Praktikum, Masterarbeit) find far more than English ones.
- LinkedIn rate-limits fast; if you see 429 errors, lower `results_per_search` or raise `sleep_between_searches`.
- If the 3B model mislabels too much, try `qwen2.5:7b` (slower but noticeably better).
- Runtime: ~1–3 s per job on CPU for a 3B model; only new jobs are classified each day.
