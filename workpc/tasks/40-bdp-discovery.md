# Task 40 — Discover the Big Data Portal (BDP)

**Goal:** find out what Wizard needs to find BDP tables in its information catalog and query them through Superset,
BDP's SQL tool, under each person's own company sign-in. BDP is two applications: the **information catalog**, where
people search for tables and request access to them, and **Superset**, where they query them. Find out what BDP holds,
how table access is requested in the catalog, which product runs the catalog, which database engines sit behind
Superset, how both sign people in, and whether Superset's REST API answers from this PC. Nothing in this task reads
table rows.
**Output:** `content\inbox\bdp\` (the check and the pages the user saves), `outbox\40-bdp-discovery.md` (internal)
and `outbox\40-bdp-shareable.md` · **Shareable:** `outbox\40-bdp-shareable.md` only (yes/no answers, versions, engine
types and counts; no addresses, database, schema or table names, or people).
**Model:** `gemini-3.8-flash` is enough; any stronger model your plan lists is fine too.

All `.\docs.ps1` commands run in PowerShell in this folder. If your shell is cmd, use
`powershell -NoProfile -ExecutionPolicy Bypass -File docs.ps1 <command>` instead.

## Rules for this task

- You never sign in to Superset or the information catalog, run SQL or open a browser. The user does the browser
  steps, signed in as usual. Nobody requests access to a table for this task.
- Never ask for, accept or write down a password, token or cookie. If a saved file holds one (for example a line with
  `access_token`, `csrf_token` or `session=`), stop, ask the user to delete that file, and continue without it.
- Never copy table rows. Database, schema and table names are internal: they may appear in `content\` and in
  `outbox\40-bdp-discovery.md`, never in the shareable file.
- In company documents BDP may also stand for something else; record every meaning you find, with its source.

## Steps

1. **What the documents say.** Search `content\inbox\_text\` and, if tasks 20-21 ran, `content\inbox\_digests\` for:
   `BDP`, `Big Data Portal`, `Superset`, `SQL Lab`, `Trino`, `Presto`, `Hive`, `Spark`, `Impala`, `Databricks`,
   `Hadoop`, `data lake`, `access request`, `information catalog`, `data catalog`, `metadata`. Note, with source ids:
   what BDP holds, how table access is requested in the information catalog and approved, which engines are named, the
   catalog and Superset addresses, and the team that runs BDP (team name or role, not people's emails). Then ask the user whether they have a BDP guide, an access-request guide or emails about BDP; if
   so, they put them in `content\inbox\bdp\` and you run `.\docs.ps1 extract` and read them.
2. **The two addresses.** Ask the user to open SQL Lab in their browser and copy the address from the address bar,
   then to open the information catalog and copy its address too.
3. **Check from this PC.** `.\docs.ps1 bdp-check --url "<that address>"`. It sends anonymous requests only (no
   sign-in, no SQL) and writes `content\inbox\bdp\superset-check.md`. Read the lines it prints:
   - `FAIL ... could not reach`: note the reason (proxy, certificate, blocked) and continue; the browser steps still work.
   - `Superset base address`: use it as `<base>` below.
   - `sign-in:`, `Superset's sign-in setting`, `sign-in gateway`, `Windows integrated sign-in`: how Superset signs
     people in.
   - `REST API`: whether programs can reach Superset's API at all.
   Optional for the user: adding `WIZARD_BDP_URL=<base>` to `.env` saves typing `--url` next time (they edit `.env`
   themselves; you never open it).
