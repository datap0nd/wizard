# Start here

You are preparing a Wizard installation on a work PC. Work through the task files in this folder in numeric order.

## For every task

1. Read `outbox\STATUS.md` (create it from the table below if it does not exist). Skip tasks already marked `done`
   unless the user asked to redo one.
2. Read the whole task file before acting. Read `..\GEMINI.md` (the install folder rules) once at the start.
3. Do the steps. Ask the user when a step needs a person (for example a missing document) and wait for the answer.
4. Write the outputs exactly where the task says.
5. Update the task's row in `outbox\STATUS.md`: `done`, `blocked` or `partial`, plus one line saying why.
6. Give the user a two-line summary, then continue with the next task.

Stop and ask before changing `.env`, deleting anything, or running any command that is not read-only.

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
| 90 Feedback pack for the developer | todo | | |
```

## What may leave this PC

Some results are written to be pasted back to the developer (Claude) who builds Wizard; each task says which.
Shareable files contain no report names, column names, owners, project ids, emails or data: only versions,
pass/fail results, counts and error messages. Everything under `content\` stays internal.
