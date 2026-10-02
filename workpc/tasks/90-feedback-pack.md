# Task 90 — Feedback pack for the developer

**Goal:** one file the user can paste to the developer (Claude) who builds Wizard, with nothing internal in it.
**Output:** `outbox\FEEDBACK-FOR-CLAUDE.md` · **Shareable:** yes, that is its purpose; the user reviews it first.

## Steps

1. Combine: `outbox\STATUS.md`; `outbox\00-environment.md`; the counts table from `outbox\10-inventory.md`;
   `outbox\14-coverage-summary.md`; `outbox\15-validation.md`; `outbox\17-switch.md` if it exists.
2. Add a section **"What the user saw"** with these questions for the user to answer in their own words (ask them now
   and write their answers): Did `start.ps1` open Wizard? Did linking the Gemini account work? What happened with the
   first question (paste any error shown in the app or in the Wizard console window)? What felt wrong or slow?
3. Check the whole file and remove anything internal: report names, column names, owner or person names, emails,
   project ids, internal hostnames or URLs, file paths with user names, and any numbers taken from company data.
4. Tell the user the file is ready and ask them to read it before sharing.

**Done when:** the file exists, the user's answers are in it, and it contains no internal details.
