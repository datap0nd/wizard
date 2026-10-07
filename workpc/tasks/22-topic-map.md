# Task 22 — Topic map

**Goal:** decide which notes to write, in which folder, in what order, and which stakeholder can check each area.
**Output:** `content\register\topic-map.md` and `content\register\stakeholders.md` (internal) · **Shareable:** counts only.
**Model:** the strongest your plan lists under `/model` (a Pro model if available, else `gemini-3.8-flash`).

## Steps

1. Run `.\docs.ps1 topics`, then read `content\inbox\_digests\_topics.md` (every topic, its score, sources and the
   experts mentioned), sections 1 and 2 of `content\schema\knowledge-standard.md`, and the list of existing notes under
   `content\knowledge\`.
2. Clean the topics: merge synonyms (`launch-gates` into `launch-process`), split topics that are really two notes,
   drop topics with a score of 1 unless they define something executives ask about. Always include:
   `glossary/ambiguous-terms`, one `glossary-<domain>` note per domain with many terms, `calendar`, one overview
   note per area, and one `metrics/<measure>` note (priority 1) for each measure executives ask about that a dataset
   note in `content\knowledge\datasets\` holds (sell-in, sell-out, channel stock, weeks of supply, revenue, share...),
   even when few documents discuss it. Existing metric notes keep their ids.
3. Write `content\register\topic-map.md`:

```
| Priority | Area | Note id | Title | Type | Sources | Stakeholders | State |
|---|---|---|---|---|---|---|---|
| 1 | processes | launch-process | Product launch process | process | 14: S-1a2b3c4d, S-... | Ana Silva | planned |
```

   Priority 1: what Wizard needs to understand an executive's question or read data correctly (definitions, ambiguous
   terms, metrics, calendar, who owns what, product line-up, markets, core processes). Priority 2: other recurring
   topics. Priority 3: nice to have. State is one of planned, written, quizzed, signed.
4. Write `content\register\stakeholders.md`: name, role, the areas they can confirm, and why (the sources that show it).
   Names and roles only, never contact details.
5. Show the user the priority 1 rows and the stakeholder list. Ask them to correct priorities, add missing topics and fix
   stakeholders. Apply their changes.

**Done when:** the user has approved the topic map and the stakeholder list. Record in `STATUS.md` the number of
planned notes per priority.
