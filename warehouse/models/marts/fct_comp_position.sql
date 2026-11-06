-- Where every current employee sits in the company's published band.
with p as (select * from {{ ref('stg_people') }} where status = 'Active'),
cur as (select employee_id, arg_max(base, effective_date) as annual_base
        from {{ ref('stg_salaries') }} group by 1)
select p.employee_id, p.country, p.department, p.level, p.weekly_hours, cur.annual_base,
       {{ band_mid('p.level', 'p.country', 'p.department') }} as band_mid,
       round(cur.annual_base / {{ band_mid('p.level', 'p.country', 'p.department') }}, 3) as compa_ratio
from p join cur using (employee_id)
