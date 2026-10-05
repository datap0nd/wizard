# Task 10 — Document inventory

**Goal:** know what documentation exists for each data platform before writing anything.
**Output:** `outbox\10-inventory.md` (internal) · **Shareable:** only the counts table at the end.

## Steps

1. Run `.\docs.ps1 extract` first: Office files and emails are converted to text in `content\inbox\_text\` (you
   cannot read them otherwise). PDFs and images you read directly. List the subfolders of `content\inbox\` (not the
   ones starting with `_`). Each subfolder is one platform, named by its short lowercase id
   (`asap`, `gscm`, `nerp`, and possibly `smartswitch`, `share`, others). If documents sit directly in `content\inbox\`
   or a folder name is unclear, ask the user which platform they belong to.
2. For every file: name, type, size, and a one-line description of what it contains after reading it
   (platform overview, Q&A, report list, report definition, field dictionary, screenshot, other).
3. For each platform, mark what is available:
   - an overview of the platform (how it is organised, how reports and prompts work)
   - a list of its reports
   - report definitions or field lists (columns, measures, units, prompts)
   - business definitions (fiscal calendar, market and model codes, metric meanings)
4. Wizard's first questions need: marketing spend (NERP), sell-in / sell-out / channel stock (GSCM), market share by
   brand, Smart Switch switching by origin brand with coverage, installed base and app usage (often ASAP). List which of
   these have no documentation yet, and ask the user to add what they can to `content\inbox\<platform>\`.

## Write `outbox\10-inventory.md`

Sections: per platform (files and what each holds), missing material, then a final **counts table**
(platform | files | has overview | has report list | has field definitions) that is safe to share.

**Done when:** every inbox file is listed and every platform has its availability marked.
