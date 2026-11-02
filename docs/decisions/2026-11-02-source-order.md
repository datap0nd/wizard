# 2026-11-02 — The company's source order, a test for "enough", and the schemas Wizard may query

**Owner:** project owner. **Status:** decided (2 November 2026). Amends
[2026-10-02 Agent-first design](2026-10-02-agent-first.md) on one point: the company's order of sources is guidance in
the prompt, with a sufficiency test, never code that forces a tool sequence.

**Context.** Wizard now reads the team's HTML dashboards, the AI Team Database, ASAP, GSCM, the Big Data Portal and
catalog systems such as NERP. Gemini had one fixed hint ("read a dashboard first when one covers the question") and no
way to tell when the first source is enough. The owner:

- "dashboards first (html dashboards). Then AI team DB. Then ASAP/GSCM. Then BDP, etc. I would love to be able to
  reorganize this in settings to be honest (because there's a few more portals we will map in the future too)."
- "Also NERP needs to be there, it would be perfect if I could be flexible in this setting in settings somehow."
- "What I want is for us to help gemini understand when its enough or its not enough on a good basis. For example: I
  ask for a study on demographics of attach rate care+. The care+ dashboard has age of customers (example only). But in
  asap, the care+ data has a lot more customer segmentation info."

The owner also wrote a "three-tier hierarchy" as a knowledge note: the dashboards always first, answering with no SQL
when they cover the period, market and metric; then the database when the dashboards lack the topic or the detail
(weekly or daily, say); then the Big Data Portal when the database lacks the topic or is not refreshed, saying
outright that it is stale. A note reaches Gemini only when a search returns it, so a rule meant for every question
does not belong in a note. The same note held an access rule: only one schema of the database is allowed, another is
forbidden. Advice in a note does not stop a query.

**Options.** For the order: (1) leave it in the knowledge base; (2) code that calls the sources in a fixed sequence;
(3) a company setting that builds a short block of the prompt, with a test Gemini applies to decide whether a source is
enough. For the access rule: (a) advice in the prompt; (b) a list of allowed schemas enforced inside
`wizard_query_postgresql`, from the plan PostgreSQL makes of the statement.

**Decision.** Option 3 and option (b).

- **Settings → Source order** (`WIZARD_SOURCE_ORDER`), one order for the whole company, carried by the provisioning
  file and **Export settings…** like every company setting. It lists the data sources this PC has (from
  `systems.available()`): Dashboards, the database by the name people see (`WIZARD_PG_NAME`, e.g. "AI Team Database"),
  each portal (ASAP, GSCM, the Big Data Portal, and any portal configured later) and the catalog systems (e.g. NERP);
  not the knowledge base, attached files or Metronome. The person moves a source up or down (buttons, keyboard
  accessible; a source that shares a level leaves it for a level of its own, one alone on its level passes the whole
  level next to it), puts it on the same level as the one above (and takes it off again), writes a "use it for" line
  (plain text, at most 200 characters) and marks it "only when asked". With nothing saved the order is the owner's:
  Dashboards; the database; ASAP and GSCM on one level; NERP; the Big Data Portal; then any other source. A source the
  order does not name (a portal set up later) comes last, on a level of its own; a named source this PC does not have
  is left out of the prompt and kept in the setting (Settings shows it as "not on this PC" and can remove it).
- **Stored** as compact JSON on one line, first source first:
  `[{"id":"dashboards","use":"…"},{"id":"postgresql"},{"id":"asap"},{"id":"gscm","same":true},{"id":"nerp","when_asked":true},{"id":"bdp"}]`
  (`same`: on the level of the source above; `use`: what it is for; `when_asked`: only when asked). It is validated
  when Settings saves it and when Wizard starts (`source_order.py`): ids, no duplicates, no unknown fields, booleans,
  at most 40 sources, the 200-character plain-text line (no `<`, `>` or control characters); the line may be up to
  12,000 characters. An invalid value stops loading with a message naming `WIZARD_SOURCE_ORDER`, so Settings rolls the
  change back.
- **Where to start.** Every question run gets a `<where_to_start>` block built from the setting, limited to the sources
  that run may use: the levels in order with their names and "use it for" lines, then the rule: start with the first
  source in this order that holds what is asked; it is enough when it covers the measure, every breakdown asked for,
  the period, the markets and the granularity; a study or analysis needs every breakdown the sources hold for the
  measure, not only the first source's; go further down only for what it lacks, or when its as-of is too old for the
  question, and say in the answer why ("the dashboard is monthly", "ASAP has the segmentation"); before using a later
  source because an earlier one is stale, say so outright; sources on one level are chosen by coverage; when Gemini
  stops early, it says in one line what the other sources also hold. The block is left out when the run may use one
  source or none, and from Check my data, Make recurring, mapping and task runs. The system prompt's "Prepared
  dashboards" section became "Where to start" (the dashboards' as-of and disagreement guidance kept), and the portal
  map's "Look in it first" now reads "within a portal, look in its map before its menu", so the prompt has one account
  of where to start. What each source covers is still learned from the knowledge notes: a metric's "Where to get it",
  the dashboard notes and a mapped report's `use_for`; the knowledge standard's section 11 now asks each block there to
  say the source's breakdowns, granularity, markets, periods and freshness.
- **Only when asked.** On Auto, a source marked "only when asked" is not offered: the run is a choice of every other
  system, marked `auto` (`SystemChoice.auto`), stored and shown as Auto. Its tools are not in Gemini's list and refuse
  (`system_off`, "used only when the person asks for it"), the request's `<systems>` block names it, and
  `wizard_ask_for_system` is offered, as it is when the person switched a system off. The button under the answer
  switches it on: the picker becomes an explicit choice of what Auto used plus that source. The systems list
  (`only_when_asked`) and the picker ("Wizard picks from all but NERP (only when asked)") say so. When the person picks
  systems themselves, those are used, an "only when asked" source among them included, and the order still guides
  among them. Check my data and Make recurring after an Auto answer stay on Auto the same way.
- **Schemas Wizard may query** (`WIZARD_PG_SCHEMAS`, Settings → Company database, carried by provisioning and export):
  comma-separated schema names (a plain name as PostgreSQL folds it, to lower case; a double-quoted one as written);
  empty is no limit, as before. When it is set, `wizard_query_postgresql` (and the test runs of a recurring brief and
  Check my data's replays, which use the same function) first runs `EXPLAIN (VERBOSE, FORMAT JSON)` of the statement in
  the same read-only transaction, collects the schema of every relation the plan reads (every `Schema` key: scans of
  tables, materialized views and foreign tables, in CTEs, subqueries, joins and init plans, and functions scanned in
  `FROM`) and refuses (`schema_not_allowed`) a statement that reads any schema outside the list, naming the relation,
  its schema and the allowed ones. `pg_catalog` and `information_schema` (metadata) are always allowed. The query itself
  is not sent. Every earlier protection stays: one statement as a subquery, READ ONLY, always rolled back, a fresh
  connection closed after the call, the read-only account. A missing relation's hints no longer name relations in
  other schemas.

**Consequences.** The order is guidance: Gemini may still go to a later source first when the earlier ones plainly do
not hold the measure, and says why; no code calls the sources in sequence (AGENTS.md's "Do not" line now says so).
The plan shows the tables a view reads, not the view: a view counts by its tables. A view in an allowed schema over a
forbidden schema's tables is refused, and one in a forbidden schema that reads only allowed tables runs, so the list
names the schemas where the data the company allows actually sits. The bodies of functions are not inspected; the
read-only account's own grants stay the backstop. The Brain page's news reads go through the same function, so a news
table outside the list is refused too. EXPLAIN adds one planning round trip per query when the list is set.

**Evidence.** `tests/unit/test_source_order.py` (the default, reordering, levels, lines, only when asked, unknown and
missing sources, validation, the prompt block and its limits, Auto with an only-when-asked source through the API: not
offered, refused, asked for, switched on; Check my data and switching back to Auto; Settings, provisioning and export),
`tests/unit/test_postgres_query.py` (allowed, refused through a CTE, subquery and join in a faked plan, metadata
schemas, no list = no EXPLAIN, an unreadable plan, hints, the setting's names, the tool's refusal),
`tests/integration/test_postgres_query_real.py::test_only_the_schemas_wizard_may_query_are_read` (CI's PostgreSQL
service; BLOCKED locally like the others), and the web tests (`sourceOrder`, `SourceOrder`, `Steering`).
