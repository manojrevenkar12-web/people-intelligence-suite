-- Moving a cost between cost centres changes nothing in total: per month and entity the GL must equal payroll,
-- except where a payroll file was quarantined.
select month, country, sum(difference) as total_difference
from {{ ref('fct_gl_recon') }}
where not payroll_quarantined
group by 1, 2
having abs(sum(difference)) > 1
