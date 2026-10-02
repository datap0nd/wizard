# Task 12 — Report catalogs

**Goal:** one catalog per platform describing every report precisely enough for Wizard's analyst to pick the right one.
**Output:** `content\contracts\sources\<platform>.json` and `content\register\source-register.csv` (internal)
· **Shareable:** counts only.

## Steps

1. Read `content\GEMINI.md`, the schema `content\schema\source-contract.schema.json`, and the procedure in
   `content\.gemini\commands\wizard\report-catalog.toml` (the text inside `prompt = """ ... """`; where it says
   `@{schema/source-contract.schema.json}`, use the schema file you just read).
2. For each platform with a report list or report definitions in `content\inbox\<platform>\`, follow that procedure.
   Paths are relative to `content\`. If `content\inbox\asap\asap.draft.json` exists (made by the ASAP metadata
   importer), start from it: it already holds names, columns and prompts; add descriptions, units, aggregation rules
   and caveats.
3. Never invent a report, column, prompt or unit. Every uncertain choice gets a caveat starting with `UNCERTAIN:`.
   Every report stays `"row_access": "NAVIGATION_ONLY"` with `"file": null`.
4. After each platform, run the validator from task 15 and fix what it reports before moving on.

**Done when:** every platform with report material has a catalog that passes the validator. Record per platform in
`STATUS.md`: number of reports, number with `UNCERTAIN` caveats, validator errors remaining.
