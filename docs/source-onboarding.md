# Source onboarding template (Step 14)

Use one copy of this checklist per report or report batch. A report enters the catalog only when every box applies.

1. **Permission** — named source owner approves read access for Wizard and the user population; request recorded.
2. **Metadata indexed** — row added to `docs/source-register.csv` (metadata only, no rows): owner, report id, description,
   access method, dimensions, measures, units, grain, history, refresh, prompts, export/API rights, sensitivity.
3. **Contract** — report added to `contracts/sources/<system>.json` with typed columns, aggregation rules, prompts,
   caveats and `row_access`. Validates against `contracts/source-contract.schema.json`.
4. **Canonical dimensions mapped** — market, period and model keys mapped to Wizard terminology (`knowledge/`), with any
   mismatch documented rather than silently joined.
5. **Entitlement** — report and market rights mapped to the source's own entitlement model; tests prove a non-entitled
   user cannot search, inspect, run or reopen it.
6. **Read capability** (if approved) — allowlisted adapter path, bounded rows/time, retries with idempotence, 401/403
   mapping, schema-change detection, freshness timestamp.
7. **Parity** — same-user, same-filter comparison with the owner's original; signed; reference stored privately.
8. **Certified status** — connector status set (`NAVIGATION_ONLY`, `ROWS_UNVERIFIED` for an approved live adapter
   before parity, or `ROWS_VERIFIED`; for PostgreSQL, each report's `parity` sign-off), maintenance owner named,
   change/deprecation notice route agreed, metadata refresh schedule set.
9. **Tests** — contract test updated (`scripts/export_contracts.py`), versioned parity test, evaluation cases added.

No core report code changes should be needed: the registry generates `<system>_search_reports / _get_report_schema /
_run_report` from the contract.
