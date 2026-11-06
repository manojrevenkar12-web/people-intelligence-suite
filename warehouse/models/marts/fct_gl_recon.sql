-- Payroll cost by HiBob department against what Finance booked per cost centre.
with q as (select country, month from {{ ref('stg_quarantined_files') }}),
pay as (
    select r.month, r.country, coalesce(r.hibob_department, r.payroll_department) as department,
           sum(r.employer_cost) as payroll_cost
    from {{ ref('fct_payroll_recon') }} r
    where r.paid
    group by 1, 2, 3
),
gl as (
    select period as month, country, cost_center as department, sum(amount_eur) as gl_cost
    from {{ ref('stg_gl') }} group by 1, 2, 3
)
select coalesce(pay.month, gl.month) as month, coalesce(pay.country, gl.country) as country,
       coalesce(pay.department, gl.department) as department,
       coalesce(pay.payroll_cost, 0) as payroll_cost, coalesce(gl.gl_cost, 0) as gl_cost,
       round(coalesce(gl.gl_cost, 0) - coalesce(pay.payroll_cost, 0), 2) as difference,
       exists (select 1 from q where q.country = coalesce(pay.country, gl.country)
                                 and q.month = coalesce(pay.month, gl.month)) as payroll_quarantined,
       abs(coalesce(gl.gl_cost, 0) - coalesce(pay.payroll_cost, 0)) > {{ var('gl_tolerance') }} as flagged
from pay full outer join gl on pay.month = gl.month and pay.country = gl.country and pay.department = gl.department
