# The Big Data Portal (BDP): Apache Superset

People request access to individual tables and query them in Superset's SQL Lab; Wizard reads BDP the same way,
under the person's own sign-in (decision 2026-10-12). Superset's REST API answers inside the signed-in page.

## Queries

- `await W.superset.databases()` lists the databases this person can use: `{id, name, backend, allow_dml}`.
- `await W.superset.schemas(databaseId)` lists schemas.
- `await W.superset.sql(databaseId, "SELECT ...", {schema, limit})` runs one SELECT through SQL Lab
  (`POST /api/v1/sqllab/execute/` with the page's CSRF token) and returns `{columns, rows, total_rows}`: return it to
  record it as evidence. Wizard refuses anything but one SELECT (or WITH ... SELECT).
- Big tables are usually partitioned by date: always filter on the partition column (often `dt`, `ds`, `date` or
  `p_date`) and aggregate in SQL. Ask for few columns; set `limit`.
- A database's engine decides the SQL dialect (`backend`: hive, presto/trino, spark, impala, postgresql...).
- Charts and datasets: `GET /api/v1/chart/?q=...`, `GET /api/v1/dataset/?q=...`, and `POST /api/v1/chart/data` (the
  payload a chart sends, visible in `requests` after opening it) read existing work without writing SQL.

## When it fails

- `401`/`403` or a sign-in page: the person is not signed in to BDP, or has no access to that table. Say so; access is
  requested in BDP, not in Wizard.
- A query that runs asynchronously returns a query id instead of rows: poll `GET /api/v1/query/?q=...` sparingly, or
  ask a smaller question.
- Superset's error text explains SQL mistakes: read it and fix the query.
