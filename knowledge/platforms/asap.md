---
id: platform-asap
title: ASAP platform guide (MicroStrategy BI)
status: DRAFT_UNSIGNED
owner: TBD - ASAP IT / report owners (Step 03, Step 09)
tags: [asap, platform, microstrategy, strategy, bi, dossier, report, prompts, folders, navigation, share, smart switch, installed base]
---
**What it is.** ASAP is the MicroStrategy (Strategy) BI portal. Content is organised in folders (Shared Reports →
Market Intelligence, Consumer & Ecosystem, Finance, Executive Dossiers). Two kinds of objects matter:

- **Reports**: a grid with attributes (dimensions such as market, month, brand) and metrics (measures). Most have
  **prompts**: answers chosen before running (e.g. quarter, market). In Wizard, prompts are the `filters` of
  `asap_run_report`.
- **Dossiers**: dashboards with chapters, pages and several visualizations. Wizard cannot read a whole dossier; one
  specific visualization has to be approved first. Until then a dossier is **navigation only**.

**How to navigate.** Use `asap_search_reports` with business words (e.g. "smart switch origin", "market share brand"),
then `asap_get_report_schema` to see the grain, dimensions, measures, aggregation rules, prompts and caveats, then
`asap_run_report`. `row_access: NAVIGATION_ONLY` means the report can be listed and opened in ASAP by the user, but
Wizard cannot read its numbers: say so and suggest the user opens it.

**What lives here (synthetic Release A).** Market share by brand (retail panel, ~4-week lag), Smart Switch transfers by
origin brand and target family, Smart Switch observation coverage, installed base and activations, app engagement,
gross margin (restricted to finance leadership), an executive dossier and a retail coverage report (navigation only).

**Pitfalls.** Shares and rates must not be summed. Installed base is a month-end balance. Smart Switch counts are
observed events only (see "observed switchers"). Panel share and company sell-out use different denominators. The real
ASAP catalog (~50 candidate reports) is still to be inventoried; report names and prompts will differ.
