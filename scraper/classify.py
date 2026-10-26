"""LLM layer: describes each job posting (type, field, seniority, language, stack...).

Profile-free: it only says what the job IS; matching jobs to a person is a separate step.

Backends, tried in order for every job:
  gemini  the models listed in config, best first, in parallel. Each model is throttled to its
          own per-minute quota and a busy one hands the job to the next, so quotas add up.
          A model that hits its daily quota is skipped for the rest of the run; one that is
          rate-limited or overloaded is skipped for `cooldown_s`.
  ollama  local fallback, so a run never stops because of the API
  keyword last resort: category from the title, everything else unknown
"""
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("classify")
logging.getLogger("google_genai").setLevel(logging.WARNING)  # it logs every internal retry at INFO

CATEGORIES = ("working_student", "internship", "thesis", "full_time", "other")
FIELDS = (
    "software_engineering", "web_frontend", "mobile", "embedded_systems",
    "data_engineering", "data_analytics_bi", "data_science_ml", "ai_llm",
    "devops_cloud", "security", "qa_testing", "sap_erp", "research", "other",
)


class JobLabel(BaseModel):
    category: Literal[CATEGORIES]
    seniority: Literal["entry", "junior", "mid", "senior"]
    field: Literal[FIELDS]
    german_required: Literal["yes", "no", "unclear"]
    work_mode: Literal["remote", "hybrid", "onsite", "unclear"]
    city: str | None = Field(None, description="Main German city of the job, null if unknown or remote-only")
    hours_per_week: int | None = Field(None, description="Weekly hours if stated, else null")
    stack: list[str] = Field(default_factory=list, description="Up to 8 key technologies, e.g. Python, AWS, React")
    summary: str = Field(description="One English sentence, max 25 words, what the person will actually do")


SYSTEM = """You extract structured facts from job postings in Germany (German or English). Answer only with JSON matching the schema.

category:
- working_student: Werkstudent / working student / studentische Hilfskraft / HiWi (part-time while studying)
- internship: Praktikum / internship / Pflichtpraktikum / Praxissemester
- thesis: Bachelor/Master thesis, Abschlussarbeit
- full_time: regular employment, trainee, graduate or junior position (not for students)
- other: Ausbildung/apprenticeship, freelance, PhD/doctoral or research-assistant posts, non-technical roles
seniority: entry for student roles; junior / mid / senior from the required experience for anything else.
field: the main technical area. Use "other" for non-technical roles (sales, HR, marketing, finance...).
german_required: "yes" if fluent or good German is required or the posting is written only in German without
  mentioning English; "no" if English is enough; otherwise "unclear".
work_mode: remote, hybrid or onsite as stated; "unclear" if not stated.
Use only information from the posting; do not guess hours or city."""

# Cheap keyword rules: a hint for the LLM and the last-resort fallback.
RULES = [
    ("thesis", r"\b(masterarbeit|bachelorarbeit|abschlussarbeit|thesis)\b"),
    ("working_student", r"\b(werkstudent\w*|working student|studentische\w* (hilfskraft|mitarbeit\w*)|hiwi)\b"),
    ("internship", r"\b(praktik\w*|pflichtpraktikum|intern|internship|praxissemester)\b"),
]
STUDENT_CATEGORIES = {"working_student", "internship", "thesis"}


def keyword_hint(title: str) -> str | None:
    t = (title or "").lower()
    for cat, pattern in RULES:
        if re.search(pattern, t):
            return cat
    return None


def _text(v) -> str:
    # Missing values arrive from pandas as NaN (a float), which `x or ""` doesn't catch
    return v if isinstance(v, str) else ""


class RateLimited(Exception):
    """429 or 503. `daily` = the free-tier/plan quota for the day is used up."""

    def __init__(self, msg: str):
        super().__init__(msg)
        self.daily = "PerDay" in msg


class GeminiBackend:
    def __init__(self, model: str, gc: dict):
        from google import genai
        from google.genai import types

        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set (put it in the repo's .env)")
        self.client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(
                timeout=gc.get("timeout_s", 30) * 1000,
                # one quick retry only; on overload we'd rather move to the next backend than wait
                retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1, max_delay=4),
            ),
        )
        self.model = model
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=JobLabel,
            temperature=0,
            max_output_tokens=gc.get("max_output_tokens", 1024),
            # "minimal" is rejected by gemini-3.8-flash; "low" works on Gemini models.
            # Gemma models reject any thinking setting.
            thinking_config=None if model.startswith("gemma")
            else types.ThinkingConfig(thinking_level=gc.get("thinking_level", "low")),
        )
        self.paused_until = 0.0  # monotonic time; inf = daily quota gone for this run
        # client-side throttle to stay under the per-minute quota (free tier: 15/min)
        self.interval = 60 / gc.get("rpm", {}).get(model, gc.get("default_rpm", 14))
        self._next_slot = 0.0
        self._slot_lock = threading.Lock()

    def reserve(self, max_wait: float) -> bool:
        """Book the next request slot if it is at most `max_wait` seconds away, then wait for it.
        False = this model is busy; the caller moves on to the next model instead of queueing."""
        with self._slot_lock:
            slot = max(time.monotonic(), self._next_slot)
            if slot - time.monotonic() > max_wait:
                return False
            self._next_slot = slot + self.interval
        time.sleep(max(0.0, slot - time.monotonic()))
        return True

    def label(self, prompt: str) -> JobLabel:
        from google.genai import errors

        try:
            resp = self.client.models.generate_content(model=self.model, contents=prompt, config=self.config)
        except errors.APIError as e:
            if e.code in (429, 503):  # rate limit / quota / "model experiencing high demand"
                raise RateLimited(str(e)) from e
            raise
        if resp.parsed is None:
            raise ValueError(f"no parsable JSON (finish reason: {resp.candidates[0].finish_reason if resp.candidates else '?'})")
        return resp.parsed


