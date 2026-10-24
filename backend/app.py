"""API for the job board. Reads jobs from Postgres and serves the frontend.

Run:  uvicorn app:app --reload --port 8000   (from backend/)
"""
import os
from pathlib import Path

import psycopg
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://board:board@localhost:5432/board"
)
FRONTEND = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="Werkstudent Board")


def query(sql: str, params: list) -> list[dict]:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


@app.get("/api/jobs")
def list_jobs(
    category: str | None = None,
    q: str | None = Query(None, description="Search in title and company"),
    min_relevance: int = 0,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    where, params = ["coalesce(relevance, 0) >= %s"], [min_relevance]
    if category:
        where.append("category = %s")
        params.append(category)
    if q:
        where.append("(title ILIKE %s OR company ILIKE %s)")
        params += [f"%{q}%"] * 2
    cond = " AND ".join(where)

    jobs = query(
        f"""SELECT id, title, company, location, site, category, field, german_required,
                   relevance, job_url, coalesce(date_posted, date_found) AS posted
            FROM jobs WHERE {cond}
            ORDER BY coalesce(date_posted, date_found) DESC, relevance DESC NULLS LAST, id DESC
            LIMIT %s OFFSET %s""",
        params + [limit, offset],
    )
    total = query(f"SELECT count(*) AS n FROM jobs WHERE {cond}", params)[0]["n"]
    return {"total": total, "jobs": jobs}


@app.get("/api/stats")
def stats():
    rows = query("SELECT category, count(*) AS n FROM jobs GROUP BY category ORDER BY n DESC", [])
    return {"total": sum(r["n"] for r in rows), "by_category": rows}


# Mounted last so /api/* routes take precedence
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
