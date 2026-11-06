select employee_id, month, count(*) from {{ ref('fct_payroll_recon') }} group by 1, 2 having count(*) > 1
