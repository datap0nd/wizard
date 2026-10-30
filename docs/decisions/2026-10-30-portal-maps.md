# 2026-10-30 — Wizard maps the portals, keeps the map, and reads them by their own requests

**Owner:** project owner. **Status:** decided (30 October 2026).

**Context.** The owner asked how Wizard reads the portals, "microstrategies and nexacro portals. AFAIK, its possible to
interact via query instead of playwright + screenshots". Wizard takes no screenshots: Gemini reads the page's outline,
the Nexacro Datasets in memory and the portals' own data requests (decision
[2026-10-23](2026-10-23-portal-browser.md)). But every question started from zero: Gemini explored the portal, found
the report, its filters and its request, and forgot them when the answer ended unless it saved a script. AGENTS.md also
still forbade "copied browser cookies, TLS bypass, `/mstr` event URLs or a debugging browser as a production
connector", a rule written for a server-side ASAP connector before the portal browser existed. The owner: "I don't want
it to be forbidden. I want this tool to be super agile ... I would love for gemini 3.8 flash to FULLY explore GSCM and
get ALL the technical details and shortcuts and save them in the knowledge base inside the work PC. Then, wizard picks
it up and QUICKLY uses that to navigate to the reports, explore, make the necessary filters, extract the data, provide
answers with it." And: "add these functions to wizard itself ... add a box for me to add the PAT token so that wizard
can make changes to wizard-content github repo (samsung enterprise github)".

**Options.**
1. A work-PC Gemini CLI task that explores GSCM. It has no access to Wizard's signed-in browser, and its results would
   reach Wizard only through a publish and a restart.
2. Wizard explores in one long run. Hundreds of tool calls outgrow the model's context, and a failure loses everything.
3. Wizard explores in rounds and keeps what it learns as it goes: each round is a fresh session that continues from the
   map. Questions read the map first, and the map is published to the knowledge base.

**Decision.** Option 3.
- **Map a portal** (Settings → Portals → *Map GSCM*, also for ASAP and the Big Data Portal): Wizard's own Gemini
  (3.8 Flash, the model for everyone) explores the portal in the person's signed-in Wizard browser in a conversation
  of its own (*Map GSCM*), so the person can watch it. Each round makes at most 80 tool calls (`EXPLORE_TOOL_CALLS`) and
  starts from the map. Rounds follow one another until nothing is left to map, two rounds in a row add nothing, the
  person presses **Stop**, the portal asks for a sign-in (sign in, then **Continue mapping**), or 30 rounds have run
  (then **Continue mapping**). Questions can still be asked while a
  portal is being mapped.
- **What a round does** (`prompting.EXPLORE_REQUEST`). First, how the application works: the client and its session,
  frames, the application's Datasets and its menu Dataset, how a report opens without clicking (the client's own
  `gfn_*` functions), the busy overlay, popups, the data request format and routes, and common filter formats. Then
  every report from the menu Dataset as *todo*. Then each report in turn: open it, list its filters and their options,
  run its search, capture the data request, read its datasets, prove the fast route (send it again with one filter
  changed), save it with the filters as `{{param}}` placeholders, and keep a script that reads it.
- **The map** (`wizard_connectors/portal_map.py`, `data/portal-maps/<portal>.json`): an overview, topics (technical
  details and shortcuts with the exact calls that worked), and per report its menu path and id, how to open it, its
  filters (values, format, the parameter each one sets), its datasets and columns, its requests (`verified` only when
  proven) and its saved script. Metadata only: no rows; secret-named fields and long opaque tokens are removed on every
  save.
- **Questions use it first.** `portal_guide` shows the map (overview, shortcuts, the index of mapped reports).
  `portal_map(find=...)` returns the matching reports in full, so a mapped report is read in one `portal_run`.
  `portal_map_save` adds what a question learns. The system prompt and the guides say so.
- **Requests straight from the browser.** A new `request` step sends a data request with the person's session without
  opening the portal's screens. It runs `fetch()` in a page on the request's own origin: the page the browser is on, or
  else a light page of that origin (`/robots.txt`), never GSCM's heavy start page. So Chrome's own network stack (proxy,
  certificates, single sign-on) carries it, and every rule on page requests applies, checked before it is sent too. The
  reply is parsed (SSV, XML, JSON): one dataset comes back as a table (evidence), and a `script` shapes anything else
  from `R`.
