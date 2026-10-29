-- Intermediate model: reshapes data for marts but isn't meant to be queried directly.
-- Here: one row per (job, skill) instead of an array per job, with spellings unified
-- ("Machine Learning" / "machine learning" -> one skill).
with exploded as (
    select
        j.job_id,
        j.category,
        j.posted_on,
        trim(s) as skill_raw
    from {{ ref('stg_jobs') }} j
    cross join lateral unnest(j.stack) as s
)

select
    job_id,
    category,
    posted_on,
    lower(skill_raw) as skill_key,   -- what we group by
    skill_raw
from exploded
where skill_raw <> ''
