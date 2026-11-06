select * from {{ ref('employee_month') }} where employed_fraction <= 0 or employed_fraction > 1
