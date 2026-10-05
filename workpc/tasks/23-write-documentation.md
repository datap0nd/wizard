# Task 23 — Write the documentation

**Goal:** write every planned note so that Wizard's analyst can find it, quote it safely and know how sure it is.
**Output:** `content\knowledge\<area>\<note id>.md` (internal) · **Shareable:** counts only.
**Model:** the strongest your plan lists under `/model` (quality matters more than speed here).

## Before the first note of each session

Read all of `content\schema\knowledge-standard.md`. Every note follows it exactly: front matter, lead first,
self-contained sections, a source id on every fact, `UNKNOWN` instead of guesses, "Questions this note answers" and
"Open questions".

## Loop: five notes per round, priority 1 first

1. Take the next five rows of `content\register\topic-map.md` in state `planned`.
2. For each note:
   - read the digests of its sources (`content\inbox\_digests\<id>.md`), then the full converted text of the 3 to 8 most
     valuable sources (high worth first, newest first; the paths are in `content\inbox\_text\manifest.csv`). Where
     digests disagree, read the sources themselves;
   - write `content\knowledge\<area>\<note id>.md`. An existing `DRAFT_UNSIGNED` note: update it and keep its id. A
     `SIGNED` note: do not edit it; write your proposed change in `content\register\proposed-changes.md`;
   - newer sources win over older ones for facts that change, but keep the date ("As of September 2026");
   - set the row's state to `written`.
3. After the round, run `.\docs.ps1 validate` and fix every error in the notes. Give the user one line: notes written,
   open questions found.

## Rules that matter most

- Never invent. Unknown is `UNKNOWN: ... (ask: <role>)`; a conclusion you drew is marked `(inferred)`.
- No performance figures, no contact details, nothing sensitive (knowledge standard, section 6).
- Name the subject at the start of every section; spell out acronyms once and list them in `aliases`.

**Done when:** every priority 1 and 2 note is written and `.\docs.ps1 validate` reports no errors. Record in
`STATUS.md` the notes written per area and the number of open questions.
