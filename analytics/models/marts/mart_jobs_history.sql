-- Long-term trends from the snapshot, unaffected by the board's 7-day expiry.
-- One row per job ever seen, with when it appeared and when it expired.
with versions as (
    select * from {{ ref('jobs_snapshot') }}
),

per_job as (
    select
        job_id,
        -- latest known values (the snapshot keeps every version)
        (array_agg(category order by dbt_valid_from desc))[1]  as category,
        (array_agg(source   order by dbt_valid_from desc))[1]  as source,
        (array_agg(company  order by dbt_valid_from desc))[1]  as company,
        min(posted_on)                                          as posted_on,
        min(dbt_valid_from)::date                               as first_seen,
        -- set once the scraper deleted it; null while it's still on the board
        max(dbt_valid_from) filter (where dbt_is_deleted = 'True')::date as expired_on
    from versions
    group by job_id
)

select
    *,
    expired_on is null                     as is_active,
    date_trunc('month', posted_on)::date   as posted_month
from per_job
