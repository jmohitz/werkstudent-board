-- Profile-free classification fields, the job description, and the application tracker.
--
-- Apply: docker exec -i board-db psql -U board -d board < db/migrations/002_classification_and_tracker.sql

BEGIN;

ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS description   TEXT,
    ADD COLUMN IF NOT EXISTS seniority     TEXT,   -- entry | junior (mid/senior are dropped by the scraper)
    ADD COLUMN IF NOT EXISTS work_mode     TEXT,   -- remote | hybrid | onsite | unclear
    ADD COLUMN IF NOT EXISTS summary       TEXT,   -- one sentence: what the person will do
    ADD COLUMN IF NOT EXISTS classified_by TEXT;   -- model name, "ollama" or "keyword"
-- city, stack and hours_per_week already exist (init.sql, reserved for this step)

CREATE INDEX IF NOT EXISTS idx_jobs_field     ON jobs (field);
CREATE INDEX IF NOT EXISTS idx_jobs_work_mode ON jobs (work_mode);
CREATE INDEX IF NOT EXISTS idx_jobs_posted    ON jobs ((coalesce(date_posted, date_found)));

-- One row per job you are tracking. Jobs with a row here never expire.
CREATE TABLE IF NOT EXISTS applications (
    job_id     BIGINT PRIMARY KEY REFERENCES jobs (id) ON DELETE CASCADE,
    status     TEXT NOT NULL CHECK (status IN ('saved', 'applied', 'interview', 'offer', 'rejected')),
    notes      TEXT,
    applied_at DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
