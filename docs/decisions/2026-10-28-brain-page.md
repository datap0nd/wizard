# 2026-10-28 — The Brain page: what Wizard knows, as one picture, beside the app

**Owner:** project owner. **Status:** decided (28 October 2026).

**Context.** The owner is presenting Wizard to the MENA President and wanted "a 'brain' view with all the topics, the
portals, etc", the curated news table (about 1,500 articles, categorized) shown as an ongoing automation, and asked:
"the brain view could be something additional. I dont want to mess with the original functionality."

**Decision.**
- **A page of its own.** `/brain` is a separate page, like `/quick` and `/r/<id>`. The chat, the sidebar, the systems
  stage and Settings are unchanged; nothing in the app links to it. On the desktop app it opens in the browser at
  `http://127.0.0.1:8771/brain` (tray: Open Wizard in the browser, then add `/brain`).
- **Everything on it is read.** `GET /api/v1/brain` maps the loaded knowledge base (areas, notes, each note's own
  `related` links, plus each note's three strongest topic links: two or more shared tags), the systems this person may
  use (as on the systems stage) and the reports catalogued in each, within their report rights. The note text stays in
  the app; the page gets titles, summaries, types and status. The repository is never named.
- **The news is read live, with fixed queries.** `GET /api/v1/brain/live` counts the tables and views the read-only
  account can read, and reads the news table: found as the readable table or view called `news` (else the one whose
  name contains "news" with the most news-like columns, in the default database first), or named by
  `WIZARD_NEWS_TABLE` / `WIZARD_NEWS_DATABASE`. Its columns are matched by name. Five fixed statements (the catalog
  lookup, totals, categories, articles per week, the 40 latest) run through `PostgresQuery`, so each is one statement as
  a subquery, in a READ ONLY transaction that is rolled back, on a fresh connection closed after the call, under the
  read-only account. Only people who may read the whole database see it (as for `wizard_query_postgresql`). The server
  is read at most every 45 seconds for everyone; the page asks every minute, and new articles are marked NEW. The page
  shows the table and the queries under "How this was read". Only web links open.
- **Not a Gemini tool.** Gemini's tools are unchanged; the page changes nothing Gemini can do or see.
- **Honest labels.** The example notes in this repository show as EXAMPLE CONTENT; a knowledge base that has not synced
  says so; the news is LIVE. The motion (pulses along the links, twinkling notes) is decoration and never says Wizard is
  reading something. A bad `WIZARD_NEWS_TABLE` never stops Wizard: the page says what is wrong.
- **For presenting.** A guided tour built from the counts it read (→ or Space next, ← back, Esc out, F full screen; a
  presenter clicker's Page Down / Page Up work).

**Evidence.** `tests/unit/test_brain.py` (9), `tests/integration/test_brain_postgres_real.py` (2, real PostgreSQL 16),
`apps/web/src/brain.test.ts` (8), the e2e test "the Brain page maps what Wizard knows…" in `apps/web/e2e/wizard.spec.ts`,
and screenshots of the page in Chromium at 1280×720, 1600×900 and 1920×1080 over a synthetic knowledge base of 111 notes
and a synthetic news table of 1,512 rows (not committed).
