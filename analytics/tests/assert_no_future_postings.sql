-- A "singular" test: any SQL file in tests/. It fails if it returns rows.
-- A posting date in the future means a source's date parsing broke.
select job_id, source, date_posted
from {{ ref('stg_jobs') }}
where date_posted > current_date
