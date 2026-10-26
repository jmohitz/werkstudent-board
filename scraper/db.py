import ast
import os
from datetime import date, timedelta

import pandas as pd
import psycopg

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://board:board@localhost:5432/board"
)

COLUMNS = [
    "job_url", "job_url_direct", "title", "company", "location", "site",
    "date_posted", "category", "field", "german_required", "relevance",
    "reason", "search_term", "date_found",
    "seniority", "work_mode", "city", "stack", "hours_per_week", "summary",
    "description", "classified_by",
]


def _clean(value):
    """Turn pandas' empty values (NaN, NaT, '') into None, which becomes NULL in SQL."""
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _to_bool(value):
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes"):
            return True
        if v in ("false", "0", "no"):
            return False
        return None  # the classifier's "unclear" -> NULL, not "no German needed"
    return bool(value)


def _to_list(value):
    """stack: a Python list from the classifier, or its string form when read back from a CSV."""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()] or None
    value = _clean(value)
    if value is None:
        return None
    try:
        parsed = ast.literal_eval(value)
        return _to_list(parsed) if isinstance(parsed, (list, tuple)) else None
    except (ValueError, SyntaxError):
        return None


def _to_date(value):
    value = _clean(value)
    if value is None:
        return None
    try:
        return pd.to_datetime(value).date()
    except (ValueError, TypeError):
        return None


def _to_int(value):
    value = _clean(value)
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


CONVERTERS = {
    "german_required": _to_bool,
    "date_posted": _to_date,
    "date_found": _to_date,
    "relevance": _to_int,
    "hours_per_week": _to_int,
    "stack": _to_list,
}


def save_jobs(df: pd.DataFrame) -> int:
    """Insert jobs into Postgres and return how many were new.

    Skipped: jobs whose URL already exists, and the same job from another site
    (same title + company + city, enforced by the dedupe_key unique index).
    """
    if df is None or df.empty:
        return 0

    cols = [c for c in COLUMNS if c in df.columns]
    rows = [
        tuple(CONVERTERS.get(c, _clean)(row[c]) for c in cols)
        for _, row in df.iterrows()
        if _clean(row.get("job_url")) and _clean(row.get("title"))
    ]

    placeholders = ", ".join(["%s"] * len(cols))
    sql = (
        f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders}) "
        # no conflict target: skip on ANY unique violation (job_url or dedupe_key)
        "ON CONFLICT DO NOTHING"
    )

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
            return max(cur.rowcount, 0)

def load_seen() -> pd.DataFrame:
    """job_url, title, company of every job already in the database."""
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute("SELECT job_url, title, company FROM jobs").fetchall()
    return pd.DataFrame(rows, columns=["job_url", "title", "company"])


def delete_expired(days: int) -> int:
    """Delete jobs posted more than `days` ago. Jobs you track in `applications` are kept."""
    cutoff = date.today() - timedelta(days=days)  # local date, not the DB container's UTC date
    with psycopg.connect(DATABASE_URL) as conn:
        return conn.execute(
            """DELETE FROM jobs j
               WHERE coalesce(j.date_posted, j.date_found) < %s
                 AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.job_id = j.id)""",
            (cutoff,),
        ).rowcount
