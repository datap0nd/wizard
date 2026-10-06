# How Wizard handles platforms and their reports

Each data platform (ASAP, GSCM, NERP, later others) is described in three layers. Gemini reaches all of them through
tools, so nothing has to fit in its prompt and the catalog can grow to hundreds of reports.

| Layer | Where | What it holds | How Gemini reaches it |
|---|---|---|---|
| **Platform guide** | `knowledge/platforms/<platform>.md` | Plain-language orientation: what the platform is, how it is organised (folders, reports vs dossiers, prompts), what lives there, pitfalls and terminology | `wizard_list_sources` names the guide; `wizard_lookup_definitions` returns it |
| **Report catalog** | `contracts/sources/<platform>.json` | Every approved report: folder, description, grain, dimensions, measures with units and aggregation rules, prompts, caveats, freshness, owner, sensitivity, and `row_access` (ROWS or NAVIGATION_ONLY) | `<platform>_search_reports` (search), `<platform>_get_report_schema` (one report in full), `wizard_search_catalog` (all platforms) |
| **Business definitions** | `knowledge/metrics/`, `calendar.md`, `markets-and-models.md` | Cross-platform meanings (sell-through, share gain, observed switchers, fiscal quarter, market codes) | `wizard_lookup_definitions` |

## One MCP server per platform

Gemini CLI connects to one MCP server per platform (`asap`, `gscm`, `nerp`) plus `wizard` for cross-platform tools
(catalog search, definitions, calculator, visuals, Check my data). Each platform server exposes the same three tools
(`search_reports`, `get_report_schema`, `run_report`), which Gemini sees as `mcp_asap_run_report`, and so on. They are
generated from the report catalog: **adding a report means adding a catalog entry, not code**. Adding a platform means
adding a catalog file, a platform guide and a live adapter for its API; the MCP server appears automatically.

## Navigation

- **People** browse the Sources tab: platform → folder → report → prompts, limited to what they may see. Each report
  shows "Rows" or "Navigation only", with "Ask about this report" and (live) "Open in <platform>".
- **Gemini** navigates the same catalog with tools: search with business words → read the schema → run with prompt
  filters → cite the evidence id. Rights are applied inside every tool, so Gemini only ever sees permitted reports and
  markets.

## Filling the catalogs with the real reports

1. **ASAP (~50 candidates):** `scripts/import_asap_catalog.py` walks ASAP folders through Library REST and drafts
   catalog entries from ASAP's own metadata (names, attributes, metrics, prompts). It reads metadata only, no rows. The
   draft goes to `artifacts/catalog-drafts/` and is never loaded until reviewed.
2. **GSCM (~100 candidates), NERP and others:** start from whatever inventory IT VOC or the owners provide (an export of
   report names and descriptions, the Mosaic Q&As). Record one row per report in `docs/source-register.csv`.
3. **Owner review per report:** a business description, grain, units, aggregation rules (sum / period-end balance / rate),
   caveats, freshness and sensitivity. Then merge it into `contracts/sources/<platform>.json`
   ([source-onboarding.md](source-onboarding.md)).
4. **Platform knowledge:** put the platform's own documentation (e.g. Mosaic connectivity Q&As, GSCM help) into
   `knowledge/platforms/<platform>.md` as a short guide. Larger documents can be split into several notes with tags so
   `wizard_lookup_definitions` finds the relevant part.

Reports stay `NAVIGATION_ONLY` until a read path is approved and parity-tested. Gemini can still find them, tell the
user they exist and suggest opening them, but cannot read their numbers.

PostgreSQL is different: it has no report entries. Gemini reads the dataset notes and queries the server directly
with `wizard_query_postgresql`
([documentation-guide.md](documentation-guide.md#postgresql-documentation-then-geminis-own-sql)).
