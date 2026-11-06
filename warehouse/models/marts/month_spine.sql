-- The reporting months: the last N months up to the reporting month.
with ends as (
    select cast(strptime('{{ var("reporting_month") }}' || '-01', '%Y-%m-%d') as date) as last_month
)
select
    cast(last_month - (i * interval 1 month) as date) as month_start,
    cast(last_month - (i * interval 1 month) + interval 1 month - interval 1 day as date) as month_end,
    strftime(last_month - (i * interval 1 month), '%Y-%m') as month
from ends, range(0, {{ var("months") }}) t(i)
