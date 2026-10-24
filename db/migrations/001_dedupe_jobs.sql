-- Remove cross-site duplicates and stop new ones from being inserted.
-- A job is a duplicate when title + company + city match (case-insensitive).
-- City = first comma-separated part of location, so "Stuttgart" and
-- "Stuttgart, Baden-Württemberg, Germany" match, while the same posting in
-- two different cities stays as two rows (like foorilla lists them).
--
-- Apply: docker exec -i board-db psql -U board -d board < db/migrations/001_dedupe_jobs.sql

BEGIN;

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS dedupe_key TEXT GENERATED ALWAYS AS (
    lower(btrim(title)) || '|' ||
    lower(btrim(coalesce(company, ''))) || '|' ||
    lower(btrim(split_part(coalesce(location, ''), ',', 1)))
) STORED;

-- Keep the first row we saw (lowest id) of each group
DELETE FROM jobs a
USING jobs b
WHERE a.dedupe_key = b.dedupe_key
  AND a.id > b.id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_dedupe_key ON jobs (dedupe_key);

COMMIT;
