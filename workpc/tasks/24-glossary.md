# Task 24 — Glossary and ambiguous terms

**Goal:** Wizard knows every internal acronym and asks the right clarifying question when a word can mean several things.
**Output:** `content\knowledge\glossary\*.md` (internal) · **Shareable:** counts only.
**Model:** the strongest your plan lists under `/model`.

## Steps

1. Collect every line under "Terms:" and "Ambiguous:" in `content\inbox\_digests\*.md`, plus the acronyms and
   `aliases` in the notes under `content\knowledge\`.
2. Group the terms by domain (finance, sales, supply chain, marketing, product, platforms and IT, organisation,
   general) and write one `content\knowledge\glossary\glossary-<domain>.md` per domain, as described in section 5 of
   `content\schema\knowledge-standard.md`: `type: glossary`, one bullet per term, sorted A to Z, at most 60 entries per
   note (split a domain if needed), every entry with its source ids. An expansion no source gives is
   `UNKNOWN expansion` plus an open question.
3. Write `content\knowledge\glossary\ambiguous-terms.md` (`type: glossary`). One entry per term that sources use in
   different ways ("sales", "share", "quarter", "market", "active", "stock", "launch"...): each meaning and where it is
   used, the question Wizard should ask, and the usual meaning if the sources show one (else `UNKNOWN`), with source ids.
   For a measure ("sales": sell-in, sell-out or revenue; units or currency; actual or plan), name the metric note that
   says where each meaning is read (`See sell-in-sell-out`).
4. Link: add the glossary notes to `related` of the notes that use their terms, where helpful.
5. Run `.\docs.ps1 validate` and fix every error.

**Done when:** every collected term is in a glossary note or listed as an open question, and the validator reports no
errors. Record in `STATUS.md` the number of terms and ambiguous terms.
