# 2026-10-05 — Company documentation, expert quizzes and attached files

**Owner:** project owner. **Status:** decided (discussion of 5 October 2026).

**Context.** Wizard's analyst should understand what executives ask (internal acronyms, ambiguous words, who owns what,
how processes work) and clarify when needed. That knowledge lives in the owner's Outlook mail, decks, workbooks and
documents, many of them NASCA-protected. Only platform guides and a few metric notes existed, and the definitions tool
ranked notes by raw word counts.

**Options.**
1. Build documentation generation into the Wizard web app.
2. Run Gemini CLI on the work PC with Markdown task prompts, and give Wizard the converter and checks it needs.
3. A one-off manual write-up.

**Decision.** Option 2.
- **Gemini CLI does the reading and writing** (tasks 20-25), so the owner can follow along and the web app stays
  small. Bulk digests use Gemini 3.5 Flash; writing uses the strongest model available.
- **Office files are converted with pywin32 on the work PC**, following data_governance's proven rules: borrow a
  running application before `DispatchEx`, open read-only where the file is (NASCA binds access to its path), no
  SaveAs, macros off, restore settings, quit only what was started. pywin32 is in the portable runtime;
  `run.py --check` reports whether it loads. Without it, plain .docx/.pptx/.xlsx are read with the standard library.
- **Outlook is read only for folders and dates the owner chooses;** items marked private or confidential are skipped.
  This is a script the owner runs, not a Wizard tool: Wizard still has no email tool.
- **The documentation lives in the install's `content\` folder** (internal), never in this public repository.
  Notes follow `templates/content/schema/knowledge-standard.md`. Retrieval gains section-level search, a browse index
  and read-by-id (`wizard_browse_knowledge`, `wizard_read_knowledge`).
- **Experts check it through one self-contained HTML quiz per area and stakeholder** (10-15 questions), emailed by
  the owner and sent back as the saved page. Gemini CLI writes only the questions JSON into a fixed template, and
  answers are cited as sources. Documentation is a one-off effort: no review schedule.
- **Executives can attach files to a question.** The same converter runs in a time-limited child process. Gemini
  reads files with `wizard_read_attachment`. Each read is evidence with a new data mode, `USER_PROVIDED`: user-supplied
  and unverified. It ranks above SYNTHETIC and below approved sources.

**Consequences.**
- AGENTS.md lists `USER_PROVIDED` among the data modes.
- Wizard declares 18 tools.
- A content folder with notes but no catalogs is accepted.
- New settings: `WIZARD_ATTACHMENT_FOLDERS`, `WIZARD_MAX_ATTACHMENT_MB`, `WIZARD_ATTACHMENT_TIMEOUT_S`,
  `WIZARD_ATTACHMENT_OFFICE`.
- Source confirmation before answering ("here are the probable sources") is deferred.

**Evidence.**
- Unit tests for the converter, including fake-COM readers, the kit, the knowledge tools, attachments and the
  validator.
- The real Gemini CLI accepts all 18 tool schemas.
- pywin32 loads from a vendor folder in the x64 embeddable Python with `site` off, the work PC's layout.
- The quiz page was tested in a browser: it answers, copies, reopens with saved answers, and works at phone width.
- Office automation could not be exercised from the development session (`CO_E_SERVER_EXEC_FAILURE`). Its first real
  run is task 20 on the work PC, which reports every file it could not read.

## Addendum, 2026-10-06: PostgreSQL first

**Decision (owner).** Document the corporate PostgreSQL server first: its materialized views only, with a light
profile of the data.

- **Source of truth:** the server's catalog. The owner's decks explain meaning; where they disagree with the catalog,
  the catalog wins and the note records the conflict.
- **Account:** read-only, such as Metronome's scanner account, never the uploader.
- **Driver:** pg8000, pure Python, so Application Control has no DLL to block.
- **Workflow:** export with `.\docs.ps1 postgres-catalog`, then Gemini CLI task 18 writes the notes.
