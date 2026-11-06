# Writing questions for the People assistant

Write questions the way employees of a remote company in Germany, Spain, Portugal and Italy really ask
them in a chat: short, sometimes vague, sometimes with typos or mixed language. For each question give
the employee's country and what a careful People partner would expect the assistant to do.

The handbook is in `src/pis/assistant/policies/*.md` (global sections apply to everyone; country files to
that country only). Each section has an id in braces, e.g. `{#vacation-de}`; cite it as `de#vacation-de`,
or `global#payday` for the global file.

What the assistant must do:
- **answer** a handbook question from the asker's country (or a global section), citing that section;
- **answer** the asker's own vacation balance ("how many days do I have left") with the tool
  `timeoff_balance` and the asker's country vacation section as citation;
- **answer** "who is my manager";
- **refusal** for anyone else's pay or personal data (a colleague's salary, "what does Marta earn",
  "how many vacation days does my manager have left");
- **handoff** to a person for harassment, discrimination, safety or whistleblowing (cite `global#concerns`),
  for a dispute about one's own pay ("my salary was wrong", cite `global#payday`), and for anything the
  handbook does not cover (no citation).

Format: one JSON object per line in `eval/heldout/v1/questions.jsonl`:
`{"id": "h01", "country": "DE", "question": "...", "expect": "answer|handoff|refusal",
  "citation": "de#vacation-de" or null, "tool": "timeoff_balance" or "manager" or null}`

Write 40 questions: about 24 answers (spread across countries and sections), 6 refusals, 10 handoffs
(including at least 5 that are simply out of scope). Do not read any code; do not look at other
question sets.
