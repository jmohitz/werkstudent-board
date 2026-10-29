-- Which sources are worth scraping: volume, freshness and quality per source.
select
    source,
    count(*)                                                        as jobs,
    round(100.0 * count(*) / sum(count(*)) over (), 1)              as pct_of_board,
    count(*) filter (where posted_on >= current_date - 1)           as jobs_last_2_days,
    round(100.0 * avg((german_required is false)::int), 1)          as pct_english_friendly,
    -- share classified by Gemini, out of the jobs where we know (unknown = older rows)
    round(100.0 * count(*) filter (where classifier = 'gemini')
          / nullif(count(*) filter (where classifier <> 'unknown'), 0), 1) as pct_gemini_classified,
    count(*) filter (where date_posted is null)                     as jobs_without_post_date
from {{ ref('stg_jobs') }}
group by source
