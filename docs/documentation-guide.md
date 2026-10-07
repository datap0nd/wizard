# Documentation guide: what Gemini reads, how it is written, where it lives

## Structure

| Layer | Format | File | Read by Gemini through |
|---|---|---|---|
| Company documentation (organisation, products, markets, processes, glossary, FAQ, decisions) | Markdown with front matter, one topic per note | `knowledge/<area>/<note>.md` | `wizard_lookup_definitions` (search), `wizard_browse_knowledge` (index), `wizard_read_knowledge` (by id) |
| Platform guide (one per platform) | Markdown with front matter, ≤600 words | `knowledge/platforms/<platform>.md` | `wizard_list_sources` names it; the knowledge tools return it |
| Report catalog (one per platform, one entry per report) | JSON validated by `contracts/source-contract.schema.json` | `contracts/sources/<platform>.json` | `<platform>_search_reports`, `<platform>_get_report_schema`, `wizard_search_catalog` |
| Business definitions (cross-platform): what a measure means and where the data holds it (dataset, filters, example query) | Markdown with front matter | `knowledge/metrics/<topic>.md`, `knowledge/calendar.md`, … | the knowledge tools |
| Inventory register, topic map, quiz and review logs (people only) | CSV / Markdown | `register/` | not read by Gemini |

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

- **This repository (public GitHub):** application code plus SYNTHETIC examples only. No company content.
- **Real documentation:** the `content\` folder of the Wizard install on the work PC, created from
  [`templates/content/`](../templates/content/README.md). It becomes its own internal repository on the corporate Git
  server. Wizard reads it when `WIZARD_CONTENT_DIR` points at it (with the `gemini-cli` or `code-assist` runtime); the
  synthetic examples are then not loaded. A folder with notes but no report catalogs yet is accepted.
- **Raw sources** (Outlook exports, decks, workbooks, PDFs), their converted text (`inbox/_text/`) and the digests
  (`inbox/_digests/`) stay in `inbox/` on the work PC and are never committed.
- Validate with `.\docs.ps1 validate` on the work PC, or `uv run python scripts/validate_content.py <folder>`; Wizard
  applies the same checks at start-up and will not start on errors.
- Real content can only *describe* reports: every report is `NAVIGATION_ONLY` with no data file. PostgreSQL is the
  exception, and not through reports: Gemini queries it directly with SQL, guided by the dataset notes.

## How the company documentation is produced (Gemini CLI on the work PC)

Gemini CLI, signed in with the user's work account, does the reading and writing; you follow along and decide. The
tasks are Markdown prompts in `tasks\` (`/wizard:tasks 20-25`, then `30-31`):

1. **Collect (20).** Outlook folders and dates the user chooses (`.\docs.ps1 outlook-export`; private and confidential
   items skipped), plus files copied into `content\inbox\files\` or read in place from folders listed in
   `content\inbox\_sources.txt` (for NASCA files). `.\docs.ps1 extract` converts everything to text.
2. **Digest (21)**, best with Gemini 3.5 Flash: one short digest per source (summary, facts with locations, terms,
   ambiguous words, experts, worth, topics). Sensitive sources are marked and not used.
3. **Plan (22):** topic map and stakeholders, approved by the user.
4. **Write (23, 24)** with the strongest model: notes, glossaries and ambiguous terms.
5. **Coverage (25):** every high-worth source is cited by a note or explained.
6. **Expert quizzes (30, 31):** one HTML page per area and stakeholder, 10-15 questions (confirm a statement,
   multiple choice, free text where needed). The stakeholder opens it in Edge or Chrome, answers, clicks "Save my
   answers" and replies with the saved page; `.\docs.ps1 quiz-answers` reads it back and Gemini applies each answer,
   citing it as a source (`A-<quiz>-<question>`).

**Converting documents.** Gemini CLI cannot open Office files or Outlook mail. `.\docs.ps1` drives Office through
pywin32: it borrows a running application before starting one, opens files read-only where they are, never runs macros
and never saves a source. PowerPoint gives text, tables, SmartArt, chart values, speaker notes and pictures of mostly
visual slides; Excel gives a column profile with formulas, pivot tables, charts and named ranges; Word keeps headings
and tables; Outlook gives display names, the body and attachments. Without Office, plain .docx/.pptx/.xlsx are read with
the standard library. Email addresses and phone numbers are masked.

**The PostgreSQL server (task 18)** is documented from its own catalog, which is the source of truth for structure.
`.\docs.ps1 postgres-catalog` connects with a read-only account (`WIZARD_PG_*` in `.env`, else the scanner's `PG*`
variables) through pg8000, which is pure Python, so Application Control has no DLL to block. Its session is read-only,
with a 60-second statement timeout and a 2-second lock timeout. For every materialized view it exports:

- columns, types and comments;
- the SQL definition, which shows how every column is computed;
- indexes, lineage in both directions, and the pg_cron refresh job;
- statistics and freshness (from commit timestamps when tracked);
- a light profile: row count, null rates, distinct counts, date and period ranges, and the values of small code
  columns. Columns that name people are never listed, and no sums are taken.

Gemini CLI writes `knowledge/platforms/postgresql.md` and one `datasets/` note per view (`type: dataset`, knowledge
standard section 10). Documents explain meaning; where they contradict the export, the export wins.

**Platform material** (tasks 10-17) uses two Gemini CLI commands shipped in the content template:
`/wizard:platform-guide <platform> inbox/<platform>/` and `/wizard:report-catalog <platform> inbox/<platform>/`. For
ASAP, run `scripts/import_asap_catalog.py` first: it reads ASAP's own metadata and its draft becomes the input.

## Files attached to questions

Executives can attach PowerPoint, Excel, Word, email and CSV files to a question in Wizard (upload, or "From this PC" on
local installs, which reads the original in place so protected files open). The same converter turns them into text;
Gemini reads them with `wizard_read_attachment`, and each read is evidence with data mode `USER_PROVIDED`: never
presented as a verified source. Spreadsheet sheets and CSV files are also kept as full typed tables, so Gemini can
filter, group and total every row with `wizard_query_attachment` rather than estimating from a sample.

## PostgreSQL: documentation, then Gemini's own SQL

Task 18's dataset notes are what Gemini reads before it queries a view: what one row is, every column's meaning, units,
refresh, and pitfalls. Wizard then gives Gemini one tool, `wizard_query_postgresql`, and Gemini writes the SQL the
question needs. Nothing is pre-declared per view and there is no sign-off step. Better notes, especially
`## Pitfalls`, are how answers improve. Add a rule only after an answer has gone wrong without it.

Answers from it are labelled "Live", and the sources drawer shows the exact SQL with its rows. The connection uses
`WIZARD_PG_*` in `.env`, else the `PG*` variables. A dedicated read-only role is best.

## Review and sign-off

A note is a draft until its owner signs it: `status: SIGNED`, the owner's name in `owner`, recorded in
`register/review-log.md`. An expert's quiz answers make it *expert-checked* (`reviewed`, `reviewed_by`) but do not sign
it. Report entries are reviewed per platform by the source owner (description, grain, units, aggregation rule,
caveats, sensitivity) and stay `NAVIGATION_ONLY` until a live adapter and a signed parity check exist
([source-onboarding.md](source-onboarding.md)).
