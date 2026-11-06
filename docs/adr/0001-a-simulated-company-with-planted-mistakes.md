# 0001. A simulated company with planted mistakes

## Status
Accepted.

## Context
Real People data is the most sensitive data a company holds; no portfolio project can use it. A
reconciliation checked only on data it generated proves nothing unless the mistakes are known in advance.

## Decision
`src/pis/sim` writes a 250-person company in Germany, Spain, Portugal and Italy in the shapes the real
systems use: HiBob's API (slash-key responses, silent field omission, `showInactive`, paginated bulk
tables, 429s), a DATEV-style export with semicolons and decimal commas, a cloud payroll provider's CSV, a
compensation-cycle export and Finance's ledger. It plants the mistakes People teams actually meet: leavers
paid, joiners missed, raises not in payroll, hours that differ from the contract, managers who left,
a rehire created twice, an approved raise never entered, a file in cents, cost on an old department,
and a real pay gap in one department. The answer key is in `data/truth/`, which only the evaluation reads.

## Consequences
Every number in the report is a measured precision and recall against known mistakes. Moving to real data
means pointing `HIBOB_BASE_URL` at HiBob and dropping the providers' files into `data/sources/`.