4. **Browser steps (the user, signed in to Superset as usual).** Give the user these steps one at a time and wait:
   1. Open
      `<base>/api/v1/database/?q=(columns:!(id,database_name,backend,allow_dml,allow_run_async,expose_in_sqllab),page_size:100)`
      The page shows text starting with `{`. Save it with Ctrl+S as `superset-databases.json` in `content\inbox\bdp\`.
      If the browser offers only "Webpage", select all the text (Ctrl+A, Ctrl+C), paste it into Notepad and save it
      there under that name. If the page shows an error message instead, try `<base>/api/v1/database/` and save that.
   2. Optional: open `<base>/api/v1/me/roles/` and save it the same way as `superset-my-access.json`. It lists the
      tables the user already has access to. Skip it if it shows an error.
   3. In Superset, open the Settings menu (top right) and choose About: ask the user for the version it shows.
   4. Ask: in SQL Lab, which database do they pick for BDP tables? When they signed in to Superset, did they see the
      same sign-in page as for ASAP and GSCM?
   5. In the information catalog, ask the user (without sending a request): which product it is (its About page,
      footer or logo; e.g. DataHub, Collibra, Alation, Atlas, OpenMetadata, Amundsen, or an in-house page); whether it
      asked for a sign-in, and the same one as Superset; how they search for a table; what a table's page shows
      (description, columns, owner, partitions, whether they already have access); and what requesting access involves
      (a button, a form, who approves, how long it usually takes, and where they see their requests).
5. **Run the check again.** `.\docs.ps1 bdp-check --url "<base>"`. It now adds one line per database from the saved
   list: name, engine (`backend`: trino, presto, hive, spark, databricks, impala, ...), and whether Superset allows
   data changes (`allow_dml`), background queries (`allow_run_async`) and SQL Lab (`expose_in_sqllab`). A `WARN ... not
   the database list` line means the save did not work: repeat step 4.1. Then run `.\docs.ps1 extract`.
6. **Your access (if step 4.2 was saved).** Read `content\inbox\bdp\superset-my-access.json`. Count the grants by kind:
   `datasource_access` (one table or dataset), `schema_access` (a whole schema), `database_access` (a whole database),
   and `all_database_access` / `all_datasource_access` (everything). Do not copy the person's name or email from it.

## Write `outbox\40-bdp-discovery.md` (internal)

Sections, each with source ids or the check line it comes from:
- **What BDP is:** what it holds, how access is requested and approved, who runs it, other meanings of "BDP".
- **Information catalog:** address, product, sign-in (same as Superset or not), how a table is searched, what a
  table's page shows, and how access is requested and approved (step 4.5 and the documents).
- **Superset:** base address, version, reachable from this PC (route and any failure).
- **Sign-in:** protocol, identity provider, gateway in front of Superset, Windows integrated sign-in, same page as ASAP
  and GSCM (the user's answer).
- **REST API:** what `/api/v1/database/` answered, and the endpoints the check found listed (or "not public").
- **Databases:** a table: name, engine, DML allowed, background queries, in SQL Lab, used for BDP tables (step 4.4).
- **Your access:** the counts from step 6.
- **Open questions for the BDP team.** Always include these, plus any the documents raise:
  1. Can an application call Superset's REST API on behalf of a signed-in person, and with which credential (an access
     token from the company sign-in, Windows integrated sign-in, or Superset's own token)? Browser cookies are not
     an option.
  2. Does Superset apply each person's own table access to API calls exactly as in SQL Lab?
  3. Is "Allow DML" off for every database Wizard would use, and is there a read-only connection?
  4. What query time limit and row limit apply in SQL Lab, and are long queries run in the background?
  5. Which columns partition the large tables (usually a date) and should always be filtered?
  6. Does the information catalog have an API or search request an application may call under the person's own
     sign-in, and does it say whether a person already has access to a table?
  7. How are access requests approved, and can Wizard link a person to a table's request page in the catalog when
     they lack access?

## Write `outbox\40-bdp-shareable.md`

One table, question | answer: Superset reachable from this PC; route (direct or proxy, no address); Superset version;
sign-in protocol; identity provider product (e.g. Microsoft Entra ID, AD FS, Okta, or unknown); gateway in front of
Superset; Windows integrated sign-in offered; what the REST API answered; API lists SQL Lab execute (yes / no / not
public); same sign-in page as ASAP and GSCM; information catalog product (or unknown); catalog uses the same sign-in as
Superset; number of databases; engines with counts (e.g. trino 2, hive 1); DML
allowed (k of n); background queries (k of n); grants by kind (counts); how access is requested (one sentence without
names); number of open questions. Then the `bdp-check` lines with every host name replaced by `<superset>`,
`<gateway>` or `<identity provider>`.

**Done when:** `content\inbox\bdp\superset-check.md` exists, every database in the saved list has its engine in the
discovery file (or the file says why the list could not be saved), the sign-in route is described or marked unknown
with the reason, the information catalog's product and request route are described or marked unknown, the open questions are listed, and the shareable file has no address, database, schema, table or
person name. If the user could not do the browser steps, mark the task `partial` in `STATUS.md` and say which
answers are missing.
