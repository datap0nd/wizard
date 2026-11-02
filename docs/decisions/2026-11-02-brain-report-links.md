# 2026-11-02 — The Brain page links each mapped report to the notes it names

**Owner:** project owner. **Status:** decided (2 November 2026).

**Context.** The owner, looking at the Brain page after mapping two portals: "If I check the brain section, I see ASAP
and GSCM with hundreds of dots (GSCM is still at 20 but I didnt fully map it yet). But I dont see connections with the
rest of the knowledge base. Means that they're mapped but not interconnected no?"

They are interconnected, but the page did not show it. Since 30 October each mapped report in a portal map can say which
knowledge notes define its terms (`definitions`, written by `portal_map_route` with `use_for` and `not_for`), and Wizard
uses that link: `wizard_lookup_definitions` and `wizard_read_knowledge` list the mapped reports that name a note, and
the portal map's search weighs it. The Brain page drew each mapped report as a point joined only to its portal (`brain.py`, `portal_reports`), so the
links in the maps were hidden, and the page could not show which mapped reports name no note yet.

**Options.** (1) Leave the page as it is and explain. (2) Draw a link from each mapped report to each note it names, as
its own kind of link, and count per portal how many mapped reports are linked. (3) Also infer links from a report's name
or `use_for` matching a note's title: a guess the maps do not hold, so the page would show links Wizard does not use.

**Decision.** Option 2.
- **What the server sends** (`GET /api/v1/brain`, `brain.py`). Each drawn portal report carries `definitions`: the ids in
  its map's `definitions` that are notes in the loaded knowledge base (an id no note has is left out, a repeat kept once,
  at most 8, as a map holds), and `use_for` (at most 5 phrases of 120 characters, metadata only), for its card. Each
  portal's `mapped` gains `linked` (mapped reports naming at least one note) and `unlinked`; the counts gain
  `linked_reports` and `report_links`. A report only found (`todo`) is still counted, not drawn. Nothing is written.
- **What the page draws** (`graph3d.ts`, `Graph3D.tsx`). A link from each report to each note it names, a link kind of its
  own (`defines`) on its own layer, **Reports to their notes**, on by default: straight and dashed, in one light neutral
  ink, never a community's colour, so it reads apart from the notes' own curved, coloured links. The page has one theme,
  dark (decision 2026-10-28). The link is in the force layout as strongly as the link to the portal, so a linked report
  settles between its portal and its notes, near the notes; it also counts when the communities are found. A report that
  names no note is drawn at 40 % of its usual opacity. A page published to the Pages site before this change has no
  `definitions`: its reports are drawn as before, neither linked nor faint.
- **What the page says.** The Sources panel: "120 mapped, 87 linked to notes", with the linked share as a thin bar; the
  layer's count is the number of links; the legend line says what the dashed line and a faint report mean. A report's
  card (hover or click): its menu path, "Used for" its phrases, and "Defined in" its notes' titles, or "Not linked to a
  note yet"; its links are listed among its edges as definitions. The tour's systems step says "ASAP (120 reports mapped,
  87 linked to notes)". The statistics count the links with the other edges.
- **Fast with thousands of reports.** At most 3,000 report points (as before) and 8 links each. The drawing reuses its
  buffers from frame to frame and groups the edges by stroke with a counting sort, so a frame allocates nothing per point
  or per edge; the dashes are long and butt-ended, which costs little more than solid lines.
- **The Dashboards system joins the dashboards area.** As a portal joins its platform notes, the Dashboards system
  (`dashboards`) is documented by every note in the knowledge base's `dashboards/` area (knowledge standard, section 13:
  one note per dashboard), and the area is named "Dashboards" in the standard's order, after the data dictionary.
- **Unchanged.** The page writes nothing and stays out of Gemini's tools; the demo arrival (N) and the tour work as
  before.

**Consequences.** The page shows the links Wizard already uses, and how much of a portal is still to route: a portal
mapped but not routed ("20 mapped, 0 linked to notes") shows its reports faint around it. A report naming a note this PC's
knowledge base does not have (a note renamed or removed since) is drawn unlinked; routing it again
(`portal_map_route`) fixes it. A large linked portal spreads its reports over the graph, so its portal's links cross the
picture: in Chromium's software rendering (headless, no graphics card), 2,400 invented reports with 2,189 links turn at
26 to 28 frames a second, 35 with the links' layer off (the portals' longer links remain), against 56 with the same
reports unlinked and gathered around their portals. The frame rate on a work PC's graphics card has not been measured.

**Evidence.** `tests/unit/test_brain.py` (a report's notes kept only when the note exists, repeats, the cap, `use_for`
trimmed, per-portal and total counts, the API reading a map on the PC, the Dashboards system documented by the
dashboards area); `apps/web/src/graph3d.test.ts` (the link kind, the cap, a report's `linked`, the layer and its
switching, the colour apart from the palette, the statistics, a linked report laid out nearer its note than an unlinked
one); `apps/web/src/brain.test.ts` (the Sources line, the tour, the dashboards area's line);
`apps/web/src/components/brain/BrainPage.test.tsx` (the Sources panel, the layer's count, a report's card linked and
not); the e2e test "on the Brain page, a mapped report links to the notes it names…", run in Playwright's Chromium; and
screenshots in Chromium at 1600×900 over the example knowledge base with 2,400 invented mapped reports (not committed).
