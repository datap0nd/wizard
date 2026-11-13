# The Big Data Portal (BDP): the information catalog and Superset

BDP is two applications, each at its own address (`applications` above), both under the person's own sign-in
(decision 2026-10-12):

- **The information catalog** (DIS): where people search for tables and datasets (what one holds, its columns, who
  owns it) and request access to them.
- **Superset** (Apache Superset, SQL Lab): where they query the tables they have access to.

So a BDP question usually goes: find the table in the information catalog, then query it in Superset. Open each
application by its full address; a `/path` then stays on the application the page is on.

## The information catalog

- Explore it the general way: `goto` its address, `look`, search for a business word, and read the result's
  `requests` for the search request the page sent; then send that request yourself (`W.replay` with `replace`, or
  `fetch`) with other words. Keep a search that works with `portal_save_script`. The map's topic `catalog-search`
  says how the search works once a task has proved it, and `catalog-relevant-datasets` ranks the datasets that matter
  most, with each one's catalog page and whether this person has access: read them first (`portal_map` with `topic`).
- Read what helps the question: table names, descriptions, columns, owners, partitions, refresh, and whether this person
  already has access. Return a table (`{columns, rows}`) to cite it.
- **Access: you name the tables, the person requests them.** Wizard does not request access (owner, 13 November
  2026), and your own steps never do: Wizard refuses Request buttons, addresses that start with request, POSTs to an
  access-request address and GraphQL mutations. When the answer needs a table the person cannot query, say so plainly:
  list the tables they need, each as the catalog names it, with its catalog page address when you have one (open the
  table with `portal_run` and use the page's url) and what the analysis needs it for, and tell them to request access to
  them themselves in the information catalog. Say the data waits until access is granted. Never claim that access was
  requested.

## Superset: queries

- `await W.superset.databases()` lists the databases this person can use: `{id, name, backend, allow_dml,
  allow_run_async}`.
- `await W.superset.schemas(databaseId)` lists schemas.
- `await W.superset.sql(databaseId, "SELECT ...", {schema, limit})` runs one SELECT through SQL Lab and returns
  `{columns, rows, total_rows}`: return it to record it as evidence. It works on every Superset version: it sends the
  query to `POST /api/v1/sqllab/execute/` or, where Superset does not serve that (versions before 2.1), to
  `POST /superset/sql_json/`, with the page's CSRF token, and remembers which one answered. A database that runs
  queries in the background (`allow_run_async`) is followed until the query ends and its rows are read from Superset's
  results; `{runAsync: false}` runs it in the foreground instead. Write your own `fetch` to SQL Lab only to read
  something `W.superset.sql` does not return.
- Wizard refuses anything but one SELECT (or WITH ... SELECT) before it is sent, and again in the browser.
- Start cheap: `SELECT 1` on a database proves the route and your access; then read a table with a small `limit` (10 to
  100) and few columns before asking for more.
- Big tables are usually partitioned by date: always filter on the partition column (often `dt`, `ds`, `date` or
  `p_date`; the information catalog may name it) and aggregate in SQL. Ask for few columns; set `limit` (default 1000,
  at most 50000). `total_rows` larger than the rows you got, or `limit_reached`, means the limit cut the result.
- A query gets the rest of its step's time (30 s unless you give the step `timeout_ms`, up to 150000): give a step that
  queries a large table `timeout_ms: 120000`.
- The `W.superset` helpers work on a Superset page: `goto` Superset's address first when the page is on the catalog.
- A database's engine decides the SQL dialect (`backend`: bigquery, hive, presto/trino, spark, impala, postgresql...).
  In BigQuery, quote a full table name with backticks: `` `project.dataset.table` ``.
- Charts and datasets: `GET /api/v1/chart/?q=...`, `GET /api/v1/dataset/?q=...`, and `POST /api/v1/chart/data` (the
  payload a chart sends, visible in `requests` after opening it) read existing work without writing SQL.

## When it fails

A failed query stops its step with `SQL Lab: <method> <path> answered <status> <Superset's error type> (issue <code>):
<Superset's message>`, then what to do:

- **Not signed in** (401, or a sign-in page): the person signs in again in Settings → Portals.
- **No permission** (403, or a `..._SECURITY_ACCESS_ERROR`): the person has no access to that database or table. Say
  so; access is requested in the information catalog, not in Wizard.
- **Not served at either address** (404 at both): Superset's address in Settings → Portals is wrong, or SQL Lab is off.
- **A SQL error** (`GENERIC_DB_ENGINE_ERROR`, `SYNTAX_ERROR`, `COLUMN_DOES_NOT_EXIST_ERROR`...): read Superset's
  message, fix the query and run it again yourself; Wizard never retries it.
- **Took too long**: filter on the partition column, aggregate, ask for fewer rows, or give the step more `timeout_ms`.
- An expired CSRF token is refreshed and the query sent once more by the helper itself.
