-- Data-quality issues in the People data that a person has to fix at the source.
with p as (select * from {{ ref('stg_people') }}),
act as (select * from p where status = 'Active'),
mgr as (select employee_id, status, display_name from p)
-- reports to someone who has left
select a.employee_id, 'manager_is_leaver' as issue,
       'reports to ' || m.display_name || ', who has left' as detail
from act a join mgr m on m.employee_id = a.manager_id
where m.status <> 'Active'
union all
-- no manager, and not the top of the organisation
select a.employee_id, 'missing_manager', 'no manager in HiBob'
from act a
where a.manager_id is null and a.title not in ({{ "'" ~ var('org_root_titles') | join("','") ~ "'" }})
union all
-- too many direct reports
select m.employee_id, 'span_of_control', count(*) || ' direct reports'
from act a join mgr m on m.employee_id = a.manager_id
group by m.employee_id
having count(*) > {{ var('span_of_control_max') }}
union all
-- a rehire created as a new person: same name and country, started after the earlier record ended
select b.employee_id, 'possible_duplicate',
       'same name and country as ' || a.employee_id || ', who left on ' || a.termination_date
from p a join p b
  on a.display_name = b.display_name and a.country = b.country and a.employee_id <> b.employee_id
 and a.termination_date is not null and b.start_date > a.termination_date
union all
-- approved in the compensation tool, not in HiBob
select c.employee_id, 'comp_not_in_hibob',
       'approved ' || c.approved_base || ' from ' || c.effective_date || ', HiBob has ' || coalesce(s.base, 0)
from {{ ref('stg_comp_cycle') }} c
left join {{ ref('stg_salaries') }} s
  on s.employee_id = c.employee_id and s.effective_date = cast(c.effective_date as date)
where c.status = 'approved' and (s.base is null or abs(s.base - c.approved_base) > 1)
