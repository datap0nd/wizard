# Task 11 — Platform guides

**Goal:** one short guide per platform that Wizard's analyst reads before searching that platform's reports.
**Output:** `content\knowledge\platforms\<platform>.md` (internal) · **Shareable:** counts only.

## Steps

1. Read `content\GEMINI.md` (authoring rules) and `outbox\10-inventory.md`.
2. Read the procedure in `content\.gemini\commands\wizard\platform-guide.toml` (the text inside `prompt = """ ... """`).
   Follow it with these adjustments: the platform id is the inbox folder name, the documentation is every file in
   `content\inbox\<platform>\` (read Office files and emails as their converted text in
   `content\inbox\_text\<platform>\`), and the output path is `content\knowledge\platforms\<platform>.md`.
3. Do this for every platform that has documentation. If a guide already exists with `status: SIGNED`, do not change
   it; list proposed changes in your summary instead. If it exists as a draft, update it.
4. Keep the open questions in each guide; they feed task 16.

**Done when:** every documented platform has a guide with the exact front matter format, at most 600 words, and no
invented facts. Record in `STATUS.md` how many guides were written and how many open questions each has.
