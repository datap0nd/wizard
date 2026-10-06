# 2026-10-06 — Gemini queries PostgreSQL with its own SQL; totals over attached spreadsheets

**Owner:** project owner. **Status:** decided (6 October 2026). It replaces a first design built and withdrawn the
same day (below).

**Context.** Task 18 documented every materialized view, and the owner also documented GSCM. Asked whether Wizard could
give a GSCM or SIBP number, Gemini CLI said it could not: every real report was navigation-only, and attached
spreadsheets reached Gemini only as a profile and a sample. The SIBP and sell-in data executives ask about is in
PostgreSQL views (for example `bi_reporting.sell_in_amt_mv` and `bi_reporting.psi_combined`), readable with a
read-only account. The owner had already run complex analyses on this data with Gemini 3.8 Flash and found it
excellent.

**Options.**
1. Report entries per view, with Wizard-built SQL and per-column aggregation rules. Each view is reviewed (task 19),
   and its figures are labelled "not yet checked" until the owner signs a comparison with a trusted number.
2. A generic query tool: any view, filters, groups and aggregates chosen by Gemini, but no SQL, joins or window
   functions.
3. A read-only SQL tool: Gemini writes its own SELECT.

**Decision.** Option 3, over whatever the read-only account can read.
- **Why not option 1.** It was built and pushed (`e201ff5`, `82b8bac`). The owner then withdrew it: it constrained
  Gemini (aggregation rules, a review step, sign-offs) before any failure had been seen. AGENTS.md already says a rule
  needs a measured failure first. The approach is documentation plus capable tools, and a constraint only after Gemini
  fails without it.
- **The tool.** `wizard_query_postgresql(sql, database?, max_rows?)` reads whatever the account's grants allow. The
  dataset notes from task 18 are its documentation; Gemini can also read `information_schema` and `pg_catalog`.
- **What protects the server (unchanged by what Gemini writes):**
  - a read-only account (`WIZARD_PG_*`, else the `PG*` variables);
  - a fresh connection per call, closed afterwards;
  - one statement through PostgreSQL's extended protocol, which refuses a second one;
  - the query wrapped as a subquery, so it can only be a query;
  - a READ ONLY transaction, always rolled back;
  - 60 s statement and 2 s lock timeouts;
  - at most 500 rows returned to Gemini.
- **Labels.** Data mode `LIVE` ("Live"), connector status `READ_ONLY_SQL`. There is no "verified" step. The evidence
  keeps the SQL, the database, the rows and a digest, so the user sees how each number was produced, and Check my data
  can run the same SQL again.
- **Rights.** A free query cannot be limited to some markets, so it needs the `postgresql` right for every market. The
  local Owner has it whenever a connection is configured. Other users get it only if their identity grants it.
- **Attached spreadsheets.** Each sheet or CSV is kept as a full typed table (up to 300,000 rows), and
  `wizard_query_attachment` filters, groups and totals every row. Evidence stays `USER_PROVIDED`. This part of the
  first design is unchanged.

**Consequences.**
- AGENTS.md allows this one SQL tool and lists `LIVE` and `READ_ONLY_SQL`.
- Report entries never point at PostgreSQL. `relation`, `parity`, `ROWS_UNVERIFIED`, `LIVE_UNVERIFIED`, task 19 and
  the `postgres-contract` and `postgres-sample` commands are gone.
- Wizard declares 20 tools.
- `run.py --check` reports whether the account connects with a read-only session, or that no connection is set.
- **Residual risk.** Inside a read-only transaction, a query can still call functions that act outside the data, such
  as cancelling another session of the same account. Give Wizard a dedicated read-only role (`WIZARD_PG_*`) rather than
  sharing data_governance's scanner account, and keep its grants to SELECT.

**Evidence.**
- Unit tests check:
  - the SQL is sent as written, inside START TRANSACTION READ ONLY and ROLLBACK, with the connection closed;
  - row caps, duplicate column names, value types and error hints;
  - rights, the evidence recorded, and the Check my data re-run;
  - the local Owner's access.
- `tests/integration/test_postgres_query_real.py` runs on CI's PostgreSQL 16, under an account that is allowed to
  write.
  - Real analysis works: a CTE, a join, `lag()` and window shares.
  - Every write attempt fails and leaves the data unchanged:
    - a DELETE;
    - a data-modifying CTE;
    - chained statements, including `COMMIT; SET SESSION ... READ WRITE`;
    - `SELECT ... FOR UPDATE`;
    - `CREATE TABLE`.
  - A setting a query changes does not outlive it.
