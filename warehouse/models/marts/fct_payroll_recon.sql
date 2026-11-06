-- HiBob against payroll, person by person, month by month.
-- Every row is either matched or carries the one reason a People partner would act on first.
with exp as (select * from {{ ref('employee_month') }}),
paid as (select * from {{ ref('stg_payroll') }}),
q as (select country, month from {{ ref('stg_quarantined_files') }}),
known as (select employee_id, termination_date, start_date from {{ ref('stg_people') }}),
j as (
    select coalesce(exp.employee_id, paid.employee_id) as employee_id,
           coalesce(exp.month, paid.month) as month,
           coalesce(exp.country, paid.country) as country,
           exp.department as hibob_department, paid.department as payroll_department,
           exp.weekly_hours as hibob_hours, paid.weekly_hours as payroll_hours,
           exp.expected_base_monthly, paid.base_monthly as payroll_base_monthly,
           paid.gross, paid.employer_cost, exp.employed_fraction,
           exp.employee_id is not null as expected, paid.employee_id is not null as paid
    from exp full outer join paid on exp.employee_id = paid.employee_id and exp.month = paid.month
)
select j.*,
    case
        when not j.paid and exists (select 1 from q where q.country = j.country and q.month = j.month)
            then 'source_quarantined'
        when j.paid and not j.expected and k.employee_id is null then 'unknown_in_hibob'
        when j.paid and not j.expected and k.termination_date is not null
             and k.termination_date < cast(j.month || '-01' as date) then 'leaver_paid'
        when j.paid and not j.expected then 'paid_before_start'
        when not j.paid and strftime(k.start_date, '%Y-%m') = j.month then 'joiner_missing'
        when not j.paid then 'not_paid'
        when j.hibob_hours <> j.payroll_hours then 'hours_mismatch'
        when abs(j.payroll_base_monthly - j.expected_base_monthly) >
             greatest({{ var('tolerance_abs') }}, {{ var('tolerance_rel') }} * j.expected_base_monthly)
            then 'salary_mismatch'
        else 'matched'
    end as status
from j left join known k on k.employee_id = j.employee_id
