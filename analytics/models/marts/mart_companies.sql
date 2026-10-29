-- One row per hiring company: how many open roles, what kind, and whether you applied.
with jobs as (
    select * from {{ ref('stg_jobs') }}
),

applications as (
    select * from {{ ref('stg_applications') }}
)

select
    jobs.company,
    count(*)                                                     as open_jobs,
    count(*) filter (where jobs.category = 'working_student')    as working_student_jobs,
    count(*) filter (where jobs.category = 'internship')         as internship_jobs,
    count(*) filter (where jobs.category = 'thesis')             as thesis_jobs,
    count(distinct jobs.city)                                    as cities,
    count(applications.job_id)                                   as tracked,
    count(applications.job_id) filter (where applications.status = 'applied') as applied,
    max(jobs.posted_on)                                          as latest_posting
from jobs
left join applications on applications.job_id = jobs.job_id
where jobs.company is not null
group by jobs.company
