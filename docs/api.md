# API

Served by `backend/app.py` on <http://localhost:8000>. Interactive docs: <http://localhost:8000/docs>.

`GET /api/config` returns `{"demo": true|false}`. In demo mode (`DEMO_MODE=1`) every non-GET request
to the resume, tracker and AI endpoints returns `403`.

## Jobs

### `GET /api/jobs`

| Param | Values |
|---|---|
| `category` | `working_student`, `internship`, `thesis` |
| `field` | e.g. `data_engineering`, `ai_llm`, `software_engineering` |
| `work_mode` | `remote`, `hybrid`, `onsite`, `unclear` |
| `site` | source, e.g. `linkedin`, `xing`, `arbeitsagentur`, `careers` (all startup career pages) |
| `posted` | `today`, `yesterday`, `3d`, `7d`, `30d` (posting date, else the date found) |
| `english_only` | `true` hides jobs that require German (keeps "unclear") |
| `status` | `tracked` or an application status |
| `q` | text search in title, company, summary and stack |
| `sort` | `newest` (default) or `match` (needs an uploaded CV) |
| `limit`, `offset` | paging, `limit` ≤ 500 |

Returns `{"total": n, "jobs": [...]}`; each job has `match` (0-100 or null) and `status`.

### `GET /api/jobs/{id}`

One job including `description`, `job_url_direct`, `match` and `posting_language` (`de`/`en`).

### `GET /api/stats`

Counts for the sidebar: `total`, `by_category`, `by_field`, `by_work_mode`, `by_site`, `by_posted`,
`by_status`, and `embeddings` (`embedded`, `total`, `last_error`).

## Application tracker

- `PUT /api/applications/{job_id}` with `{"status": "saved|applied|interview|offer|rejected", "notes": "..."}`
  creates or updates; `applied_at` is set the first time the status is `applied`.
- `DELETE /api/applications/{job_id}` stops tracking.

## Resume

- `GET /api/resume`: the uploaded CV's filename, upload time and extracted profile, or `null`.
- `POST /api/resume`: multipart upload (`file`): PDF, `.txt` or `.md`, max 5 MB. Replaces the old one.
- `DELETE /api/resume`: removes it and all cached cover letters and tips.

## AI help (needs an uploaded CV)

- `POST /api/jobs/{id}/tips?refresh=false`: fit level, summary, strengths, gaps, CV edits, keywords,
  interview topics.
- `POST /api/jobs/{id}/cover-letter?lang=auto|en|de&refresh=false`: `{"text", "lang", "model", "cached"}`.
  `auto` uses the posting's language.

Both are cached per job (and language) and resume version; `refresh=true` regenerates. They return
`503` with a message when every Gemini model is busy or over quota, `409` without a CV.
