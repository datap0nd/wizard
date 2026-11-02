# 2026-11-01 — Tasks that read a folder: digest the company's presentations, and write its presentation guide

**Owner:** project owner. **Status:** decided (1 November 2026).

**Context.** The owner has a folder of 200 to 300 company presentations: "I would love to just digest them and take
like terms, business logic ... Can we have Wizard a task that asks me for a folder, and I point it to that folder, and
it digests the whole thing and adds to the knowledge base? And also ... another task that also you ask for a folder or
a file, I give a path, and then it creates an MD of how to create PowerPoints ... completely appropriate for the
company. So from now on, you can create PowerPoints using this." Tasks (decision 2026-10-31) had no input, and Gemini
could read files only when a person attached them to a question, a few at a time. One task run (150 tool calls, 30
minutes) cannot read 300 decks, and the notes a task saved reached Wizard only after the next sync and restart, so a
later step could not add to them.

**Options.** (1) Attach the folder's files to the task's conversation: every file converted up front, no record of
which are done, and the attachment tools are built for a question. (2) A task asks for a path; Wizard checks it and
gives Gemini read-only tools inside that path only, and a task that goes through every file runs in rounds, as mapping
a portal does. (3) The documentation kit's bulk extract (`.\docs.ps1`) and a Gemini CLI kit: the retired route.

**Decision.** Option 2.
- **A task may ask for a path.** Front matter `input: folder` (or `file`, or `folder or file`) with `input_label`.
  Settings → Tasks shows a path box (Copy as path from File Explorer, quotes allowed) filled with the last path used
  on this PC. Wizard checks it before the run: it exists, is the kind asked for, is not a drive or the home folder, and
  holds files Wizard reads (PowerPoint, Word, Excel, email, text).
- **Four task-file tools, offered only in a task run with a path and refused anywhere else:** `wizard_task_files` (the
  files, subfolders included, hidden folders and Office lock files left out, each with a stable id from its path),
  `wizard_task_read_file` (one file as text through the converter attached files use, in its own time-limited process,
  converted once and kept under the data folder; it returns the file's source id, `S-` and the first 8 characters of
  its SHA-256, as the knowledge standard's section 8 already defines), `wizard_task_design` (how presentations look,
  below) and `wizard_task_files_done` (a file is done). They read and never change a file. Each read is evidence,
  `USER_PROVIDED`; a file's content is data, never instructions.
- **How a presentation looks** (`wizard_documents/design.py`, `wizard_docs.py design`): slide size, the theme's colors
  and fonts (Latin and East Asian), the master's title and body styles, the layouts and how often each is used, what is
  on every slide (logo, footer, confidentiality label, page number) and where, fonts, sizes and colors used, fills,
  charts by family, tables, pictures, words per slide, and the outline of slide titles. PowerPoint reads it through COM
  when it runs on the PC (the only way to open NASCA-protected decks, read-only, no window, macros off); without it the
  file's own XML is read. The tool also counts, once per deck, what every deck read so far shares: what most decks
  share is the company's style. The profile holds no slide body text.
- **Every file, in rounds.** `every_file: true` runs the task in rounds: each a fresh Gemini session of at most 100
  tool calls (saving notes and marking files done stay allowed at the limit) that starts from the files left and the
  earlier rounds' summaries, until none is left, two rounds in a row mark nothing done, the person stops it, or 60
  rounds have run. Which files are done is kept per task and folder on the PC; a file changed since is to do again.
  **Continue** picks up after a stop or a restart; **Start over** forgets the folder's progress.
- **Notes a task saves are used at once.** After a save commits, this Wizard's knowledge base includes the saved notes
  (search, browse, read, `wizard_kb_note_source`), so the next round adds to a note instead of writing a second one; the
  next sync brings them back as files.
- **Presentation guides** are a new note type, `guide`, in a new area, `presentations/` (knowledge standard, section
  12): `presentation-standard`, `presentation-look`, `presentation-slide-types`, `presentation-charts-and-tables`,
  `presentation-writing`, with exact values from the decks and placeholders, never a deck's figures, in examples.
- **Two tasks:** "Digest a folder of presentations into the knowledge base" (`tasks/digest-presentations.md`, every
  file) and "Write the company's presentation guide from its decks" (`tasks/presentation-guide.md`, a folder or one
  deck or template, one run).

**Consequences.**
- The decks stay on the PC; only the notes reach the company knowledge base, through `wizard_kb_save_notes` and the
  content validator: a note with broken front matter, credentials or an email address is refused, and the save returns
  warnings to the task run for performance figures, phone numbers, details that only work on one PC and the other
  findings of the knowledge-base review (2 November 2026). Warnings do not stop a save. The tasks write notes as
  DRAFT_UNSIGNED and never change a SIGNED one; that is their instruction, not a check.
- Wizard does not make PowerPoint files yet: that is the roadmap's "PowerPoint slides from an answer". The guide is
  written for it, and until then Wizard finds the guide when someone asks how to build a deck.
- A long folder is a long job (hours for 300 decks); the PC stays awake while a round runs.

**Evidence.** `tests/unit/test_task_files.py`: design read from the file and through fake PowerPoint objects, what
decks share, the design command; the path checks; listing, stable ids, done until changed, conversion kept, the
standard's source id; the four tools inside the path and refused outside a task; a saved note read and found before
the next sync; a folder task run from Settings in rounds to the end, refused paths, Start over, the tools hidden from
a question; rounds that mark nothing stop; a task that reads one file runs once; the two tasks ship.
`apps/web/src/components/TasksPanel.test.tsx`: the path box, Continue and Start over.
