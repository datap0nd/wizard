# Start here

You are preparing a Wizard installation on a work PC. Work through the task files in this folder in numeric order.

Two tracks:
- **00-18 and 90: installation and data platforms** (environment, platform guides, report catalogs, switching Wizard to
  the real catalog, and 18: a data dictionary of the PostgreSQL materialized views, written from the server's catalog).
  Run 18 on its own with `/wizard:tasks 18`.
- **20-25 and 30-31: company documentation.** Collect the user's Outlook mail and files (20), digest every source with
  Gemini 3.5 Flash (21), plan the notes (22), write them (23), build the glossary and ambiguous terms (24), check
  coverage (25), then send expert quizzes (30) and apply the answers (31). The user can run one track with, for
  example, `/wizard:tasks 20-25`. Each task names the model it works best with; ask the user to switch with `/model`
  when the status bar shows another one.

## For every task

1. Read `outbox\STATUS.md` (create it from the table below if it does not exist). Skip tasks already marked `done`
   unless the user asked to redo one.
2. Read the whole task file before acting. Read `..\GEMINI.md` (the install folder rules) once at the start.
3. Do the steps. Ask the user when a step needs a person (for example a missing document) and wait for the answer.
4. Write the outputs exactly where the task says.
5. Update the task's row in `outbox\STATUS.md`: `done`, `blocked` or `partial`, plus one line saying why.
6. Give the user a two-line summary, then continue with the next task.

Stop and ask before changing `.env`, deleting anything, or running any command that is not read-only. The commands of
`.\docs.ps1` (converting documents, exporting chosen Outlook folders, counting, checking) are the exception: they only
read the user's files and mailbox and write inside `content\` and `documents\`.

If `outbox\STATUS.md` exists but lacks a row of the table below, add the row (tasks are added by updates).

## outbox\STATUS.md template

```
| Task | Status | Note | Updated |
|---|---|---|---|
| 00 Environment report | todo | | |
| 10 Document inventory | todo | | |
| 11 Platform guides | todo | | |
| 12 Report catalogs | todo | | |
| 13 Business definitions | todo | | |
| 14 Question coverage | todo | | |
| 15 Validate content | todo | | |
| 16 Open questions for owners | todo | | |
| 17 Switch Wizard to the real catalog | todo | | |
| 18 Document the PostgreSQL materialized views | todo | | |
| 20 Collect emails and files | todo | | |
| 21 Digest every source | todo | | |
| 22 Topic map | todo | | |
| 23 Write the documentation | todo | | |
| 24 Glossary and ambiguous terms | todo | | |
| 25 Coverage check | todo | | |
| 30 Expert quizzes | todo | | |
| 31 Apply the stakeholders' answers | todo | | |
| 90 Feedback pack for the developer | todo | | |
```

## What may leave this PC

Some results are written to be pasted back to the developer (Claude) who builds Wizard; each task says which.
Shareable files contain no report names, column names, owners, project ids, emails or data: only versions,
pass/fail results, counts and error messages. Everything under `content\` stays internal.
