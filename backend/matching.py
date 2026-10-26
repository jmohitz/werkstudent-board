"""Resume -> structured profile + embedding; jobs -> embeddings (background); cosine-similarity ranking."""
import hashlib
import io
import logging
import threading
import time
from typing import Literal

import numpy as np
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from pypdf import PdfReader

import llm
from db import query

logger = logging.getLogger("matching")

# Cosine similarity of gemini-embedding-001 vectors sits in a narrow band; these map it to a
# readable 0-100 "match". Calibrated on 810 jobs with a data/AI-student CV: 1st percentile 0.60
# (chemistry/physics theses), median 0.665, 97th 0.727, best 0.744.
MATCH_LOW, MATCH_HIGH = 0.60, 0.75


# ---------- resume ----------

class Language(BaseModel):
    language: str
    level: str = Field(description="e.g. native, C1, B2, A2, basic, fluent")


class ResumeProfile(BaseModel):
    name: str | None = None
    headline: str = Field(description="One line, e.g. 'MSc Computer Science student focused on data engineering'")
    degree: str | None = None
    field_of_study: str | None = None
    university: str | None = None
    expected_graduation: str | None = None
    skills: list[str] = Field(description="Most important technical skills first, max 25")
    experience: list[str] = Field(description="One short line per role/project: role, organisation, key tech. Max 8")
    languages: list[Language]
    german_level: Literal["none", "A1", "A2", "B1", "B2", "C1", "C2", "native", "unknown"]
    target_roles: list[str] = Field(description="Kinds of roles this person fits best, max 6")
    summary: str = Field(description="3-4 sentences on strengths and focus")


RESUME_SYSTEM = """You read a CV (German or English) and extract a structured profile.
Use only what the CV says; never invent skills, dates or levels.
german_level: if the CV gives a range like "A2/B1", use the lower level; "fluent"/"verhandlungssicher" = C1;
"Muttersprache"/"native" = native; if German isn't mentioned at all, use "unknown".
Write all output in English."""


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif name.endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
    else:
        raise ValueError("Upload a PDF (or a .txt/.md file)")
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(text) < 200:
        raise ValueError("Could not read enough text from this file. Is it a scanned image? Export it as a text PDF.")
    return text


def profile_text(p: dict) -> str:
    return "\n".join([
        p.get("headline") or "", p.get("summary") or "",
        "Skills: " + ", ".join(p.get("skills") or []),
        "Target roles: " + ", ".join(p.get("target_roles") or []),
        "Experience: " + "; ".join(p.get("experience") or []),
    ])


def save_resume(filename: str, data: bytes) -> dict:
    text = extract_text(filename, data)
    profile, model = llm.generate(f"CV:\n{text[:20000]}", RESUME_SYSTEM, schema=ResumeProfile,
                                  models=llm.FAST_MODELS)
    profile = profile.model_dump()
    vec = llm.embed([profile_text(profile)], "RETRIEVAL_QUERY")[0]
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    query(
        """INSERT INTO resume (id, filename, text, text_hash, profile, embedding, uploaded_at)
           VALUES (1, %s, %s, %s, %s, %s, now())
           ON CONFLICT (id) DO UPDATE SET filename = EXCLUDED.filename, text = EXCLUDED.text,
               text_hash = EXCLUDED.text_hash, profile = EXCLUDED.profile,
               embedding = EXCLUDED.embedding, uploaded_at = now()""",
        (filename, text, text_hash, Jsonb(profile), vec),
    )
    logger.info(f"resume saved ({len(text)} chars, profile by {model})")
    return get_resume()


def get_resume() -> dict | None:
    rows = query("SELECT filename, text, text_hash, profile, embedding, uploaded_at FROM resume WHERE id = 1")
    return rows[0] if rows else None


def delete_resume():
    query("DELETE FROM resume")
    query("DELETE FROM job_ai")  # generated for that resume


# ---------- job embeddings (background) ----------

