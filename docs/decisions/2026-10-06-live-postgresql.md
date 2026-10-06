# 2026-10-06 — Live numbers from PostgreSQL, and totals over attached spreadsheets

**Owner:** project owner. **Status:** decided (6 October 2026).

**Context.** Task 18 documented every materialized view, and the owner also documented GSCM. Asked whether Wizard could
give a GSCM or SIBP number, Gemini CLI answered that it could not: every real report was navigation-only, and attached
spreadsheets reached Gemini only as a profile and a sample. The SIBP and sell-in data the executives ask about is in
PostgreSQL views (`bi_reporting.sell_in_amt_mv`, `bi_reporting.psi_combined`), which Wizard can already read through
a read-only account.

**Options.**
1. Keep the views navigation-only until each one is parity-checked, and only then read rows.
2. Read the documented views live straight away, labelled as unchecked, and sign a parity check per view to make them
   verified.
3. Give Gemini a SQL tool.

**Decision.** Option 2.
- **Live, labelled.** Rows read from a catalogued PostgreSQL view have data mode `LIVE_UNVERIFIED`, shown as
  "Live · not yet checked". The system's connector status is `ROWS_UNVERIFIED`.
- **Verified per view, by a person.** Once the owner has compared one query (`.\docs.ps1 postgres-sample`) with a
  figure they trust, that report entry gets `parity` (date, who, which reference). From then on its rows are
  `LIVE_VERIFIED`. Nothing else upgrades a view.
- **No SQL from the model.** Option 3 is rejected (AGENTS.md: no arbitrary SQL). `<system>_run_report` takes the same
  filters, groupings and measures as before. Wizard builds the SQL from the entry's columns and aggregation rules,
  with quoted identifiers and bound values, LIMIT 500 and market rights in the WHERE clause. It runs in a read-only
  session with statement and lock timeouts, under the read-only account.
- **Aggregation rules are enforced in SQL:**
  - `sum` adds the values.
  - `sum_same_currency` returns a total only within one currency.
  - `last` takes the latest period in each group.
  - `none` returns a value only for a single row.
- **SIBP and sell-in first.** Task 19 drafts entries for the chosen views (`.\docs.ps1 postgres-contract`). Gemini CLI
  reviews them with the owner, then runs the parity checks.
- **Attached spreadsheets get the same treatment in this release.** Each sheet or CSV is kept as a full typed table
  (up to 300,000 rows). `wizard_query_attachment` filters, groups and totals every row. Evidence stays `USER_PROVIDED`.

**Consequences.**
- New data mode `LIVE_UNVERIFIED`, ranked between USER_PROVIDED and DATED_APPROVED_SNAPSHOT.
- New connector status `ROWS_UNVERIFIED`.
- Report entries gain `relation`, `parity`, and `column` on fields. The validator accepts row reports only for
  approved live adapters (PostgreSQL).
- Wizard declares 19 tools.
- Wizard's server needs `WIZARD_PG_*` (or the `PG*` variables) when the catalog has PostgreSQL reports. `run.py --check`
  reports whether the session is reachable and read-only.

**Evidence.**
- Unit tests check the generated SQL (quoted, bound, rights), every validator rule, the draft and sample commands, the
  attachment query engine and the evidence each one records.
- `tests/integration/test_postgres_source_real.py` compares every aggregation rule with independently computed values
  on a real PostgreSQL 16 in CI.
- The corporate views are first read on the work PC, in task 19.
