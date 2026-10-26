"""Sample dataset for a read-only public demo (run the backend with DEMO_MODE=1).

  export:  python scripts/demo_data.py export [N]   -> db/demo_jobs.json (N newest classified jobs, default 150)
  import:  python scripts/demo_data.py import        -> loads it into DATABASE_URL (e.g. the demo host's DB)

Full descriptions are left out on purpose: a public demo should show what the board does, not
republish other sites' posting text. Titles, companies, tags and links to the original posting stay.
Uses the backend's virtualenv (psycopg): backend/.venv/bin/python scripts/demo_data.py ...
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://board:board@localhost:5432/board")
FILE = Path(__file__).parent.parent / "db" / "demo_jobs.json"
COLUMNS = ["job_url", "title", "company", "location", "city", "site", "date_posted", "date_found",
           "category", "field", "seniority", "german_required", "work_mode", "stack", "hours_per_week",
           "summary", "classified_by"]


def export(n: int):
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM jobs WHERE classified_by IS NOT NULL "
            "ORDER BY coalesce(date_posted, date_found) DESC, id DESC LIMIT %s", (n,)).fetchall()
    FILE.write_text(json.dumps(rows, default=str, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(rows)} jobs to {FILE}")


def load():
    rows = json.loads(FILE.read_text(encoding="utf-8"))
    today = date.today().isoformat()  # shift dates so the demo looks fresh and nothing expires at once
    with psycopg.connect(DATABASE_URL) as conn:
        for r in rows:
            r["date_posted"], r["date_found"] = None, today
            conn.execute(
                f"INSERT INTO jobs ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))}) "
                "ON CONFLICT DO NOTHING", [r[c] for c in COLUMNS])
    print(f"loaded {len(rows)} jobs into {DATABASE_URL.rsplit('@', 1)[-1]}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        export(int(sys.argv[2]) if len(sys.argv) > 2 else 150)
    elif cmd == "import":
        load()
    else:
        sys.exit(__doc__)
