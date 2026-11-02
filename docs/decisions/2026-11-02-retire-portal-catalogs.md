# 2026-11-02 — A portal Wizard has mapped is read through its map; its report catalog is retired

**Owner:** project owner. **Status:** decided (2 November 2026).

**Context.** Report catalogs (`contracts/sources/<system>.json` in the knowledge base) were written before Wizard read
the portals live. Each one generates `<system>_search_reports`, `<system>_get_report_schema` and `<system>_run_report`,
and feeds `wizard_search_catalog` and `wizard_list_sources`. Since 30 October Wizard keeps a live map of each portal it
explores ([decision](2026-10-30-portal-maps.md)): menu path and id, what each report is for, its filters and the data
request that reads it. A review of the knowledge base found the company's portal catalogs thin and out of step with the
maps: 14 of 15 entries carried UNCERTAIN caveats waiting for an owner, and one portal's catalog used report ids that
do not match the reports in its map. Gemini already had to be told that the catalog tools search only Wizard's
catalog, not the portal (decision of 30 October, "list the reports in GSCM" took 28 steps), and the content validator
asked for an owner review of every UNCERTAIN entry. Asked to decide what to do with the portal catalogs, the owner
answered: "your recommendation".

**Options.**
1. Keep both: review every catalog entry and keep it in step with the map by hand. Two descriptions of one portal,
   one of them always behind.
2. Generate the catalog from the map. The map is not a catalog (no typed columns or aggregation rules), so the result
   would be guesses dressed as a contract.
3. Retire a portal's catalog once its map has mapped reports. The map is the one place Wizard finds that portal's
   reports; catalogs of systems that are not portals, and of portals with no map yet, stay.

**Decision.** Option 3, the recommendation.
- **When.** A system's catalog is retired when the system is a portal set up on this PC (Settings → Portals) and its
  map has at least one report marked mapped or partial: this PC's map, else the one published to the knowledge base
  (`portal-maps/<portal>.json`), as `PortalMaps` already loads them. Decided once at start-up
  (`tools.retire_portal_catalogs`, called by `create_app` before the registry is built), because the tool list and
  Gemini CLI's MCP servers are fixed then too. A portal mapped while Wizard runs is retired at the next start.
- **What changes for a retired catalog.** It leaves `services.catalog`: no `<system>_*` tools in Gemini's tool list
  (and no MCP server for it), none of its reports in `wizard_search_catalog`, no entry in the Sources tab or in the
  Brain page's catalogued report count. `wizard_search_catalog` says which portals it did not search and names
  `portal_map(system=..., find=...)` for each. `wizard_list_sources` lists the portal once, as the live portal, with
  `reports_mapped`, "Read through its map" and `portal_map(...) → portal_run(...)` as the way in (any portal whose map
  has mapped reports gets that pointer; a retired one also says its catalog is retired and names its platform guide).
- **What does not change.** A portal with no mapped report yet keeps its catalog and the `live_portal` note that the
  catalog is not the portal. A system that is not a portal keeps its catalog. The repository's synthetic catalogs
  (`SYNTHETIC_FIXTURE`, readable synthetic rows) are never retired, so the demo, the fixtures, the goldens, the replay
  transcripts and the evals work as before even on a PC with a mapped portal.
- **The content validator** no longer asks for an owner review of a retired catalog's entries. For a catalog whose
  portal (asap, gscm, bdp) has a published map with mapped reports, it says once, as a warning on the file, that the
  catalog is retired and its UNCERTAIN choices need no review, instead of one "waiting for owner review" warning per
  entry. It says it rather than staying silent so the person learns why the catalog is no longer in Wizard and can
  remove the file. It sees only the published map, not a PC's own; errors in the file (invalid JSON, secrets) still
  count.
- **The system prompt's** report-catalog bullet under "Company portals" says a mapped portal has no catalog tools and
  its map is where its reports are; the `/wizard:report-catalog` command in the content template stops for a mapped
  portal.

**Consequences.**
- New: `tools.retire_portal_catalogs`, `Catalog.without`, `PortalMaps.mapped`, `Services.retired_catalogs`; the
  `portal_maps` note in `wizard_search_catalog`; `reports_mapped` and `reports` on a mapped portal in
  `wizard_list_sources`. Tool names, descriptions and schemas are unchanged in the published contracts (they are
  exported in synthetic mode).
- People stop writing catalogs for mapped portals: the content template, the documentation guide, source onboarding
  and the platforms page say so. A retired catalog file can be deleted from the knowledge base; leaving it does no harm.
- **Residual risks.** A map with one mapped report retires the whole catalog, including reports the map has only
  listed (todo): Gemini then finds those in the map's index or the portal's menu, not in a catalog entry. A PC where a
  portal is not set up still offers that portal's catalog. A retired catalog that held a report the map lacks loses it
  from Wizard until the report is mapped.

**Evidence.** `tests/unit/test_retired_catalogs.py` (5): a portal with a mapped report loses its catalog tools, MCP
scope and search results while a portal whose map has nothing mapped and a non-portal system keep theirs, and
`wizard_list_sources` points at its map; the published map counts and a switched-off portal is not mentioned; synthetic
mode and a PC without portals keep every catalog (the same tools as before, synthetic rows still read); the validator
says once that a mapped portal's catalog is retired and still asks for review where nothing is mapped or the system is
not a portal; through the API, Wizard starts without the catalog of a mapped portal (Sources tab empty, the portal
listed once with its mapped reports). `scripts/verify_spec.py` passes unchanged; `scripts/export_contracts.py` shows
no contract diff.
