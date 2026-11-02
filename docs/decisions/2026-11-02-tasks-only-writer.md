# 2026-11-02 — Tasks are the only writer of the knowledge base; the documentation kit is retired

**Owner:** project owner. **Status:** decided (2 November 2026).

**Context.** Two things wrote the company's knowledge-base repository, and neither knew about the other. Tasks
([decision](2026-10-31-tasks.md)) save whole notes straight to it with `wizard_kb_save_notes`. `.\docs.ps1 kb-publish`
uploaded the work PC's `content\knowledge` and `content\contracts\sources`: it replaced every changed file and deleted
every file missing locally, and nothing brought the notes a task saved into that folder. One more publish would have
reverted every note a task changed and deleted every note a task wrote. A review of the knowledge base advised fixing
it "in the kit and kb-publish". Asked which copy wins, the owner took the recommendation that the repository is the
master copy of the notes: "your recommendation". On making kb-publish safe: "Remove traces of those 50 tasks no? We're
going with these dynamic tasks you start from here." And on the rest of the documentation kit: "remove the rest of the
kit too, I don't use it."

**Options.** (1) Keep kb-publish and make it safe: a record on the PC of what it last published, nothing published
that changed in the repository since, and a `kb-pull` that brings the repository's versions down. Two writers stay,
and the PC's copy is one more thing to keep in step. (2) Retire kb-publish and the rest of the documentation kit:
tasks are the only writer, and everyone works on the repository.

**Decision.** Option 2.
- **The repository is the master copy of `knowledge/`.** A task run is the only part of Wizard that writes notes
  (`wizard_kb_save_notes`: whole notes, validated, one commit per save, with the write token entered in Settings on
  that PC). A person may change a note on GitHub directly; every PC picks it up at its next sync. The owner signs a
  note there (`status: SIGNED`, `reviewed`, `reviewed_by`; knowledge standard, section 7).
- **Report catalogs** (`contracts/sources/`) stay in the repository as they are. Portal catalogs are retired
  separately; the others are read-only until a task can write them.
- **Retired:** `docs.ps1` and every command behind it (kb-publish, kb-check, validate, provision, extract, status,
  next, topics, coverage, check, outlook-folders, outlook-export, postgres-check, postgres-catalog, bdp-check,
  quiz-check, quiz-answers), with their code (`wizard_documents`: `kit.py`, `inbox.py`, `postgres.py`, `bdp.py`, the
  kit's commands in `cli.py`, the mail export in `office.py`, `publish()` and `check_read()` in `kb.py`) and tests; the
  expert quiz page (`workpc/templates/`); the install folder's `GEMINI.md` for Gemini CLI sessions; and the content
  template's authoring set-up (`templates/content/`: `GEMINI.md`, `README.md`, `.gemini/commands/`, `inbox/`,
  `register/`, the placeholder folders and the catalog schema copy). Setup removes `docs.ps1`, `GEMINI.md`,
  `templates\` and `tasks\` from an install and leaves the folders the person filled (`content\`, `documents\`,
  `outbox\`) alone.
- **Kept, because Wizard uses it:** the document converter and the commands it runs in a process of its own
  (`scripts/wizard_docs.py`: `convert` for attached files and task files, `design` for `wizard_task_design`, `edit` and
  `save-copy` for `wizard_edit_attachment`, `outlook-draft` for the Email button); the knowledge standard at
  `templates/content/schema/knowledge-standard.md` (`wizard_kb_standard`); `kb.py`'s writes (task notes, portal maps,
  the Pages site, Test connection); `scripts/validate_content.py` and `scripts/make_provision.py`; and `.geminiignore`,
  which keeps a Gemini CLI session started in the install folder away from sign-ins and secrets.
- **The users' read-only token** is checked by Settings → Knowledge base → **Test connection**, with the same request
  every PC's sync makes, so `kb-check` has no successor.
- **A new, empty repository** needs no publishing step: Test connection with the write token gives it its first commit
  (a README, through GitHub's contents API, because its Git data API refuses an empty repository), and so does
  Wizard's first write of any kind (a task's save, a portal map, the Pages site).
- **The knowledge standard** no longer points to the kit: source ids come from the files a task reads
  (`wizard_task_read_file`: `S-` and 8 hex characters of the SHA-256; `A-...` ids of experts' answers already in notes
  stay valid); a proposed change to a signed note goes in the task's summary; the validator runs on every save; a
  dataset note's structure comes from the database itself, read with `wizard_query_postgresql` from the catalog
  tables.

**Consequences.**
- Nothing on a PC can overwrite or delete a note in the repository: a note changes only by a task's commit or on
  GitHub.
- A work PC's `content\` folder, where one exists, is no longer published or refreshed; its notes are older than the
  repository's.
- Converting a folder in bulk, exporting Outlook mail, the PostgreSQL catalog export, the Big Data Portal's anonymous
  check and the expert quizzes are gone; a task that needs one of them needs a tool in Wizard first. The provisioning
  file is made with **Export settings…** in the tray or with `scripts/make_provision.py`.
- Older decision records and build-report entries still describe the kit: they are history.

**Evidence.** `tests/unit/test_kb_repository.py` (was `test_kb_publish.py`): a task's first save into an empty
repository, through Wizard's own writer, starts it with the README, then a portal map follows; Test connection starts
an empty repository once and refuses a public, archived or read-only one without writing; Test connection with both
tokens on an empty repository; every earlier write and refusal test. `tests/unit/test_site.py`: the Pages site as the
first thing published to an empty repository. `tests/unit/test_workpc.py`: no kit in the repository, and setup removes
what earlier versions installed. `tests/unit/test_documents.py`: the convert command masks contacts and keeps an
email's attachments.
