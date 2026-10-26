CREATE TABLE jobs (
    id              BIGSERIAL PRIMARY KEY,
    job_url         TEXT NOT NULL UNIQUE,
    job_url_direct  TEXT,
    title           TEXT NOT NULL,
    company         TEXT,
    location        TEXT,
    site            TEXT,
    date_posted     DATE,
    category        TEXT,
    field           TEXT,
    german_required BOOLEAN,
    relevance       SMALLINT,   -- legacy (profile-based scoring), NULL for new rows
    reason          TEXT,       -- legacy
    search_term     TEXT,
    date_found      DATE NOT NULL DEFAULT CURRENT_DATE,

    -- profile-free classification (db/migrations/002)
    seniority       TEXT,
    work_mode       TEXT,
    city            TEXT,
    stack           TEXT[],
    hours_per_week  SMALLINT,
    summary         TEXT,
    description     TEXT,
    classified_by   TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- same job on several sites -> one row (see db/migrations/001_dedupe_jobs.sql)
    dedupe_key      TEXT GENERATED ALWAYS AS (
        lower(btrim(title)) || '|' ||
        lower(btrim(coalesce(company, ''))) || '|' ||
        lower(btrim(split_part(coalesce(location, ''), ',', 1)))
    ) STORED
);

CREATE UNIQUE INDEX uq_jobs_dedupe_key ON jobs (dedupe_key);

CREATE INDEX idx_jobs_category   ON jobs (category);
CREATE INDEX idx_jobs_city       ON jobs (city);
CREATE INDEX idx_jobs_date_found ON jobs (date_found);
CREATE INDEX idx_jobs_field      ON jobs (field);
CREATE INDEX idx_jobs_work_mode  ON jobs (work_mode);
CREATE INDEX idx_jobs_posted     ON jobs ((coalesce(date_posted, date_found)));

-- One row per job you are tracking. Jobs with a row here never expire.
CREATE TABLE applications (
    job_id     BIGINT PRIMARY KEY REFERENCES jobs (id) ON DELETE CASCADE,
    status     TEXT NOT NULL CHECK (status IN ('saved', 'applied', 'interview', 'offer', 'rejected')),
    notes      TEXT,
    applied_at DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- resume upload, matching and cached AI output (db/migrations/003)
CREATE TABLE resume (
    id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    filename    TEXT NOT NULL,
    text        TEXT NOT NULL,         -- extracted plain text
    text_hash   TEXT NOT NULL,         -- cached AI output is keyed by this
    profile     JSONB NOT NULL,        -- structured profile extracted by the LLM
    embedding   REAL[],
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One vector per job, filled in the background by the API server
CREATE TABLE job_embeddings (
    job_id     BIGINT PRIMARY KEY REFERENCES jobs (id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    embedding  REAL[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Generated per job + resume version, so reopening a job is instant and free
CREATE TABLE job_ai (
    job_id      BIGINT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('cover_letter', 'tips')),
    lang        TEXT NOT NULL DEFAULT '',   -- 'en' / 'de' for cover letters, '' for tips
    resume_hash TEXT NOT NULL,
    model       TEXT NOT NULL,
    content     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, kind, lang, resume_hash)
);

