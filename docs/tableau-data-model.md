# Tableau data model

`pis report` writes `reports/tableau/people.hyper` (schema `Extract`), read back after writing. Connect a
workbook or publish it as a data source. Employee IDs are keyed pseudonyms (`P-…`); no names or emails.

| Table | Grain | Use |
|---|---|---|
| `headcount_monthly` | month × country × department | headcount, FTE, hires, leavers, voluntary leavers |
| `comp_position` | current employee | level, country, department, base, band midpoint, compa-ratio |
| `payroll_exceptions` | person × month, not matched | status and the HiBob and payroll values behind it |
| `data_quality_issues` | issue | issue category per person, to fix in HiBob |
| `gl_reconciliation` | month × country × department | payroll cost, GL cost, difference, flagged |
| `pay_equity_by_department` | department | adjusted gap; groups under the minimum size suppressed |

Suggested views for leadership: headcount and attrition trend by department; compa-ratio distribution by
level; open payroll exceptions by status and age; GL breaks by month; pay equity with intervals.