- **Nexacro discovery helpers.** `W.nexacro.appDatasets()` (the application's Datasets, the menu among them),
  `W.nexacro.functions()` (the client's own `gfn_`/`fn_` functions with the start of their source),
  `W.nexacro.inputs()` (a report's filters, buttons and grids, with a combo's options as `code = label`), and
  `W.nexacro.lookup()`.
- **Component paths and routes are no longer redacted.** The redaction of long opaque values (40+ characters) also
  hid Nexacro component paths (`mainframe.VFrameSet.WorkFrame0.form.cbo_market`) and long `.do` routes from Gemini and
  from the map. Dotted names with three or more parts and address paths now stay whole. JWTs, session ids
  (`...9C.worker1`) and base64 values are still shortened.
- **Published to the knowledge base.** Settings → Knowledge base has **Write token (PAT)** (`WIZARD_KB_WRITE_TOKEN`): a
  token with Contents read and write on the knowledge-base repository on the company's GitHub Enterprise Server. A
  company provisioning file cannot carry it (`provisioning.PC_CHOSEN`): only the person who enters it on their PC holds
  it. **Test connection** also says whether it can write. After a run that added to a map, Wizard commits
  `portal-maps/<portal>.json` and a readable `portal-maps/<portal>.md` (under `WIZARD_KB_PATH`) in one commit through
  GitHub's API (`wizard_documents.kb.write_files`). Only those files change, an unchanged map makes no commit, and only
  to a private repository. It refuses a map the knowledge base's own check would reject, which would stop every PC's
  sync. `docs.ps1 kb-publish` leaves `portal-maps/` alone. A PC without a map of its own reads the published one from
  the synced knowledge base. **Publish now** and **Start over** (this PC's copy) are in Settings → Portals.
- **The rule.** The ban on copied browser cookies, `/mstr` event URLs and a debugging browser is lifted; AGENTS.md
  keeps only "never disable TLS certificate checks". Use whatever route reads a portal fastest. The read-only rules
  stay: writes are refused by name and method, other hosts are refused, forbidden controls are never clicked, and
  Gemini never types a password. Those protect the company's systems from a script's mistake, and the owner asked for
  speed, not writes.

**Consequences.**
- New: `portal_map.py`, tools `portal_map` and `portal_map_save`, the `request` step, run kind `explore` with
  `RunManager.start_exploration` / `stop_exploration`, API `GET|POST|DELETE /api/v1/portals/{system}/map`,
  `.../map/stop`, `.../map/publish`, `maps` and `mapping` in `GET /api/v1/portals`, `PortalMaps.tsx`, the settings field
  `WIZARD_KB_WRITE_TOKEN`, `kb.write_files` and `kb.check_write`. The knowledge-base check accepts `portal-maps/*.json`
  (secrets refused, the file name must match the portal).
- AGENTS.md: the third exception mentions the `request` step and the map; company content mentions what Wizard writes
  to the repository; the old connector ban is replaced by the TLS rule.
- **Residual risks.** The map is only as good as what Gemini proved. A request marked `verified` was replayed once with
  one filter changed, not reconciled with the screen for every filter. A portal update can move a route or a
  component: a question that fails on the map's route explores again and corrects the map. Publishing makes the map
  visible to everyone who syncs the knowledge base: it holds report names, routes and filter codes, which is internal
  metadata of the same kind as the notes there.

**Evidence.** `tests/unit/test_portal_map.py` (13): merge, search and summary; secrets removed on save; publishing the
JSON and the page under the knowledge base's folder, and refusing a map with a secret; a PC starting from the
published map; the knowledge base's check of maps; the write token refused in a company file and loaded from the pane;
the mapping request; the tools (read the map first, add to it, guide index); and through the API with a scripted
Gemini: rounds until nothing is left (4 rounds, 3 reports), stopping when rounds add nothing, stopping at once with
what to do when the portal asks for a sign-in, a question answered
while a mapping runs, Stop, one mapping at a time, and a round that saved to the map publishing it.
`tests/unit/test_kb_publish.py` (2 new): Wizard's own files in one commit with everything else left alone, no commit
for an unchanged map, never to a public repository or without write access, and the write check.
`tests/integration/test_portal_browser.py` (3 new, real Chromium): the Nexacro helpers find the menu Dataset, the
`gfn_openMenu` shortcut and a combo's options; a `request` step reads an SSV transaction as LIVE evidence without
opening the portal's start page (a light page of its origin first, then nothing more once there), and a script shapes
the reply; a `request` step's writes, PUTs and other hosts are refused before anything is sent.
`tests/unit/test_portals.py`: component paths and routes stay whole, while a JWT, a session id with a route suffix and
base64 values are still shortened. `apps/web/src/components/PortalMaps.test.tsx` (3). The real GSCM is first mapped on
the work PC.
