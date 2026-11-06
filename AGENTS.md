# Working in this repository

## Fast feedback
- `pytest -q` runs everything in under 30 seconds: the HiBob client against the stand-in, the contracts,
  the dbt build, reconciliation, privacy, the assistant, the payroll sync and the n8n workflow checks.
- `pis evaluate` scores the pipeline, the assistant and the sync against the simulated truth and rewrites
  `reports/results.json`; `pis report` regenerates `reports/REPORT.md`, the dashboard and the Tableau extract.

## Invariants
- **Nothing but the evaluation reads the truth.** `data/truth/` and `config/company.yaml` belong to the
  simulation (`src/pis/sim`) and `src/pis/evaluate.py` (`tests/test_isolation.py`).
- **Contracts at the door.** A source row that breaks a contract goes to quarantine with a reason; a file
  whose rows mostly break the same rule is quarantined whole and its people are reported as
  `source_quarantined`, never as unpaid.
- **Personal data stays where it is needed.** Reporting extracts carry pseudonyms, not names or HiBob IDs;
  groups under `pay_gap.min_group` are suppressed; gender is read only by the pay-equity job, in memory.
- **The assistant reads only the asker's own record**, and every such read is in the audit log.
- **Rules decide, models phrase.** Which questions are answered, refused or handed over is code.
- **Money moves only through people.** The sync sends change requests the payroll team approves, and
  sends anything that needs judgement (overpayments, duplicates) to the People team.
- **Business settings live in `config/policy.yaml`**, not in code.
- **Reports are generated.** Do not hand-edit `reports/`.

## The held-out rule
`eval/heldout/<set>/questions.jsonl` was written by an agent that read only `eval/WRITING_QUESTIONS.md` and
the handbook. It is pinned by `eval/heldout/<set>.sha256`; its first run is recorded once in
`reports/heldout/<set>/first_run.json` and never rewritten. Never change the assistant to do better on a
held-out set. If you study a set's failures, write `regression` into its `STATUS` and have someone who has
not seen the code write a new set.
