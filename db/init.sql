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
    relevance       SMALLINT,
    reason          TEXT,
    search_term     TEXT,
    date_found      DATE NOT NULL DEFAULT CURRENT_DATE,

    -- filled in Step 2, empty for now
    city            TEXT,
    stack           TEXT[],
    hours_per_week  SMALLINT,

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