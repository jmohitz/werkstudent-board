"""LLM layer: classifies one job posting with a small Ollama model using structured (JSON schema) output."""
import re
import logging
from typing import Literal

from ollama import Client
from pydantic import BaseModel, Field


class JobLabel(BaseModel):
    category: Literal["working_student", "internship", "thesis", "full_time", "other"]
    field: Literal[
        "data_engineering", "data_science_ml", "ai_llm", "software_engineering",
        "devops_cloud", "research", "other",
    ]
    german_required: Literal["yes", "no", "unclear"]
    relevance: int = Field(ge=1, le=5, description="Fit to the candidate profile, 5 = perfect")
    reason: str = Field(description="One short sentence")


# Cheap keyword rules: give the LLM a hint and act as a fallback if it fails.
RULES = [
    ("thesis", r"\b(masterarbeit|bachelorarbeit|abschlussarbeit|thesis)\b"),
    ("working_student", r"\b(werkstudent\w*|working student|studentische\w* (hilfskraft|mitarbeit\w*))\b"),
    ("internship", r"\b(praktik\w*|pflichtpraktikum|intern|internship)\b"),
]


def keyword_hint(title: str) -> str | None:
    t = (title or "").lower()
    for cat, pattern in RULES:
        if re.search(pattern, t):
            return cat
    return None


SYSTEM = """You classify German job postings for a student. Answer ONLY with JSON matching the schema.
Categories:
- working_student: Werkstudent / working student / studentische Hilfskraft (part-time while studying)
- internship: Praktikum / internship (incl. Pflichtpraktikum)
- thesis: Bachelor/Master thesis, Abschlussarbeit
- full_time: regular full-time job, trainee, junior position
- other: anything else (apprenticeship/Ausbildung, freelance, irrelevant)
german_required: "yes" if fluent/good German is required or the posting is fully in German, "no" if English is enough, else "unclear".
relevance: how well the job fits the candidate profile (1-5)."""


logger = logging.getLogger("classify")


class Classifier:
    def __init__(self, cfg: dict):
        oc = cfg["ollama"]
        self.client = Client(host=oc["host"])
        self.model = oc["model"]
        self.max_chars = oc.get("max_description_chars", 2000)
        self.profile = cfg["profile"]
        self.schema = JobLabel.model_json_schema()

    def classify(self, title: str, company: str, location: str, description: str) -> dict:
        hint = keyword_hint(title)
        desc = (description or "")[: self.max_chars]
        user = (
            f"Candidate profile:\n{self.profile}\n\n"
            f"Job title: {title}\nCompany: {company}\nLocation: {location}\n"
            f"Keyword hint from title: {hint or 'none'}\n\n"
            f"Description:\n{desc or '(no description)'}"
        )
        try:
            resp = self.client.chat(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                format=self.schema,
                options={"temperature": 0},
                think=False,  # qwen3: skip the reasoning trace, we only want the JSON
            )
            label = JobLabel.model_validate_json(resp.message.content)
            out = label.model_dump()
            # A clear title keyword beats a confused small model
            if hint and out["category"] in ("full_time", "other"):
                out["category"] = hint
            return out
        except Exception as e:
            logger.warning(f"LLM failed for '{title}': {e}")
            return {
                "category": hint or "other", "field": "other", "german_required": "unclear",
                "relevance": 0, "reason": "LLM failed, keyword fallback",
            }
