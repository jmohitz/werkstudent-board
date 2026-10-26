"""Gemini access for the API server: structured/text generation with a model fallback chain, and
embeddings. Key: GEMINI_API_KEY in the repo's .env.

Generation tries GEN_MODELS best-first. A model that is rate-limited or overloaded is skipped for a
minute; one whose daily free quota is used up is skipped for a few hours.
"""
import logging
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv(Path(__file__).parent.parent / ".env")
logger = logging.getLogger("llm")
logging.getLogger("google_genai").setLevel(logging.WARNING)  # it logs every internal retry at INFO

# Best quality first. Free-tier limits measured on this key: 3.8-flash 20/day, 3.5-flash 5/min,
# 3.5-flash-lite and 3.1-flash-lite 15/min each.
GEN_MODELS = os.environ.get(
    "GEN_MODELS", "gemini-3.8-flash,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite"
).split(",")
# Resume parsing is plain extraction: start with the faster models and keep 3.8-flash's
# 20 requests/day for cover letters and tips.
FAST_MODELS = [m for m in GEN_MODELS if m != "gemini-3.8-flash"] + ["gemini-3.8-flash"]
EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIMS = 768
# Free tier per model: 100 texts and 30,000 tokens per minute. Batches are sized to stay under both.
EMBED_BATCH = 90
EMBED_TOKENS_PER_BATCH = 24_000

_client = None
_paused: dict[str, float] = {}  # model -> monotonic time it may be used again
_lock = threading.Lock()


class LLMUnavailable(Exception):
    """Every model failed or is rate-limited right now."""


class RateLimited(Exception):
    """429/503. `daily` = the free-tier daily quota is used up (embeddings: 1000 texts/day)."""

    def __init__(self, msg: str):
        super().__init__(msg)
        self.daily = "PerDay" in msg  # e.g. EmbedContentRequestsPerDay...; per-minute limits pass quickly


def client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY is not set (add it to the repo's .env)")
        _client = genai.Client(
            api_key=key,
            # interactive use: a slow or stuck model should hand over to the next one quickly
            http_options=types.HttpOptions(timeout=45_000, retry_options=types.HttpRetryOptions(attempts=1)),
        )
    return _client


def _pause(model: str, err: Exception, seconds: int = 60):
    daily = "PerDay" in str(err)
    with _lock:
        _paused[model] = time.monotonic() + (6 * 3600 if daily else seconds)
    logger.warning(f"{model}: {'daily quota used up' if daily else type(err).__name__}, skipping it for a while")


def generate(prompt: str, system: str, schema=None, max_tokens: int = 4096, models: list[str] | None = None):
    """Returns (result, model). result is a parsed `schema` instance, or text when schema is None.
    `models` overrides the order (e.g. skip the slow best model for quick extraction tasks)."""
    failures = []
    for model in models or GEN_MODELS:
        if time.monotonic() < _paused.get(model, 0):
            continue
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.4 if schema is None else 0,
            max_output_tokens=max_tokens,
            thinking_config=None if model.startswith("gemma") else types.ThinkingConfig(thinking_level="low"),
            **({"response_mime_type": "application/json", "response_schema": schema} if schema else {}),
        )
        try:
            resp = client().models.generate_content(model=model, contents=prompt, config=config)
        except errors.APIError as e:
            if e.code in (429, 503):
                _pause(model, e)
            failures.append(f"{model}: {e.code}")
            continue
        except Exception as e:  # timeouts, network: don't make the next click wait on it again
            _pause(model, e, seconds=120)
            failures.append(f"{model}: {type(e).__name__}")
            continue
        if schema is not None and resp.parsed is None:
            failures.append(f"{model}: unparsable output")
            continue
        if schema is None and not (resp.text or "").strip():
            failures.append(f"{model}: empty output")
            continue
        return (resp.parsed if schema is not None else resp.text.strip()), model
    raise LLMUnavailable("All Gemini models are busy or over quota right now"
                         + (f" ({'; '.join(failures)})" if failures else "") + ". Try again in a minute.")


def embed(texts: list[str], task: str) -> list[list[float]]:
    """task: RETRIEVAL_DOCUMENT for jobs, RETRIEVAL_QUERY for the resume."""
    try:
        resp = client().models.embed_content(
            model=EMBED_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMS, task_type=task),
        )
    except errors.APIError as e:
        if e.code in (429, 503):
            raise RateLimited(str(e)) from e
        raise
    return [e.values for e in resp.embeddings]
