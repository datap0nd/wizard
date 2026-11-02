# Documentation guide: what Gemini reads, how it is written, where it lives

Company documentation reaches Wizard one way: **tasks** in Settings → Tasks write it to the company's knowledge-base
repository, the master copy ([decision](decisions/2026-11-02-tasks-only-writer.md)).

## Structure

| Layer | Format | File | Read by Gemini through |
|---|---|---|---|
| Company documentation (organisation, products, markets, processes, glossary, FAQ, decisions) | Markdown with front matter, one topic per note | `knowledge/<area>/<note>.md` | `wizard_lookup_definitions` (search), `wizard_browse_knowledge` (index), `wizard_read_knowledge` (by id) |
| Platform guide (one per platform) | Markdown with front matter, ≤600 words | `knowledge/platforms/<platform>.md` | `wizard_list_sources` names it; the knowledge tools return it |
| Report catalog (one per platform, one entry per report) | JSON validated by `contracts/source-contract.schema.json` | `contracts/sources/<platform>.json` | `<platform>_search_reports`, `<platform>_get_report_schema`, `wizard_search_catalog` |
| Business definitions (cross-platform): what a measure means and where the data holds it (dataset, filters, example query) | Markdown with front matter | `knowledge/metrics/<topic>.md`, `knowledge/calendar.md`, … | the knowledge tools |

Every note follows [the knowledge standard](../templates/content/schema/knowledge-standard.md): flat front matter (`id`,
`title`, `type`, `status`, `owner`, `summary`, `aliases`, `tags`, `related`, `sources`, `updated`, `reviewed`,
`reviewed_by`), the answer in the lead, self-contained `##` sections, a source id on every fact, `UNKNOWN` instead of
guesses, no performance figures and no personal data. Report entries carry the fields listed in
[platforms.md](platforms.md); the aggregation rule per measure (`sum`, `sum_same_currency`, `last`, `none`) matters
most, because Wizard's tools enforce it.

## How Wizard's analyst finds a note

- **Search** ranks `##` sections (each glossary entry on its own) with BM25 and boosts a note's title, aliases, tags,
  id and summary; common words do not count. A long note returns its lead plus the matching sections and the headings
  it left out; a short one returns whole.
- **Browse** lists every area and note with its one-line summary, like a table of contents.
- **Read** returns up to five notes in full by id.
- Every result carries the approval status, and when an expert last confirmed the note. Wizard says when it relies on
  an unsigned note.
- `glossary/ambiguous-terms.md` lists words that mean different things ("sales": sell-in, sell-out or revenue) with
  the question to ask, so Wizard clarifies instead of guessing.

## Where

- **This repository (public GitHub):** application code, the knowledge standard and SYNTHETIC examples only. No
  company content.
- **Real documentation:** the company's private knowledge-base repository on its GitHub Enterprise Server
  ([desktop.md](desktop.md)). Every PC syncs it with a read-only token and checks each commit before using it; a task
  writes notes to it with the write token entered on the PC that runs it. On a test install, a local folder laid out
  the same way can stand in for it (`WIZARD_CONTENT_DIR`, with the `gemini-cli` or `code-assist` runtime); the
  synthetic examples are then not loaded. A folder with notes but no report catalogs yet is accepted.
- **Raw sources** (decks, workbooks, mail) stay on the person's PC: a task reads the folder it is given, and the notes
  cite each file by its source id.
- `wizard_kb_save_notes` checks every note before saving it; `uv run python scripts/validate_content.py <folder>` runs
  the same checks on a folder in a development checkout, and every sync applies them before using a commit.
- Real content can only *describe* reports: every report is `NAVIGATION_ONLY` with no data file. PostgreSQL is the
  exception, and not through reports: Gemini queries it directly with SQL, guided by the dataset notes.

## How the company documentation is produced

**Tasks** (owner, 31 October 2026) are instructions the Wizard team writes in the repository's `tasks/` folder. They
appear in Wizard's **Settings → Tasks** without an update; each runs as a Gemini run in a conversation of its own and
saves the notes it writes to the company knowledge base (`wizard_kb_save_notes`: whole notes, checked against the knowledge
standard, one commit per save). Only a task run saves notes.

A task may ask for a folder or file on the PC ([decision](decisions/2026-11-01-folder-tasks.md)). "Digest a folder of
presentations into the knowledge base" reads every deck in a folder, in rounds, and adds terms, measure definitions,
processes, organisation, products, markets and standing decisions to the notes, each fact cited by its deck's source
id. "Write the company's presentation guide from its decks" reads how the decks look (theme, fonts, layouts, logo and
labels, as PowerPoint reads them) and how they are built, and writes the `presentations/` notes (knowledge standard,
section 12).

**Reading files.** Gemini cannot open Office files or Outlook mail. A task's files, like attached ones, go through
Wizard's converter, which drives Office through pywin32: it borrows a running application before starting one, opens
files read-only where they are, never runs macros and never saves a source. PowerPoint gives text, tables, SmartArt,
chart values, speaker notes and pictures of mostly visual slides; Excel gives a column profile with formulas, pivot
tables, charts and named ranges; Word keeps headings and tables; Outlook gives display names, the body and attachments.
Without Office, plain .docx/.pptx/.xlsx are read with the standard library. Email addresses and phone numbers are
masked.

**The PostgreSQL server** is documented from its own catalog, which is the source of truth for structure. A task that
writes or checks `datasets/` notes (`type: dataset`, knowledge standard section 10) reads it with
`wizard_query_postgresql`: columns, definitions, lineage, refresh jobs and the values of small code columns, never sums.
Documents explain meaning; where they contradict the database, the database wins.

## Files attached to questions

Executives can attach PowerPoint, Excel, Word, email and CSV files to a question in Wizard (upload, or "From this PC" on
local installs, which reads the original in place so protected files open). The same converter turns them into text;
Gemini reads them with `wizard_read_attachment`, and each read is evidence with data mode `USER_PROVIDED`: never
presented as a verified source. Spreadsheet sheets and CSV files are also kept as full typed tables, so Gemini can
filter, group and total every row with `wizard_query_attachment` rather than estimating from a sample.

## PostgreSQL: documentation, then Gemini's own SQL

The dataset notes are what Gemini reads before it queries a view: what one row is, every column's meaning, units,
refresh, and pitfalls. Wizard then gives Gemini one tool, `wizard_query_postgresql`, and Gemini writes the SQL the
question needs. Nothing is pre-declared per view and there is no sign-off step. Better notes, especially
`## Pitfalls`, are how answers improve. Add a rule only after an answer has gone wrong without it.

Answers from it are labelled "Live", and the sources drawer shows the exact SQL with its rows. The connection uses
`WIZARD_PG_*` in `.env`, else the `PG*` variables. A dedicated read-only role is best.

## Review and sign-off

A note is a draft until its owner signs it in the knowledge-base repository: `status: SIGNED`, the owner's name in
`owner`, `reviewed` and `reviewed_by` (knowledge standard, section 7). An expert's check makes it *expert-checked*
(`reviewed`, `reviewed_by`) but does not sign it. Report entries are reviewed per platform by the source owner
(description, grain, units, aggregation rule, caveats, sensitivity) and stay `NAVIGATION_ONLY` until a live adapter and a signed parity check exist
([source-onboarding.md](source-onboarding.md)).
