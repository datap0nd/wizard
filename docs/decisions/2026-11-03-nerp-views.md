# 2026-11-03 — NERP is its views, read live on their own server

**Owner:** project owner. **Status:** decided (3 November 2026).

**Context.** NERP was a synthetic report catalog (`contracts/sources/nerp.synthetic.json`): demo reports, never live
data. The owner: "add a little NERP section. NERP is just a few sql views or tables. I should be able to restrict it to
a certain DB, with a certain URL, certain Schema. It only will have access to views." And: "we need proper mapping. It's
a huge table." Asked in the session, the owner chose PostgreSQL and one read-only account carried by the company file,
like the AI Team Database's.

**Options.** (1) Put NERP's schema in the AI Team Database's settings: one server only, and NERP is on another. (2) A
second PostgreSQL source with its own server, database, schema and account, checked by the plan as the AI Team
Database is: a view's plan shows the tables under it, which may sit in other schemas, so a plan check would refuse
NERP's own views or, loosened, allow its tables. (3) A second source whose statement is parsed and may name only that
schema's views, with the account's grants behind it.

**Decision.** Option 3.
- **Settings → NERP**: the name people see, the server (a host, host:port or a `postgresql://` address whose port,
  database and user fill what is not set; a password in it is refused), port, database, schema, read-only user,
  password (DPAPI on the PC, like every secret), SSL. Carried by the company file and Export settings. Incomplete
  settings leave NERP off and say why; Wizard still starts. **Test connection** says how many views the account can
  read in that schema and warns when it can also read tables there.
- **Tools** (`nerp_*`, system `nerp`): `nerp_list_views` (the schema's views and materialized views the account can
  read, each with the dataset note that maps it, and the ones no note maps yet), `nerp_view_columns`, and `nerp_query`:
  one SELECT, as the AI Team Database's query runs it (its own connection, a READ ONLY transaction always rolled back,
  statement and lock timeouts, at most 500 rows), in the configured database only. Before it runs, the statement is
  parsed (sqlglot, pure Python) and every relation it reads, in every CTE, subquery and join, must be one of those
  views; a table, another schema's view, the catalog, another database, a function of another schema, or a function
  that runs SQL text or reaches outside the database (query_to_xml, dblink, pg_read_file...) is refused. The
  search_path is that schema, so an unqualified name is NERP's view. Evidence is `LIVE` / `READ_ONLY_SQL`; Check my
  data runs it again.
- **NERP takes over its catalog.** Connected, NERP is a live database on the stage, in the systems picker and in the
  source order; the synthetic (or knowledge-base) NERP catalog and its `nerp_*_report` tools leave.
- **Mapping** is the task "Map NERP's views" (`tasks/nerp-map-views.md`, repeats until done): one dataset note per
  view, to the knowledge standard's section 10, with what a row is, every column, its value lists, its date range, the
  filter every query needs (rows per day, how long a query without it takes) and example queries proved with
  `LIMIT 0`. The tools point at each view's note.

**Consequences.**
- A second exception to "no arbitrary SQL tools" (AGENTS.md), with its own check.
- One more dependency, `sqlglot` (pure Python, MIT): the portable runtime's locks name it.
- The account's grants remain the first protection: the owner's account reads views only.

**Evidence.** `tests/unit/test_nerp.py` (settings and addresses, every refusal of the views-only check, the query's
statements in order, the tools and their evidence, the catalog taken over, the stage and the tools offered, Settings);
`tests/integration/test_nerp_real.py` on a real PostgreSQL 16 (a view over another schema's table is read; the table,
another schema's view of the same name, the catalog, query_to_xml and writes are refused, under an account allowed to
write).
