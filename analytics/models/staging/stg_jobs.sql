-- Staging model: one-to-one with the source, only renaming, casting and light cleanup.
-- No joins or aggregations here; those belong in marts.
select
    id                                   as job_id,
    title,
    company,
    city,
    site                                 as source,
    category,
    field,
    seniority,
    work_mode,
    german_required,
    stack,
    hours_per_week,
    classified_by,
    -- one clean bucket per classifier; NULL = classified before this was recorded
    case
        when classified_by is null           then 'unknown'
        when classified_by = 'keyword'       then 'keyword'
        when classified_by = 'ollama'        then 'ollama'
        else 'gemini'                        -- gemini-* and gemma-* models
    end                                  as classifier,
    date_posted,
    date_found,
    -- the board treats "posted" as the posting date when known, else the day we found it
    coalesce(date_posted, date_found)    as posted_on,
    created_at
from {{ source('app', 'jobs') }}
