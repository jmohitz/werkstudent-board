"""API for the job board. Reads jobs from Postgres, ranks them against your resume, generates cover
letters / resume tips, and serves the frontend.

Run:  uvicorn app:app --reload --port 8000   (from backend/)
"""
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import ai
import llm
import matching
from db import query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
FRONTEND = Path(__file__).parent.parent / "frontend"
MAX_UPLOAD = 5 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    matching.start_background_embedding()  # embeds jobs that don't have a vector yet, ~90/min
    yield


app = FastAPI(title="Werkstudent Board", lifespan=lifespan)


@app.middleware("http")
async def no_stale_frontend(request: Request, call_next):
    # make browsers re-check index.html / app.js / style.css on every load, so changes show up
    # without a hard refresh (they still get a fast 304 when nothing changed)
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

POSTED = "coalesce(j.date_posted, j.date_found)"  # some sites give no posting date
# posted filter -> (from N days ago, to N days ago), both inclusive
POSTED_RANGES = {
    "today": (0, 0),
    "yesterday": (1, 1),
    "3d": (3, 0),
    "7d": (7, 0),
    "30d": (30, 0),
}
STATUSES = ("saved", "applied", "interview", "offer", "rejected")
# career-page feeds are stored per ATS ("careers:greenhouse", ...) but filtered as one source
SOURCE = "CASE WHEN j.site LIKE 'careers:%%' THEN 'careers' ELSE j.site END"
LIST_COLUMNS = f"""j.id, j.title, j.company, j.location, j.city, j.site, j.category, j.field,
    j.seniority, j.german_required, j.work_mode, j.stack, j.summary, j.hours_per_week,
    j.job_url, {POSTED} AS posted, a.status"""
JOINS = "FROM jobs j LEFT JOIN applications a ON a.job_id = j.id"


def posted_bounds(key: str) -> tuple[date, date]:
    # "today" is the machine's local date, not the DB container's (UTC)
    start, end = POSTED_RANGES[key]
    today = date.today()
    return today - timedelta(days=start), today - timedelta(days=end)


def _resume_or_409() -> dict:
    resume = matching.get_resume()
    if not resume:
        raise HTTPException(409, "Upload your resume first")
    return resume


def _job_or_404(job_id: int) -> dict:
    rows = query(f"SELECT {LIST_COLUMNS}, j.description, j.job_url_direct {JOINS} WHERE j.id = %s", (job_id,))
    if not rows:
        raise HTTPException(404, "job not found")
    return rows[0]


