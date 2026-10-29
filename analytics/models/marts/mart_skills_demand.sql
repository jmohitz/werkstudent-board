-- Which skills are asked for most, overall and per category.
select
    skill_key,
    -- the most common original spelling, for display ("Python", not "python")
    mode() within group (order by skill_raw)                    as skill,
    count(distinct job_id)                                      as jobs,
    count(distinct job_id) filter (where category = 'working_student') as working_student_jobs,
    count(distinct job_id) filter (where category = 'internship')      as internship_jobs,
    count(distinct job_id) filter (where category = 'thesis')          as thesis_jobs,
    round(100.0 * count(distinct job_id)
          / (select count(*) from {{ ref('stg_jobs') }} where stack is not null), 1) as pct_of_jobs
from {{ ref('int_job_skills') }}
group by skill_key
order by jobs desc
