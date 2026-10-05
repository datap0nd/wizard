# Task 25 — Coverage check

**Goal:** make sure the documentation uses everything valuable that was collected, and nothing is left out by accident.
**Output:** `content\register\documentation-coverage.md` (internal), `outbox\25-coverage.md`
· **Shareable:** `outbox\25-coverage.md` (percentages and counts only).
**Model:** the strongest your plan lists under `/model`.

## Steps

1. `.\docs.ps1 coverage` lists the high- and medium-worth sources no note cites, the topics without a note, and the
   notes without sources (also written to `content\register\documentation-coverage.md`).
2. For each uncited high-worth source, do one of:
   - add its facts to an existing note (rules of task 23) and cite it;
   - add a topic to `content\register\topic-map.md` and write the note;
   - or, if it is not documentation after all, add one line under "Not used" in the coverage file saying why.
3. Topics without a note: write the note or merge the topic into an existing one. Notes without sources: add the
   sources, or mark their statements `(inferred)`.
4. Run `.\docs.ps1 coverage` and `.\docs.ps1 validate` again. Repeat until at least 90% of high-worth sources are cited
   or explained, and the validator reports no errors.

## Write `outbox\25-coverage.md`

The coverage percentage for high and medium sources, the number of notes per area, open questions per area, and
validator warnings by kind.

**Done when:** at least 90% of high-worth sources are cited or explained and the validator reports no errors.
