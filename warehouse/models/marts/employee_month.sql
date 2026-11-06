-- What HiBob says each person should cost in each month they were employed.
-- Salary and department as of the month end; pay prorated for the days employed in the month.
with p as (select * from {{ ref('stg_people') }}),
spine as (select * from {{ ref('month_spine') }}),
em as (
    select p.employee_id, p.country, p.weekly_hours, p.start_date, p.termination_date, p.status,
           s.month, s.month_start, s.month_end,
           greatest(p.start_date, s.month_start) as from_day,
           least(coalesce(p.termination_date, s.month_end), s.month_end) as to_day
    from p join spine s
      on p.start_date <= s.month_end and (p.termination_date is null or p.termination_date >= s.month_start)
),
sal as (
    select em.employee_id, em.month, arg_max(sa.base, sa.effective_date) as annual_base
    from em join {{ ref('stg_salaries') }} sa
      on sa.employee_id = em.employee_id and sa.effective_date <= em.month_end
    group by 1, 2
),
dep as (
    select em.employee_id, em.month, arg_max(w.department, w.effective_date) as department,
           arg_max(w.level, w.effective_date) as level
    from em join {{ ref('stg_work_history') }} w
      on w.employee_id = em.employee_id and w.effective_date <= em.month_end
    group by 1, 2
)
select em.employee_id, em.month, em.month_start, em.month_end, em.country, em.weekly_hours,
       dep.department, dep.level, sal.annual_base,
       round(sal.annual_base / 12 * em.weekly_hours / 40, 2) as expected_base_monthly,
       (datediff('day', em.from_day, em.to_day) + 1) / (datediff('day', em.month_start, em.month_end) + 1)
           as employed_fraction,
       em.start_date, em.termination_date
from em
left join sal using (employee_id, month)
left join dep using (employee_id, month)
