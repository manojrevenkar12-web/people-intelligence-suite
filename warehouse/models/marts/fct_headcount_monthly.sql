-- Headcount at month end, FTE, hires and leavers, by country and department.
with em as (select * from {{ ref('employee_month') }}),
p as (select * from {{ ref('stg_people') }})
select em.month, em.country, em.department,
       count(*) filter (where em.termination_date is null or em.termination_date >= em.month_end) as headcount,
       round(sum(em.weekly_hours / 40.0) filter (where em.termination_date is null
                                                     or em.termination_date >= em.month_end), 1) as fte,
       count(*) filter (where strftime(em.start_date, '%Y-%m') = em.month) as hires,
       count(*) filter (where strftime(em.termination_date, '%Y-%m') = em.month) as leavers,
       count(*) filter (where strftime(em.termination_date, '%Y-%m') = em.month
                          and p.termination_reason = 'voluntary') as voluntary_leavers
from em join p using (employee_id)
group by 1, 2, 3
