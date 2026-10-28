# The Big Data Portal (BDP): the information catalog and Superset

BDP is two applications, each at its own address (`applications` above), both under the person's own sign-in
(decision 2026-10-12):

- **The information catalog**: where people search for tables (what a table holds, its columns, who owns it) and
  request access to them.
- **Superset** (Apache Superset, SQL Lab): where they query the tables they have access to.

So a BDP question usually goes: find the table in the information catalog, then query it in Superset. Open each
application by its full address; a `/path` then stays on the application the page is on.

## The information catalog

- Which product runs it is not recorded yet (work-PC task 40). Explore it the general way: `goto` its address,
  `look`, search for a business word, and read the result's `requests` for the search request the page sent; then send
  that request yourself (`W.replay` with `replace`, or `fetch`) with other words. Keep a search that works with
  `portal_save_script`.
- Read what helps the question: table names, descriptions, columns, owners, partitions, refresh, and whether this person
  already has access. Return a table (`{columns, rows}`) to cite it.
- **Access requests: you prepare, the person submits.** Your own steps never request access: Wizard refuses Request
  buttons, addresses that start with request, POSTs to an access-request address and GraphQL mutations. When the answer
  needs a table the person cannot query, call `portal_request_access` with the table's page (or the request page) as
  `address`, the `tables`, and this request's own `answers` by the form's labels (`access_request_form` above lists
  the labels seen on the form before), such as the reason in the person's words. The person then sees a button that
  opens the page in Wizard's visible browser window, with their saved answers (purpose, manager, duration...) and yours
  filled into the form's empty fields; they press Request access there if the form is behind it, check every field and
  submit. Name the table in your answer and say the data waits until access is granted. Portal reads wait while that
  window is open, so call it last.

## Superset: queries

- `await W.superset.databases()` lists the databases this person can use: `{id, name, backend, allow_dml}`.
- `await W.superset.schemas(databaseId)` lists schemas.
- `await W.superset.sql(databaseId, "SELECT ...", {schema, limit})` runs one SELECT through SQL Lab
  (`POST /api/v1/sqllab/execute/` with the page's CSRF token) and returns `{columns, rows, total_rows}`: return it to
  record it as evidence. Wizard refuses anything but one SELECT (or WITH ... SELECT).
- The `W.superset` helpers work on a Superset page: `goto` Superset's address first when the page is on the catalog.
- Big tables are usually partitioned by date: always filter on the partition column (often `dt`, `ds`, `date` or
  `p_date`; the information catalog may name it) and aggregate in SQL. Ask for few columns; set `limit`.
- A database's engine decides the SQL dialect (`backend`: hive, presto/trino, spark, impala, postgresql...).
- Charts and datasets: `GET /api/v1/chart/?q=...`, `GET /api/v1/dataset/?q=...`, and `POST /api/v1/chart/data` (the
  payload a chart sends, visible in `requests` after opening it) read existing work without writing SQL.

## When it fails

- `401`/`403` or a sign-in page: the person is not signed in to that application, or has no access to that table. Say
  so; access is requested in the information catalog, not in Wizard.
- A query that runs asynchronously returns a query id instead of rows: poll `GET /api/v1/query/?q=...` sparingly, or
  ask a smaller question.
- Superset's error text explains SQL mistakes: read it and fix the query.
