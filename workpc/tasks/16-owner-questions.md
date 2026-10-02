# Task 16 — Questions for the data owners

**Goal:** one list the user can send to each platform owner, so drafts can be confirmed and signed.
**Output:** `content\register\open-questions.md` (internal) · **Shareable:** counts per platform only.

## Steps

1. Collect every `UNKNOWN`, `UNCERTAIN:` caveat and "Open questions" item from `content\knowledge\**` and
   `content\contracts\sources\*.json`, plus the MISSING and UNCLEAR fields from `content\register\coverage.md`.
2. Group them by platform and then by report. Merge duplicates. Write each as a closed question the owner can answer
   quickly (for example "Is `stock_units` a month-end balance? yes / no").
3. Add a short section per platform asking the owner to confirm: report owner name, refresh schedule, whether rows may
   be read through an API, and who can grant read access.
4. Use checkboxes (`- [ ]`) so answers can be ticked off.

**Done when:** every open item appears exactly once. Record the number of questions per platform in `STATUS.md`.