class OllamaBackend:
    def __init__(self, oc: dict):
        from ollama import Client

        # timeout: a stuck request fails over to the keyword fallback instead of hanging the run
        self.client = Client(host=oc["host"], timeout=oc.get("timeout_s", 120))
        self.model = oc["model"]
        self.max_tokens = oc.get("max_output_tokens", 400)
        self.schema = JobLabel.model_json_schema()

    def label(self, prompt: str) -> JobLabel:
        resp = self.client.chat(
            model=self.model,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            format=self.schema,
            # num_predict: small models sometimes loop inside a JSON string forever; a valid
            # label is ~150-250 tokens, so cut off long before that becomes a hang
            # (truncated JSON fails validation -> keyword fallback)
            options={"temperature": 0, "num_predict": self.max_tokens},
            think=False,  # qwen3: skip the reasoning trace, we only want the JSON
        )
        return JobLabel.model_validate_json(resp.message.content)


class Classifier:
    def __init__(self, cfg: dict):
        gc, oc = cfg.get("gemini", {}), cfg["ollama"]
        self.max_chars = gc.get("max_description_chars", 4000)
        self.workers = gc.get("max_workers", 8)
        self.cooldown = gc.get("cooldown_s", 60)
        self.spill_after = gc.get("spill_after_s", 2)
        self.ollama = OllamaBackend(oc)
        self.geminis: list[GeminiBackend] = []
        if gc.get("enabled", True):
            try:
                self.geminis = [GeminiBackend(m, gc) for m in gc.get("models", ["gemini-3.8-flash"])]
            except Exception as e:
                logger.warning(f"Gemini unavailable, using Ollama only: {e}")
        self._lock = threading.Lock()
        self.stats = {"keyword": 0, "ollama": 0, **{g.model: 0 for g in self.geminis}}

    def _pause(self, g: GeminiBackend, err: RateLimited):
        with self._lock:
            now = time.monotonic()
            if err.daily:
                if g.paused_until != float("inf"):
                    logger.warning(f"{g.model}: daily quota used up, not using it again this run")
                g.paused_until = float("inf")
            elif now >= g.paused_until:  # log once per cooldown
                logger.warning(f"{g.model}: rate-limited or overloaded, pausing {self.cooldown}s")
                g.paused_until = now + self.cooldown

    def _label(self, prompt: str, title: str):
        """Try each Gemini model in order, then Ollama. Returns (label, source) or (None, None).

        Quotas are per model, so a busy model (next free slot > spill_after_s away) is skipped for
        the next one: the models' per-minute limits add up instead of everyone queueing on the
        first. The last available model is always waited for rather than falling to Ollama."""
        available = [g for g in self.geminis if time.monotonic() >= g.paused_until]
        for i, g in enumerate(available):
            last = i == len(available) - 1
            if not g.reserve(max_wait=float("inf") if last else self.spill_after):
                continue
            try:
                return g.label(prompt), g.model
            except RateLimited as e:
                self._pause(g, e)
            except Exception as e:
                logger.warning(f"{g.model} failed for '{title}', trying next: {str(e)[:150]}")
        try:
            return self.ollama.label(prompt), "ollama"
        except Exception as e:
            logger.warning(f"Ollama failed for '{title}', keyword fallback: {e}")
        return None, None

    def classify(self, title, company, location, description) -> dict:
        title, company, location, description = map(_text, (title, company, location, description))
        hint = keyword_hint(title)
        prompt = (
            f"Job title: {title}\nCompany: {company}\nLocation: {location}\n"
            f"Keyword hint from title: {hint or 'none'}\n\n"
            f"Description:\n{description[: self.max_chars] or '(no description)'}"
        )

        label, source = self._label(prompt, title)
        with self._lock:
            self.stats[source or "keyword"] += 1
        if label is None:
            return {
                "category": hint or "other", "seniority": "entry" if hint else None, "field": "other",
                "german_required": "unclear", "work_mode": "unclear", "city": None,
                "hours_per_week": None, "stack": [], "summary": None, "classified_by": "keyword",
            }

        out = label.model_dump()
        out["stack"] = out["stack"][:8]
        out["classified_by"] = source
        # A clear title keyword beats a confused model: "Werkstudent ..." is a student role, entry level
        if hint and (out["category"] in ("full_time", "other") or out["seniority"] in ("mid", "senior")):
            out["category"], out["seniority"] = hint, "entry"
        return out

    def classify_many(self, rows: list[tuple]) -> list[dict]:
        """rows: (title, company, location, description). Order of results matches rows."""
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(lambda r: self.classify(*r), rows))
