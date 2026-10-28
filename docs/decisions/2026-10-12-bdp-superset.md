# 2026-10-12 — The Big Data Portal: per-user access through Superset, discovery first

**Owner:** project owner. **Status:** decided for discovery (12 October 2026); the query tool waits for its results.
Amended 28 October 2026: [BDP is its information catalog and Superset](2026-10-28-bdp-information-catalog.md).

**Context.** The owner wants Wizard to use a fourth platform, the Big Data Portal (BDP). BDP is not a report platform
like ASAP or GSCM. People request access to individual tables, and query them with SQL in Superset (SQL Lab), BDP's
query tool. So BDP follows the PostgreSQL route (dataset notes, then Gemini's own SQL), not the report-catalog route.
Nobody on the project yet knows which database engines sit behind Superset, how Superset's API signs people in, or
whether the API can be reached from a work PC.

**Options for whose access Wizard uses.**
1. Each person's own BDP access, through the company sign-in they already use for Superset (the same SSO as ASAP and
   GSCM). Superset then allows exactly the tables that person requested.
2. One Wizard account with its own table grants. Simpler, but everyone given BDP rights in Wizard would see every
   table that account can read, whatever they requested themselves.

**Decision.**
- **Option 1.** BDP is queried through Superset under each person's own sign-in. No shared account, and never copied
  browser cookies (AGENTS.md). A person without their own BDP sign-in gets a clear "link your account" state, never
  someone else's access.
- **Discovery first.** Work-PC task 40 and `.\docs.ps1 bdp-check` find out what such a connection needs: the engines
  behind Superset, how Superset signs people in (identity provider, protocol, a gateway in front of it, Windows
  integrated sign-in), and whether its REST API answers from the PC. `bdp-check` sends anonymous GET requests only;
  the engine list comes from one page the user saves from their own signed-in browser.
- **Not decided yet.** The query tool itself (`wizard_query_bdp` running Gemini's SELECT through Superset's SQL Lab API)
  would be a second exception to AGENTS.md's no-SQL rule. It is decided, with its protections, once task 40 has
  answered: Superset's per-user API sign-in, "Allow DML" off, query time and row limits, partition filters. Until
  then AGENTS.md is unchanged and Wizard has no BDP tool.

**Consequences.**
- New: `services/documents/wizard_documents/bdp.py`, the `bdp-check` kit command, task 40 (its own track in
  `START_HERE.md`).
- Redirect addresses are kept as host, path and parameter names only; parameter values (state, nonce, client ids) are
  never written. Redirects that leave Superset's host are recorded, not followed.
- The shareable result (`outbox\40-bdp-shareable.md`) holds no addresses, database, schema or table names, or people.

**Evidence.** `tests/unit/test_bdp_check.py` runs `bdp-check` against simulated Superset servers:
- OAuth through Microsoft Entra ID, read from redirects, without requesting the identity provider;
- a SAML gateway in front of every page;
- a password login page with Windows integrated sign-in;
- the API description and the version endpoint;
- an unreachable host;
- the saved database list;
- the CLI.
The tests also check that only anonymous GETs to Superset's own host are sent, and that no parameter value is
written. The field names it reads (`AUTH_TYPE`, `AUTH_PROVIDERS`, `version_string`, the `/health` and `/version`
routes, the `backend` column) were checked against Superset's and Flask-AppBuilder's source.
