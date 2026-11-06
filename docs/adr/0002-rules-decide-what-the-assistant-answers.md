# 0002. Rules decide what the assistant answers

## Status
Accepted.

## Context
A People assistant fails in two expensive ways: it shares someone else's data, or it answers something a
person must handle (a harassment report, a pay dispute). Both are policy decisions, not language tasks.

## Decision
The decision is code (`src/pis/assistant/core.py`), checked in this order: action requests and concerns go
to a person; disputes about one's own pay go to a person; anything about another person's pay or balance is
refused; one's own balance and manager come from HiBob for the asker only; everything else is answered from
the handbook section of the asker's country, with the section cited, or handed over when no section covers
it well enough (`assistant.min_score`, `assistant.min_coverage`). A language model can be added to phrase
the answer from the cited section; it never decides the route.

## Consequences
The People team can read and change the rules. The cost is coverage: the first blind run handed over a
quarter of questions it could have answered. A wrong answer is worse than a handover, so that is the
direction we chose to fail in.
