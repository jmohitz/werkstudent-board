-- Daily volume: one row per day and category. The grain ("one row per ...") is the
-- first thing to decide for any mart; the test in _marts.yml enforces it.
select
    posted_on                                          as day,
    category,
    count(*)                                           as jobs,
    count(*) filter (where german_required is false)   as english_friendly_jobs,
    count(*) filter (where work_mode = 'remote')       as remote_jobs
from {{ ref('stg_jobs') }}
group by posted_on, category
