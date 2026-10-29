-- The application tracker, renamed to match stg_jobs.
select
    job_id,
    status,
    notes,
    applied_at,
    updated_at
from {{ source('app', 'applications') }}
