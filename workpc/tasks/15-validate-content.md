# Task 15 — Validate the content folder

**Goal:** make sure Wizard will accept `content\` (it refuses to start on any error).
**Output:** `outbox\15-validation.md` · **Shareable:** yes, after replacing report ids with `<report>`.

## Steps

1. Run the validator from this folder:
   ```
   $c = Get-Content current.json -Raw | ConvertFrom-Json
   & $c.python (Join-Path $c.release 'scripts\validate_content.py') content
   ```
2. Fix every `ERROR` by correcting the content (never by weakening the rule): wrong ids, unknown folders, missing
   units, percentages marked for summing, missing front matter, stray data files. If a fix needs a decision you cannot
   take from the documentation, add an `UNCERTAIN:` caveat or an open question instead and ask the user.
3. Re-run until it prints `OK` with 0 errors. Warnings (missing descriptions, `UNCERTAIN` choices) are allowed; list
   them for the owners.

## Write `outbox\15-validation.md`

The final validator summary line, the number of warnings by kind, and any errors you could not fix, with report ids
replaced by `<report>`.

**Done when:** the validator reports 0 errors, or the remaining errors are explained.
