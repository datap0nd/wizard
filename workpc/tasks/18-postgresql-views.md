# Task 18 — Document the PostgreSQL materialized views

**Goal:** a data dictionary of every materialized view on the PostgreSQL server, written from the server's own catalog
(the source of truth) and explained with the user's documents: what one row is, what every column means and how it is
computed, where the data comes from, and how fresh it is.
**Output:** `content\knowledge\platforms\postgresql.md`, `content\knowledge\datasets\*.md` and the export in
`content\inbox\postgres\` (internal) · **Shareable:** counts only.
**Model:** the strongest your plan lists under `/model`. The export itself is not AI.

## Steps

1. **Connect.** `.\docs.ps1 postgres-check`.
   - "no PostgreSQL connection settings": ask the user to add these lines to `.env` in this folder. They edit it
     themselves: you never open `.env`.
     `WIZARD_PG_HOST`, `WIZARD_PG_PORT`, `WIZARD_PG_DATABASE`, `WIZARD_PG_USER`, `WIZARD_PG_PASSWORD`, and optionally
     `WIZARD_PG_SSLMODE` (`prefer` by default).
     The account must be a **read-only** one, such as Metronome's freshness-scanner account (`PGUSER`), never the
     uploader account. If the scanner's `PGHOST`/`PGUSER`/`PGPASSWORD` variables are already set on this PC, they are
     used without any `.env` change.
   - `FAIL session is read-only`: stop and tell the user.
   - `WARN elevated rights`: tell the user and continue only if they agree.
2. **Export.** `.\docs.ps1 postgres-catalog` exports every database the account can connect to; add `--database <name>`
   or `--schema <name>` to limit it. It writes one file per materialized view and a `00-overview.md` to
   `content\inbox\postgres\<database>\`. Notes in those files say which steps were skipped (a view being refreshed, a
   timeout). Then run `.\docs.ps1 extract`, so every export file (and the user's documents) gets a source id.
3. **Read.** Read `content\schema\knowledge-standard.md` (all of it, section 10 most carefully) and each
   `00-overview.md`. Ask the user which documents describe the database (for example the PowerPoints they added) and
   read their converted text in `content\inbox\_text\`.
4. **Platform guide.** Write `content\knowledge\platforms\postgresql.md` (`type: platform`, at most 600 words): what the
   server is for, its databases and schemas, how data arrives (as the documents and the lineage show), how the
   materialized views are refreshed (pg_cron schedules from the export), naming conventions, and pitfalls (for example
   columns kept as text, freshness unknown when commit timestamps are off). Add how to find a dataset note.
5. **One dataset note per materialized view**, as section 10 of the standard describes:
   `content\knowledge\datasets\<schema>-<view>.md`, `type: dataset`.
   - Structure comes only from the export, cited with its source id: grain, every column, types, how each column is
     computed (read it from the SQL definition), lineage, refresh, ranges and value lists.
   - Meaning comes from the documents, cited too. A column neither explains is `UNKNOWN` plus an open question.
   - When a document disagrees with the export, the export wins; record the document's claim under
     `## Conflicting information`.
   - No sums or other business figures. Put the owner role in `content\register\stakeholders.md` as someone to quiz,
     not in the note.
   - Five views per round, then `.\docs.ps1 validate` and fix every error. Give the user one line per round.
6. **Re-runs.** When the server changes, repeat steps 2-5: update the existing notes (same ids), add new views, and for
   a view that no longer appears add "(removed from the server as of <date>)" to its title and tell the user.
7. Suggest quizzing the database owner on the open questions (task 30).

**Done when:** every materialized view in the export has a dataset note, the platform guide exists, and
`.\docs.ps1 validate` reports no errors. Record in `STATUS.md` the number of views documented and open questions.
