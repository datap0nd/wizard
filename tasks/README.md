# Tasks

Instructions the Wizard team writes for Gemini, run by the person at their PC from **Settings → Tasks**. The tasks come
packaged with the app ([decision](../docs/decisions/2026-11-13-tasks-packaged.md)): Settings → Tasks lists this folder
as the installed version holds it and reads nothing from the network, and a task pushed to `main` reaches each PC with
the update that push releases. What a task produces goes to the company's knowledge-base repository
(`wizard_kb_save_notes`), never here.

One Markdown file per task, named after its id:

```
---
id: check-where-to-get-it
title: Check and correct every metric note's "Where to get it"
summary: One line shown in Settings: what it changes and why.
added: 2026-10-31
---
The instructions for Gemini: what to read, what to change, what to leave alone, what to say at the end.
```

A task may ask for a folder or a file on the person's PC before it runs (Settings → Tasks shows a path box):

```
input: folder            # or: file, or: folder or file
input_label: The folder with the presentations
every_file: true         # it goes through every file: Wizard runs it in rounds until each one is marked done
```

Gemini reads that path only with the task-file tools, never outside it: `wizard_task_files` (the files, with ids),
`wizard_task_read_file` (one file as text, with its source id), `wizard_task_design` (how presentations look: theme,
fonts, layouts, logo and labels, read by PowerPoint) and `wizard_task_files_done` (a file is done). A task with
`every_file` runs in rounds of about 100 tool calls; each round continues with the files left, and **Continue** picks up
after a stop or a restart.

A task that works through a list in several runs (notes to check, figures to take out) can run again until it is done
(owner decision, [docs/decisions/2026-11-02-task-queue.md](../docs/decisions/2026-11-02-task-queue.md)):

```
repeat: until_done
max_runs: 5              # optional: at most this many runs (default 5, never more than 50)
```

Wizard then asks Gemini to end each run's summary with one last line, `Left: <number>`: how many items the task still
has to do (`Left: 0` when nothing is left). After a run succeeds, Wizard starts a fresh run in the same conversation
while that number is above 0, the run saved at least one note or map change, and `max_runs` is not reached; Settings
shows "Run 2 of up to 5". A summary without a `Left:` line counts as done. A run that fails is tried once more;
the task fails when that run fails too. Write such a task so that a run continues
from what earlier runs changed (they are in the knowledge base) and says what it counted as left. `repeat` does not
apply to an `every_file` task, which already runs until every file is done.

**The queue.** Settings → Tasks runs tasks one after another: **Run all** (every task), **Run selected** (the ticked
ones) or **Add to queue** on one task fills the queue in run order, oldest `added` first, then id. Tasks meant to run
in turn get the same `added` and numbered ids (`review-1-…`, `review-2-…`). The person can reorder the queue,
then presses **Start**: each task starts when the one before ended succeeded (its last round, or its last run when it
repeats). A failure or a stop stops the queue there; **Continue** runs that task again and goes on. A task
that asks for a path is queued only with the path typed in its box. Do not write a task that relies on another
running at the same time: one task runs at a time.

A task can also move, rename and remove notes, in the same save and the same single commit (owner decision,
[docs/decisions/2026-11-02-dashboards-area.md](../docs/decisions/2026-11-02-dashboards-area.md)):

```
wizard_kb_save_notes({
  "moves": [{"id": "weekly-sell-in-dashboard", "to": "knowledge/dashboards/weekly-sell-in-dashboard.md"}],
  "removes": ["an-obsolete-note"],
  "notes": [{"path": "knowledge/metrics/sell-in.md", "text": "<the whole file>"}],
  "message": "Dashboards have their own area"})
```

- A move keeps the file name, and so the id. A new file name renames the note: the file name is its new id, and Wizard
  sets it in the note and in every other note's `related` in the same commit. Text that names the old id is the task's
  to change; the save's warnings list those notes.
- A moved note whose text also changes is given whole in `notes` at its new path.
- A remove is refused while another note's `related` names it, unless the same call saves that note without the link.
- A SIGNED note is never replaced, moved, renamed or removed, and nothing is committed when anything is refused.

Rules:

- This repository is public: a task holds instructions only, never company content (names of reports, people,
  figures). Gemini finds those with its tools on the person's PC.
- A task runs with Wizard's tools: the knowledge tools, `wizard_kb_note_source`, `wizard_kb_standard`, `wizard_kb_save_notes`, the portal
  map and portal tools, the database and catalog tools, the dashboards tools (`wizard_dashboards`,
  `wizard_read_dashboard`) when the PC has a dashboards folder, NERP's view tools (`nerp_list_views`,
  `nerp_view_columns`, `nerp_query`) when NERP is connected, and the task-file tools when it asks for a path. A task
  that needs a tool Wizard does not have needs an update first.
- A task can publish one section of the Cases site's quiz (owner decision,
  [docs/decisions/2026-11-12-case-feedback-and-quiz.md](../docs/decisions/2026-11-12-case-feedback-and-quiz.md)):
  `wizard_quiz_save({"section": "bi" | "business", "intro": "...", "questions": [{"topic", "question", "now",
  "choices", "notes"}]})`, 5 to 50 questions that replace that section's on the site. People answer them there
  without signing in; their answers reach the site's admin pane, not the knowledge base. `quiz-1-…` and `quiz-2-…`
  prepare the two sections.
- Say what must not change, and what to do with a SIGNED note: Wizard refuses to change one, so usually propose the
  change in the summary.
- Delete a task's file when it is no longer needed; Wizard drops it from the list.