@app.get("/api/jobs")
def list_jobs(
    category: str | None = None,
    field: str | None = None,
    work_mode: str | None = None,
    site: str | None = Query(None, description="source, e.g. linkedin, xing, arbeitsagentur, careers"),
    posted: str | None = Query(None, description="today, yesterday, 3d, 7d or 30d"),
    english_only: bool = Query(False, description="hide jobs that require German"),
    status: str | None = Query(None, description="tracked (any status) or one application status"),
    q: str | None = Query(None, description="Search title, company, stack and summary"),
    sort: Literal["newest", "match"] = "newest",
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    where, params = ["TRUE"], []
    for col, val in (("category", category), ("field", field), ("work_mode", work_mode)):
        if val:
            where.append(f"j.{col} = %s")
            params.append(val)
    if site:
        where.append(f"{SOURCE} = %s")
        params.append(site)
    if posted in POSTED_RANGES:
        where.append(f"{POSTED} BETWEEN %s AND %s")
        params += list(posted_bounds(posted))
    if english_only:
        where.append("j.german_required IS DISTINCT FROM TRUE")  # keeps "no" and "unclear"
    if status == "tracked":
        where.append("a.status IS NOT NULL")
    elif status in STATUSES:
        where.append("a.status = %s")
        params.append(status)
    if q:
        where.append(
            "(j.title ILIKE %s OR j.company ILIKE %s OR j.summary ILIKE %s"
            " OR array_to_string(j.stack, ' ') ILIKE %s)"
        )
        params += [f"%{q}%"] * 4
    cond = " AND ".join(where)
    resume = matching.get_resume()
    resume_vec = resume["embedding"] if resume else None

    if sort == "match" and resume_vec is not None:
        # score every matching job, then page through them best-first (unscored jobs last, newest first)
        ids = [r["id"] for r in query(f"SELECT j.id {JOINS} WHERE {cond} ORDER BY {POSTED} DESC, j.id DESC", params)]
        scores = matching.match_scores(resume_vec, ids)
        ranked = sorted(ids, key=lambda i: -scores.get(i, -1))  # stable: keeps newest-first among ties
        page = ranked[offset:offset + limit]
        rows = {r["id"]: r for r in query(f"SELECT {LIST_COLUMNS} {JOINS} WHERE j.id = ANY(%s)", (page,))}
        jobs = [rows[i] for i in page if i in rows]
        total = len(ids)
    else:
        jobs = query(
            f"SELECT {LIST_COLUMNS} {JOINS} WHERE {cond} ORDER BY {POSTED} DESC, j.id DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        total = query(f"SELECT count(*) AS n {JOINS} WHERE {cond}", params)[0]["n"]
        scores = matching.match_scores(resume_vec, [j["id"] for j in jobs])
    for j in jobs:
        j["match"] = scores.get(j["id"])
    return {"total": total, "jobs": jobs}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int):
    job = _job_or_404(job_id)
    resume = matching.get_resume()
    job["match"] = matching.match_scores(resume["embedding"], [job_id]).get(job_id) if resume else None
    job["posting_language"] = ai.posting_language(job)
    return job


@app.get("/api/stats")
def stats():
    def group(col: str) -> list[dict]:
        return query(
            f"SELECT {col} AS key, count(*) AS n FROM jobs WHERE {col} IS NOT NULL "
            f"GROUP BY {col} ORDER BY n DESC"
        )

    counts, params = [], []
    for key in POSTED_RANGES:
        counts.append(f"count(*) FILTER (WHERE {POSTED} BETWEEN %s AND %s) AS \"{key}\"")
        params += list(posted_bounds(key))
    by_posted = query(f"SELECT {', '.join(counts)} FROM jobs j", params)[0]
    by_status = query("SELECT status AS key, count(*) AS n FROM applications GROUP BY status")
    return {
        "total": query("SELECT count(*) AS n FROM jobs")[0]["n"],
        "by_category": group("category"),
        "by_field": group("field"),
        "by_work_mode": group("work_mode"),
        "by_site": query(f"SELECT {SOURCE} AS key, count(*) AS n FROM jobs j WHERE j.site IS NOT NULL "
                         f"GROUP BY 1 ORDER BY n DESC"),
        "by_posted": by_posted,
        "by_status": {r["key"]: r["n"] for r in by_status},
        "embeddings": matching.embedding_progress(),
    }


# ---------- application tracker ----------

class ApplicationIn(BaseModel):
    status: Literal[STATUSES]
    notes: str | None = None


@app.put("/api/applications/{job_id}")
def set_application(job_id: int, body: ApplicationIn):
    """Track a job: create or update its status. applied_at is set the first time it is 'applied'."""
    rows = query(
        """INSERT INTO applications (job_id, status, notes, applied_at)
           SELECT %(id)s, %(status)s, %(notes)s,
                  CASE WHEN %(status)s = 'applied' THEN CURRENT_DATE END
           WHERE EXISTS (SELECT 1 FROM jobs WHERE id = %(id)s)
           ON CONFLICT (job_id) DO UPDATE SET
               status     = EXCLUDED.status,
               notes      = coalesce(EXCLUDED.notes, applications.notes),
               applied_at = coalesce(applications.applied_at, EXCLUDED.applied_at),
               updated_at = now()
           RETURNING job_id, status, notes, applied_at""",
        {"id": job_id, "status": body.status, "notes": body.notes},
    )
    if not rows:
        raise HTTPException(404, "job not found")
    return rows[0]


@app.delete("/api/applications/{job_id}", status_code=204)
def clear_application(job_id: int):
    """Stop tracking a job (it can then expire normally)."""
    query("DELETE FROM applications WHERE job_id = %s", (job_id,))


# ---------- resume, matching, AI help ----------

def _public_resume(r: dict) -> dict:
    return {"filename": r["filename"], "uploaded_at": r["uploaded_at"], "profile": r["profile"]}


@app.get("/api/resume")
def get_resume():
    """The uploaded resume, or null if none (200 either way, so the page doesn't log an error)."""
    resume = matching.get_resume()
    return _public_resume(resume) if resume else None


@app.post("/api/resume")
async def upload_resume(file: UploadFile = File(...)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 5 MB)")
    try:
        resume = await run_in_threadpool(matching.save_resume, file.filename or "resume.pdf", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    return _public_resume(resume)


@app.delete("/api/resume", status_code=204)
def delete_resume():
    matching.delete_resume()


@app.post("/api/jobs/{job_id}/cover-letter")
def cover_letter(job_id: int, lang: Literal["auto", "en", "de"] = "auto", refresh: bool = False):
    job, resume = _job_or_404(job_id), _resume_or_409()
    try:
        return ai.cover_letter(job, resume, lang, refresh)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))


@app.post("/api/jobs/{job_id}/tips")
def resume_tips(job_id: int, refresh: bool = False):
    job, resume = _job_or_404(job_id), _resume_or_409()
    try:
        return ai.tips(job, resume, refresh)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))


# Mounted last so /api/* routes take precedence
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
