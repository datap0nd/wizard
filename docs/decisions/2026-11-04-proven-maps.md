# 2026-11-04 — Wizard proves a portal map; Gemini's word does not

**Owner:** project owner. **Status:** decided (4 November 2026).

**Context.** The first run of the task "GSCM: map the columns and groupings behind each sales report's configuration"
read the daily sell-out report (DB4009) through its search panel, never found its Configuration button, wrote that the
report "does not support an Account/Operator dimension breakdown", and put that into the map and the GSCM platform
note. The owner adds the account in seconds: Configuration → Sales → Sales → ORG Sales, Apply, after choosing the
subsidiaries one by one. The owner: "how can you ensure we fully map GSCM once and for all? Are we being precise with
this? Also ... are we currently going through UI or doing direct queries?", then "yes build it, DB4009 first", and
"ensure that it doesnt have small limits".

Where it stood: Gemini opened reports through GSCM's own open function, read what the screen's grid held, and clicked
through Configuration. Direct requests were possible and preferred, but no GSCM request was ever proven: Gemini set
`verified` and `mapped` itself, and nothing compared a reply with the person's own export.

**Decision.**
- **Read the report's code.** `W.nexacro.transactions()` lists every data request a report's functions can send (each
  `transaction()` or wrapper call: service, address, input and output datasets, arguments, callback), every `.do`
  address in its code, and the application's wrappers. `W.nexacro.source(name)` gives a function whole. Complete by
  construction, not by what the screen happened to send.
- **Wizard proves; Gemini does not.** `portal_prove_request` sends a request twice from the person's browser (the
  screen's values, then one changed) and keeps it as proven only when both answers are clean (no error from the
  portal), hold the same datasets and columns, and the change changed the rows. Only it marks a request verified;
  `portal_map_save` ignores Gemini's `verified`, never drops a proof, and saves a report as partial until one of its
  requests is proven.
- **No claim of absence.** `portal_map_save` and `portal_map_route` refuse a sentence saying a report lacks a breakdown
  (account, operator, customer, dimension...): what was not found is unknown. A sentence saying what a choice needs, what
  was not found yet, or how rows look is a description and passes.
- **Checked against the person's own export.** A task that asks for a file reads a spreadsheet's every row as tables,
  and `wizard_task_compare` checks evidence against it row by row and number by number (keys, values, tolerance; the
  rows only one side has). MATCH is kept in the report's map entry. The export's figures stay in the run.
- **DB4009 first.** The task "GSCM daily sell-out by account (DB4009)" asks for the person's export, reads the report's
  code, follows the person's path once, maps every Configuration category, proves the request with the ORG Sales level,
  checks it against the export, and corrects the earlier claim. The broader task runs after it and skips DB4009.
- **Limits that would cut a map short were raised:** every column of a dataset and table (up to 5,000), 50,000 evidence
  rows per read, every option of a drop-down, whole request bodies in the browser's log, map fields up to 200,000
  characters, a repeating task up to 50 runs.

**Consequences.**
- Earlier maps keep their reports' status; a request only "verified" there is marked as Gemini's own account in the
  map's page, and the system prompt says to check its reply.
- A map's word "mapped" now means a proven request; "checked against an export" means a MATCH.

**Evidence.** `tests/unit/test_precise_maps.py` (verified and mapped only with Wizard's proof, a save never drops a
proof, claims of absence refused and descriptions allowed, the export comparison: a match, a number off, a row missing,
kept in the map, task only); `tests/integration/test_portal_browser.py` (a report's requests read from its code, the
wrapper the screen never called included; a request proven, refused by the portal, unchanged by the value, missing a
value).
