# 2026-10-23 — Gemini reads the company portals in the person's own Wizard browser

**Owner:** project owner. **Status:** decided (23 October 2026).

**Context.** The owner asked how to be sure Wizard really reads the web portals (ASAP, GSCM, the Big Data Portal) it
says it reads, because "I think it's not actually going in and exploring tables". It was not: every ASAP, GSCM and NERP
report tool read synthetic fixture files or, with the real knowledge base, refused with `navigation_only`; BDP had no
tool at all; and the systems stage said "Reading ASAP" for a search of Wizard's own report catalog. The only live data
came from the AI Team Database. The owner then decided: "I want wizard to spawn its own little browser (use google
chrome in user machine) spin up playwright and explore the reports if needed ... querying data in the background.
Especially ... whenever microstrategy or nexacro is possible to use in the background via queries (gscm for example) I
would prefer if it went through the reports via that." And: "metronome already knows how it works. info needs to be
relayed to gemini to use for its own scripts in the best way possible."

**Options.**
1. A fixed adapter per portal and report (Wizard-built requests, one tool per report), as the report catalogs planned.
2. Copy Metronome's recorded Flows: replay a person's recorded clicks.
3. Gemini writes its own browser scripts, like its own SQL, in a browser signed in as the person, with Metronome's
   knowledge of each portal as guides and helpers, and the protections inside the tool.

**Decision.** Option 3, agent-first as AGENTS.md asks.
- **The browser.** Playwright 1.62.0 (the version Metronome's Flows already run on the work PCs) drives the installed
  Google Chrome (or Edge, Settings → Portals) with Wizard's own profile in the person's Wizard home, never their
  everyday profile. It runs headless in the background. **Sign in to the portals** opens it visibly, one tab per
  portal; the person signs in themselves (SSO, MFA) and closes it. Wizard stores no password or cookie of its own.
  Only on a single-person PC (desktop app or work-PC install): a shared server behind SSO refuses portal settings.
- **The tools** (`portal` MCP server): `portal_guide` (how the portal works, the helpers, saved scripts),
  `portal_run` (Gemini's steps: open, click, fill, select, press, wait, look, read a table, and JavaScript evaluated in
  the page), `portal_save_script` (keep steps that worked, with parameters, on this PC).
- **Queries before clicks.** Inside the page, `fetch()` carries the person's session. Wizard keeps the page's own data
  requests in the page (`W.requests`, `W.replay`) and parses Nexacro SSV and XML and JSON replies (`W.parse`), so
  Gemini can call a portal's transactions with its own parameters instead of driving screens.
- **Metronome's knowledge relayed.** The guides (`wizard_connectors/portal_guides/`) and helpers
  (`portal_helpers.js`) carry what Metronome learned in `datap0nd/data_governance`: GSCM's Nexacro component paths,
  WorkFrames, the wait overlay, Datasets bound to Grids, `gds_bookmark` and the Favorite route, popups and its forbidden
  controls; ASAP's `iframe#content-frame`, the `_COMMON_INFO`/`_SESSION` objects and `menuInfo.do` menu walk (the token
  stays inside the helpers), prompts, Sunday-to-Saturday `YYYYWW` weeks, RUN and "Data rows:"; Superset's API for BDP.
  Company host names and GSCM's backend route names stay out of this public repository.
- **What protects the portals (inside the tool, whatever the script does):**
  - only the configured portals' hosts, their company domain, `WIZARD_PORTAL_HOSTS` and the hosts the person's own
    sign-in went through can be reached (requests, navigation, WebSockets), so a script cannot send data elsewhere;
  - a request whose path segment, service name, task id or action parameter starts with a write verb (save, insert,
    update, delete, remove, modify, edit, upload, import, approve, reject, register, create, new, add, submit, send,
    publish, share, pin, apply, confirm, cancel, reset, clear, schedule, subscribe, email, logout...) is aborted before
    it leaves the browser; PUT, PATCH and DELETE are refused except MicroStrategy prompt answers;
  - Superset SQL Lab runs one SELECT (or WITH ... SELECT) at a time;
  - clicks on controls named Save, Delete, Submit, Pin, Unselect, Sign out... (Metronome's `FORBIDDEN_CLICK_WORDS`)
    are refused; confirmations are answered No; downloads and service workers are off;
  - session tokens, passwords, cookies and long opaque values are redacted from everything Gemini sees (values,
    tables, request previews, errors and dialogs);
  - a sign-in page stops the read (`sign_in_required`): Gemini never types credentials;
  - bounds: 30 steps and about 3 minutes per call (under the Gemini CLI tool bridge's 180 s), 30 s per step by
    default (150 s at most), 500 rows of each table returned.
- **Labels.** Data mode `LIVE`, connector status `BROWSER_SESSION`. Never verified. The evidence keeps the steps and
  scripts (the query), the page, the rows and a digest. Check my data does not repeat a portal read.
- **The stage tells the truth.** A catalog search shows as "Searching the catalog of ASAP", a portal read as "Reading
  GSCM in your browser", and "Cross-checked N systems" counts only systems something was read from.

**Consequences.**
- AGENTS.md lists this third exception and its protections.
- New: `portals.py` (settings and rules), `portal_browser.py` (the browser thread), `portal_helpers.js`,
  `portal_capture.js`, `portal_guides/`, `tools/portal_tools.py`, `PortalSignIn.tsx`; API `GET /api/v1/portals`,
  `POST /api/v1/portals/sign-in`, `.../sign-in/done`, `.../check`; settings `WIZARD_PORTAL_ASAP_URL`,
  `WIZARD_PORTAL_GSCM_URL`, `WIZARD_PORTAL_BDP_URL` (and since 28 October `WIZARD_PORTAL_BDP_CATALOG_URL`,
  [decision](2026-10-28-bdp-information-catalog.md)), `WIZARD_BROWSER`, `WIZARD_PORTAL_HOSTS` (and
  `WIZARD_BROWSER_EXECUTABLE` for tests, never from a company file).
- WizardSetup.exe carries Playwright (38 MB wheel with its Node driver) and greenlet; no browser is downloaded. The
  desktop workflow publishes the portable runtime release when the locks name a new one.
- **Residual risks.** JavaScript in the page can do anything the person can do on screen; the network rules are the
  backstop, and they recognise writes by name, so a portal that writes through a neutrally named route would not be
  stopped. The same rules may also refuse a harmless request whose name starts with such a verb (a usage log): the
  call says what was refused. Both are first checked on the work PC.

**Evidence.** `tests/unit/test_portals.py` (37): settings, reachable hosts, reads and writes by path, service name,
task id, form field, Nexacro XML parameter and method, SQL Lab statements, Metronome's forbidden clicks, redaction,
tables from script results, single-person-PC only, and the API. `tests/integration/test_portal_browser.py` (9), in a
real Chromium against a simulated portal: a Nexacro Dataset as LIVE evidence with the script as its query, bookmarks,
tables and the page outline, a captured SSV transaction replayed with a new week, the ASAP menu walked with the token
never reaching Gemini, refused clicks, writes, other hosts and a confirmation, a sign-in page, partial results, a saved
script rerun with parameters. The real portals are first read on the work PC.
