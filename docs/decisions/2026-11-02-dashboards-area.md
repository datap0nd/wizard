# 2026-11-02 — A dashboards area in the knowledge base, and tasks that move, rename and remove notes

**Owner:** project owner. **Status:** decided (2 November 2026).

**Context.** The team's HTML dashboards combine PostgreSQL data with business logic: definitions, filters, exclusions
and adjustments that the database alone does not hold. The owner wants them first: "We need dashboards area for sure."
The review of the knowledge base found notes describing these dashboards filed under `datasets/`, which holds one note
per database object, and a note whose only purpose was a mandatory source order. A task could not fix either:
`wizard_kb_save_notes` only added or replaced whole notes, and refused an id that belonged to a note at another path, so
a note could not leave the wrong folder, change its id or go.

**Options.** (1) A new note type, `dashboard`: every PC still on an older Wizard would read it as a validator error and
refuse the synced commit that carries it. (2) The dashboards area with `type: entity`, which every Wizard already
accepts. (3) For moving notes: a separate task-only tool, or optional `moves` and `removes` in the existing save, so
Gemini changes the knowledge base through one tool with one set of checks.

**Decision.** Options 2 and 3, the second form.
- **Knowledge standard.** A `dashboards/` area in section 1, and section 13 "Dashboard notes": one note per HTML
  dashboard, `type: entity`, saying what it shows (measures, breakdowns, periods), the business logic it applies and how
  each figure is calculated (so Wizard can reproduce it in SQL, or knows when not to), the dataset notes it is built
  from, how often it is refreshed and where its as-of shows, who maintains it (a role), its file name and subfolder
  inside the dashboards folder (never a drive letter, share path or full path), the metric notes it relates to, the
  questions it answers and its open questions; no performance figures, since the dashboard is the live source. Section
  11 lets a metric's `## Where to get it` name a dashboard note, say what it shows and when it is the better source.
- **Tasks move, rename and remove notes**, through `wizard_kb_save_notes` with two optional lists: `moves` (`id` and
  `to`: the same file name moves the note and keeps its id; a new file name renames it) and `removes` (ids). With the
  save's guarantees: only in a task run, one commit per call, every resulting note checked by the validator first, and
  nothing committed when anything fails. A SIGNED note is never replaced, moved, renamed or removed (the standard
  already said only its owner changes it; every task said so too, and now the tool refuses it). A rename sets the new
  id in the note and in every other note's `related` in the same commit, read through the knowledge base, or is refused
  with the list (a SIGNED note that links to it). A remove is refused while another note's `related` names it, unless
  the same call saves that note without the link. Notes whose text names a renamed or removed id are listed as
  warnings for Gemini to change.
- **The commit removes files** with `update_branch` (the writer the Pages site uses), only when every removed file is
  still on the branch: otherwise another Wizard moved it since this PC's last sync, and nothing is committed. A save that
  removes nothing still uses the same commit as before.
- **The rest of the run sees the change**: `KnowledgeBase.with_saved` drops moved, renamed and removed notes.

**Consequences.**
- The knowledge review's notes about dashboards can move to `dashboards/` and the source-order note can go, by tasks
  (written separately). The tools that read the dashboards themselves are separate work.
- A whole-note save that replaces a SIGNED note is now refused; before, only the task's instructions prevented it.
- Quizzes and expert answers refer to note ids (knowledge standard, section 2); a rename does not change them.

**Evidence.** `tests/unit/test_tasks.py`: a move (the old file removed and the new one written in one commit, the run's
knowledge base, note source and browse seeing it), a move with new text, a rename with the link in another note
changed in the same commit, removes with and without a link updated in the same call; refusals that commit nothing for
a SIGNED note (move, remove, replace, a rename linked from one), a remaining link, a validator error, a destination
that is another note, a path the same call removes and an unknown id; a question refused; the writer's removal through
`update_branch` and its refusal when a file is gone; a `dashboards/` note written to section 13 passing the validator.
