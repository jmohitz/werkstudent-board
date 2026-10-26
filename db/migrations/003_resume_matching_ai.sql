-- Resume upload, job embeddings for matching, and cached AI output (cover letters, resume tips).
--
-- Apply: docker exec -i board-db psql -U board -d board < db/migrations/003_resume_matching_ai.sql

BEGIN;

-- Single-user app: at most one resume (id is always 1)
CREATE TABLE IF NOT EXISTS resume (
    id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    filename    TEXT NOT NULL,
    text        TEXT NOT NULL,         -- extracted plain text
    text_hash   TEXT NOT NULL,         -- cached AI output is keyed by this
    profile     JSONB NOT NULL,        -- structured profile extracted by the LLM
    embedding   REAL[],
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One vector per job, filled in the background by the API server
CREATE TABLE IF NOT EXISTS job_embeddings (
    job_id     BIGINT PRIMARY KEY REFERENCES jobs (id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    embedding  REAL[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Generated per job + resume version, so reopening a job is instant and free
CREATE TABLE IF NOT EXISTS job_ai (
    job_id      BIGINT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('cover_letter', 'tips')),
    lang        TEXT NOT NULL DEFAULT '',   -- 'en' / 'de' for cover letters, '' for tips
    resume_hash TEXT NOT NULL,
    model       TEXT NOT NULL,
    content     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, kind, lang, resume_hash)
);

COMMIT;
