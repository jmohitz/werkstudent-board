"""Per-job AI help: a tailored cover letter and resume tips, from the uploaded resume + the posting.
Results are cached in job_ai per (job, kind, language, resume version)."""
import re
from typing import Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

import llm
from db import query

COVER_SYSTEM = """You write cover letters for students applying to Werkstudent, internship and thesis positions in Germany.

Rules:
- Use ONLY facts from the CV. Never invent experience, skills, grades, dates or motivation the CV doesn't support.
- Only say a tool or skill was used in a specific job or project if the CV lists it under that job or project;
  skills from a general "Skills" list may be mentioned as skills, not as things done in a particular role.
- If the posting asks for something the CV doesn't show, don't claim it; lean on related, real experience instead.
- No generic soft-skill claims (teamwork, structured working style, eagerness to learn) unless the CV shows
  them; let the concrete experience speak instead.
- Be specific: connect 2-3 concrete CV items to the posting's actual tasks and stack. No generic filler.
- 250-350 words. Plain text, no markdown, no placeholders like [Company] - use the real names given.
- Structure: greeting, why this role/company (from the posting), 2 short paragraphs of evidence from the CV,
  availability (hours/start date only if the CV states them), closing, the candidate's name.
- German: formal "Sie", start with "Sehr geehrte Damen und Herren," unless the posting names a contact person,
  end with "Mit freundlichen Grüßen". English: "Dear Hiring Team," ... "Kind regards,"."""

TIPS_SYSTEM = """You are a careers advisor for computer science students in Germany. Compare the CV with the job
posting and say honestly how well it fits and what to change in the CV for THIS application.

Rules:
- Base everything on the CV text and the posting. Never suggest adding skills or experience the candidate
  doesn't have; for gaps, suggest how to show related real experience or what to learn.
- resume_changes must be concrete edits ("Move the Airflow pipeline project to the top and name the data
  volume", not "highlight your skills").
- keywords: terms from the posting the candidate can truthfully include.
- Write in English."""


class JobTips(BaseModel):
    match_level: Literal["strong", "good", "partial", "weak"]
    fit_summary: str = Field(description="2-3 sentences: overall fit and the main reason")
    strengths: list[str] = Field(description="CV points that match the posting, max 6")
    gaps: list[str] = Field(description="Requirements the CV doesn't show, max 6")
    resume_changes: list[str] = Field(description="Concrete CV edits for this application, max 8")
    keywords: list[str] = Field(description="Posting terms to include if truthful, max 12")
    interview_prep: list[str] = Field(description="Topics to prepare for an interview, max 4")


_DE = set("und der die das wir sie für mit eine einer ist bei unser unsere werden du ihr deine aufgaben "
          "kenntnisse erfahrung studium".split())
_EN = set("and the we you for with our are will your is an of to tasks experience skills".split())


def posting_language(job: dict) -> str:
    words = re.findall(r"[a-zäöüß]+", ((job.get("title") or "") + " " + (job.get("description") or "")).lower())
    de = sum(w in _DE for w in words)
    en = sum(w in _EN for w in words)
    return "de" if de > en else "en"


def _job_block(job: dict) -> str:
    return (
        f"Job title: {job['title']}\nCompany: {job.get('company') or 'unknown'}\n"
        f"Location: {job.get('city') or job.get('location') or 'unknown'}\n"
        f"Type: {job.get('category')}\nStack: {', '.join(job.get('stack') or [])}\n\n"
        f"Posting:\n{(job.get('description') or job.get('summary') or '(no description stored)')[:8000]}"
    )


def _cached(job_id: int, kind: str, lang: str, resume_hash: str):
    rows = query(
        "SELECT content, model, created_at FROM job_ai WHERE job_id=%s AND kind=%s AND lang=%s AND resume_hash=%s",
        (job_id, kind, lang, resume_hash),
    )
    return rows[0] if rows else None


def _store(job_id: int, kind: str, lang: str, resume_hash: str, model: str, content):
    query(
        """INSERT INTO job_ai (job_id, kind, lang, resume_hash, model, content) VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (job_id, kind, lang, resume_hash)
           DO UPDATE SET model = EXCLUDED.model, content = EXCLUDED.content, created_at = now()""",
        (job_id, kind, lang, resume_hash, model, Jsonb(content)),
    )


def cover_letter(job: dict, resume: dict, lang: str = "auto", refresh: bool = False) -> dict:
    lang = posting_language(job) if lang == "auto" else lang
    if not refresh and (hit := _cached(job["id"], "cover_letter", lang, resume["text_hash"])):
        return {"text": hit["content"]["text"], "lang": lang, "model": hit["model"], "cached": True}
    prompt = (f"Write the cover letter in {'German' if lang == 'de' else 'English'}.\n\n"
              f"CV:\n{resume['text'][:15000]}\n\n---\n{_job_block(job)}")
    text, model = llm.generate(prompt, COVER_SYSTEM, max_tokens=2048)
    _store(job["id"], "cover_letter", lang, resume["text_hash"], model, {"text": text})
    return {"text": text, "lang": lang, "model": model, "cached": False}


def tips(job: dict, resume: dict, refresh: bool = False) -> dict:
    if not refresh and (hit := _cached(job["id"], "tips", "", resume["text_hash"])):
        return {**hit["content"], "model": hit["model"], "cached": True}
    prompt = f"CV:\n{resume['text'][:15000]}\n\n---\n{_job_block(job)}"
    result, model = llm.generate(prompt, TIPS_SYSTEM, schema=JobTips)
    content = result.model_dump()
    _store(job["id"], "tips", "", resume["text_hash"], model, content)
    return {**content, "model": model, "cached": False}
