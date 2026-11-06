# Playbook for the People team

## Every month, after payroll closes
1. Run `pis pipeline` (or let the scheduled job run it). Check `reports/REPORT.md`: anything in
   quarantine is a file to ask the provider about before you trust the numbers.
2. Work the exceptions in Tableau (`payroll_exceptions`): leavers paid go to Finance for recovery; raises
   not in payroll and hours mismatches are already change requests in the provider's approval queue.
3. Fix the data-quality issues in HiBob (`data_quality_issues`): managers who left, missing managers,
   possible duplicates (a person checks; most share only a name), approved raises not entered.

## Adding a handbook answer
Add a section to the country file in `src/pis/assistant/policies/` with a heading and an id:
`## Bike leasing (Germany) {#bike-de}`. Write the answer the way you would say it. If people ask it in
words the section does not use, add a line `Asked as: …` with those words. Run `pytest -q`; add a question
to `eval/dev/questions.jsonl` that the new section should answer.

## Changing what the assistant refuses or hands over
The rules are at the top of `src/pis/assistant/core.py`, one pattern each. Change one, add a dev question
that shows why, run the tests. Never tune on the held-out questions (see AGENTS.md).

## Extending the n8n workflows
`pis n8n` writes the workflows from `src/pis/n8n_build.py`. Import them in n8n, then create the
credentials they name: the API token, the chat webhook secret and the payroll provider API key. Set
`PIS_API_URL`, `PAYROLL_API_URL` and `HELPDESK_URL` in n8n's environment.