class _Cache:
    """All job vectors in memory, L2-normalised, so scoring a few thousand jobs is one matrix product."""

    def __init__(self):
        self.lock = threading.Lock()
        self.vecs: dict[int, np.ndarray] = {}
        self.loaded = False

    def load(self):
        rows = query("SELECT job_id, embedding FROM job_embeddings")
        with self.lock:
            self.vecs = {r["job_id"]: _unit(r["embedding"]) for r in rows}
            self.loaded = True

    def add(self, ids, vectors):
        with self.lock:
            for i, v in zip(ids, vectors):
                self.vecs[i] = _unit(v)


cache = _Cache()
status = {"running": False, "last_error": None}


def _unit(v) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(a)
    return a / n if n else a


def _job_text(r: dict) -> str:
    return "\n".join(x for x in [
        r["title"], f"{(r['category'] or '').replace('_', ' ')} · {(r['field'] or '').replace('_', ' ')}",
        r["summary"] or "", "Stack: " + ", ".join(r["stack"] or []), (r["description"] or "")[:1500],
    ] if x)


def embed_missing_batch() -> int:
    rows = query(
        """SELECT j.id, j.title, j.category, j.field, j.summary, j.stack, j.description
           FROM jobs j LEFT JOIN job_embeddings e ON e.job_id = j.id
           WHERE e.job_id IS NULL
           -- daily quota is limited: jobs with the full classification and description first
           ORDER BY (j.classified_by IS NULL), coalesce(j.date_posted, j.date_found) DESC, j.id DESC
           LIMIT %s""",
        (llm.EMBED_BATCH,),
    )
    # keep the batch under the per-minute token quota (~4 characters per token)
    texts, budget = [], llm.EMBED_TOKENS_PER_BATCH
    for r in rows:
        t = _job_text(r)
        budget -= len(t) // 4 + 8
        if budget < 0 and texts:
            break
        texts.append(t)
    rows = rows[:len(texts)]
    if not rows:
        return 0
    vectors = llm.embed(texts, "RETRIEVAL_DOCUMENT")
    ids = [r["id"] for r in rows]
    for i, v in zip(ids, vectors):
        query(
            "INSERT INTO job_embeddings (job_id, model, embedding) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (i, llm.EMBED_MODEL, v),
        )
    cache.add(ids, vectors)
    return len(rows)


def _embed_loop():
    status["running"] = True
    while True:
        try:
            if not cache.loaded:
                cache.load()
            n = embed_missing_batch()
            status["last_error"] = None
            time.sleep(61 if n else 120)  # free tier: 100 texts/min
        except llm.RateLimited as e:
            if e.daily:  # daily free-tier quota: don't hammer it, check again in an hour
                status["last_error"] = "daily embedding quota used up; resuming later"
                time.sleep(3600)
            else:
                time.sleep(65)
        except Exception as e:
            status["last_error"] = str(e)[:200]
            logger.warning(f"embedding batch failed: {e}")
            time.sleep(120)


def start_background_embedding():
    threading.Thread(target=_embed_loop, name="job-embedder", daemon=True).start()


def embedding_progress() -> dict:
    r = query("SELECT (SELECT count(*) FROM jobs) AS total, (SELECT count(*) FROM job_embeddings) AS embedded")[0]
    return {**r, **status}


# ---------- scoring ----------

def match_scores(resume_vec, job_ids: list[int]) -> dict[int, int]:
    """job_id -> 0-100 match for the jobs that have an embedding."""
    if resume_vec is None or not job_ids:
        return {}
    if not cache.loaded:
        cache.load()
    q = _unit(resume_vec)
    with cache.lock:
        have = [i for i in job_ids if i in cache.vecs]
        if not have:
            return {}
        sims = np.stack([cache.vecs[i] for i in have]) @ q
    pct = np.clip((sims - MATCH_LOW) / (MATCH_HIGH - MATCH_LOW), 0, 1) * 100
    return {i: int(round(p)) for i, p in zip(have, pct)}
