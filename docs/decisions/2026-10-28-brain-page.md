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

**Update (28 October 2026, later): a demo arrival instead of real ones.** The owner: "The table is a static table.
I'm not updating anything. I want a fake 'new news article came in' animation, not an actual true sql query please."
- Pressing **N**, or reaching the tour's news step (2.5 seconds after it opens), plays the arrival: one of the table's
  own articles, below the top three and never the same one twice, slides in at the top as "just now" with NEW,
  "1 new article just arrived" and a flurry along the news synapses. It writes nothing and no count moves (the total
  stays the table's). It is the page's one staged motion, recorded in AGENTS.md.
- The page no longer watches for real new rows; it reads the news when it opens and every 10 minutes.
- For a table loaded in one go, recency and weeks count by publication date (the chart is "articles per week by
  publication date"), the right end of the chart names its last week, and "published in the last 7 days" and
  "newest … ago" show only when they say something recent. The tour's news step is "Reading the market".

**Update (28 October 2026, later): a simple and an advanced view, and more room for the news.** The owner: "in the
/brain, create a simple/advanced toggle, advanced is current view (more emphasis on the news on the bottom right, the
section is too small) and the simple one is without animations and the wizard logo and the cards at the bottom."
- **Simple / Advanced** in the header (V switches; `?view=simple` or `?view=advanced` opens one; the browser keeps
  the last choice). Advanced is the page as it was. Simple has no wizard in the middle, no counters along the bottom
  and nothing moving: the picture is drawn still, the news total does not count up, the headlines do not scroll. The
  tour and the demo arrival (N) still work there, without their motion.
- **The news gets the room** in both: a wider panel (420 px, 480 px on wide screens), a lower chart, the categories in
  two columns, and the latest articles list at least 220 px tall with larger headlines. With motion off (the simple
  view or the PC's reduced-motion setting) the chart's running-total line is drawn instead of left invisible.

**Update (30 October 2026): the knowledge base as a 3D graph, more serious.** The owner: "The knowledge base. I want
to create a neural network or graphify of the full knowledge base, in 3D", "And we replace the /brain, with that. A bit
more... serious", "make it scientific, and complex, but not overly ... quirky. keep news and tour."
- **The picture is a 3D graph of the whole knowledge base.** Points: the knowledge base at the root, each area, every
  note, every tag two or more notes share (up to 60 notes; more says little), every glossary term, the systems the notes
  document, and the news categories. Edges: each area to the root, each note to its area, the notes' own `related`
  links, **mentions** (a note's text naming another note by its id, title or an alias of at least four characters, as
  whole words; a name two notes share, or one found in more than a quarter of the notes, is left out; the 12 most named
  per note), shared tags (two or more; off at first, as the tag points show the same), a note to its tags and terms,
  a system to the notes that document it, the news table to the database and its categories. `GET /api/v1/brain` now
  also returns the glossary terms (up to 3,000), all of a note's tags (up to 15), its length in words, and each link's
  weight. Everything is still read; nothing is a Gemini tool.
- **Laid out by a force simulation in the browser** (`apps/web/src/graph3d.ts`): springs along the edges (membership
  pulls hardest, so each area forms its own module), Barnes-Hut repulsion through an octree (θ = 0.9), a weak pull to
  the middle; seeded, so the same knowledge base settles the same way, and a refresh keeps the places of the points it
  already had. Drawn on a plain canvas with a perspective camera: no new dependency.
- **Scientific, not decorative.** A flat dark surface, the validated dark categorical palette for the areas in their
  own order (a ninth area and beyond in grey; every area is also labelled in the graph and the legend), depth fading,
  a floor grid and an axis triad for orientation. Along the bottom, the note network's statistics: nodes, edges,
  note links m, mean degree ⟨k⟩, k max, density ρ, average clustering ⟨C⟩, modularity Q with the areas as communities,
  components, mean shortest path ⟨ℓ⟩ and diameter D (sampled from 200 notes above 800), and the degree distribution
  P(k); each explained on hover. The layout's state ("settled · 252 it.") shows beside them.
- **Gone:** the pixel wizard and his circle, the starfield, the pulses and twinkling, the counters along the bottom and
  the Simple / Advanced toggle (V). The graph turns slowly (Rotate turns it off; reduced motion never turns it and
  draws it only once settled).
- **Working it:** drag turns, the wheel zooms, a double click or R frames it again; hover shows a point, a click opens
  it with its edges by kind and the points it joins (each opens in turn); `/` searches notes, terms and tags; on the
  left, the areas (a click lights one up and frames it), the layers (related, mentions, shared tags, note to area,
  tags, terms, systems, news) with their counts, and the sources with their reports or tables.
- **Kept:** the news panel and its demo arrival (N), and the tour (→, ←, Esc, F), whose steps now frame what they
  speak of and label the notes they name. The intro says how many links are declared and how many are mentions.

**Evidence.** `tests/unit/test_brain.py` (10 since 30 October), `tests/integration/test_brain_postgres_real.py` (2, real PostgreSQL 16),
`apps/web/src/brain.test.ts` (8), the e2e test "the Brain page maps what Wizard knows…" in `apps/web/e2e/wizard.spec.ts`,
and screenshots of the page in Chromium at 1280×720, 1600×900 and 1920×1080 over a synthetic knowledge base of 111 notes
and a synthetic news table of 1,512 rows (not committed).

Evidence for the 30 October update: `tests/unit/test_brain.py` (mentions by id, title and alias; shared, short and
common names left out; terms, tags and words), `apps/web/src/graph3d.test.ts` (13: what is drawn, colours, sizes,
layers, a deterministic layout that keeps each note nearer its own area, carried places, the octree on 600 notes, the
camera, picking, focus, search, the statistics against hand-computed values), the e2e test "the Brain page shows the
knowledge base as a 3D graph…", and screenshots in Chromium at 1280×720, 1600×900 and 1920×1080 over a synthetic
knowledge base of 101 notes in 12 areas (681 links, 163 glossary terms, mapped by the real `knowledge_map`) and
synthetic news (not committed).
