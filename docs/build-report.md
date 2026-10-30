# Build report

The single running record the plan asks for: what is implemented, actual test output, operating mode and open
decisions. Update it with every change that alters behaviour.

## 2026-10-30 (latest) — Export settings for another PC; a write token that reads but may not write says how to fix it

The owner: "I want to set exactly the same app on a different PC... I want to export my settings file basically. and
imkport it there", then "yes build the export settings button. Also, github refused the write token HTTP 403 while
uploading a file (POST/git/blobs)." [Decision](decisions/2026-10-30-settings-export.md).
- **Export settings…** (WizardBar's tray menu, next to Import a settings file…): WizardBar asks the service
  (`POST /internal/v1/desktop/export`, control token, loopback only) and saves `wizard.provision` where the person
  chooses, after saying it holds the passwords in plain text. `settings_pane.export`: the company file's keys and every
  Settings field with the value this PC uses (environment > `.env` > this PC > company file); per-PC values, the write
  token and old model picks left out; checked as any provisioning file (`provisioning.render`, which
  `scripts/make_provision.py` now uses too). Afterwards WizardBar says what to do on the other PC and to delete the file.
- **The 403.** The publish read the repository, its branch and its files with the write token, then GitHub refused the
  first write (`POST /git/blobs`): the token reads but may not write, which is what a fine-grained token with Contents
  "Read-only" does (GitHub preselects Read-only when Contents is added). A refused write now says so, with the steps:
  Settings → Developer settings → Fine-grained tokens → the token → Edit → Contents: "Read and write" → Update; the
  token stays the same, so nothing changes in Wizard. When GitHub names the missing permission, the same steps follow.
  An archived repository (read-only on GitHub) is named before any write. The Settings help for the write token says
  that GitHub preselects Read-only.

**Tests.** `tests/unit/test_settings_pane.py` (export: precedence, left out, round trip through import, nothing to
export), `tests/unit/test_desktop.py` (export only with the control token; menu item and endpoint agree),
`tests/unit/test_kb_publish.py` (a plain 403 on the first write names a token that reads but may not write and the
steps; the permission header case gives the steps; an archived repository is named and nothing is written). WizardBar
built with `dotnet build -c Release` (warnings are errors).

## 2026-10-30 — A refused portal-map publish says which request and why

The owner: "github refused the request when publishing the portal mapping. The token needs contents read and write and
sso approval." and "the token I generated is simply classic token with repo access." That message was Wizard's guess
for every 403. On the company's GitHub Enterprise Server a classic token with the repo scope already reads and writes,
and tokens need no SSO approval there, so the guess pointed away from the likely cause: an organisation that refuses
classic personal access tokens. Settings → Test connection checked only the account's role, so it would have passed.
- **Why, from GitHub** (`wizard_connectors.github.refused`): a 403 is explained from GitHub's own message and headers:
  an organisation that refuses classic tokens (make a fine-grained token: resource owner the organisation, that
  repository only, Contents read and write), a token lifetime the organisation refuses, SSO (`X-GitHub-SSO`), the rate
  limit, approval, or a missing permission (`X-Accepted-GitHub-Permissions`, e.g. `contents=write`). Anything else
  names both usual causes. GitHub's message is always quoted.
- **Which request** (`kb.explain`): "while reading the repository (GET /)", "while uploading a file (POST /git/blobs)",
  "while moving the branch to the new commit (PATCH /git/refs/heads/main)" and so on. A protected branch (409 or 422)
  is named as one; a 409 is no longer always called "empty". The account-role refusal says the account, not the token.
- **Test connection** (`kb.check_write`): after the account's role, it asks GitHub to create a branch at a commit that
  does not exist. A token that may not write is refused (403, explained as above); one that may is told the commit does
  not exist (422). Nothing is created either way.
- The knowledge-base sync's own 403 (the read-only token) uses the same explanation. Settings' help for the write token
  says fine-grained, and that organisations may refuse classic tokens. Desktop docs: Test connection and two
  troubleshooting rows.

**Tests.** `tests/unit/test_kb_publish.py`: Test connection says a read-only token cannot write (GitHub asks for
`contents=write`) and a classic token is refused by the organisation, and the probe's request is a commit of zeros that
creates nothing; a refused map names the request and the cause for a classic token, a read-only token on upload, SAML
SSO, the rate limit and an unexplained 403 (no "SSO" unless GitHub says so); a protected branch (422 and 409) is named,
not called empty. `tests/unit/test_desktop.py`: the sync's 403 names classic tokens. Against the company's GitHub
server nothing was run here: whether the probe answers 422 for a token that may write is the owner's next Test
connection.

## 2026-10-30 — The Brain page draws the knowledge base the way graphify does

The owner, showing a graphify graph: "the knowledge base brain looks rough, was hoping it looked like this".
[Decision update](decisions/2026-10-28-brain-page.md).
- `graph3d.ts`: no knowledge-base root or area hubs; **communities** by Louvain modularity over every edge (weighted:
  related 2, shared tags 0.4, the rest 1; a fixed visiting order, so the same graph gives the same communities), named
  by their most linked note, largest first, the points without a link gathered last. The layout runs in 2D (every z
  stays 0) or 3D, with a weak pull towards each community's centre and longer spokes from a hub to its terms, tags and
  news categories. Statistics over the whole graph, with the communities' modularity (and the areas' on hover).
- `Graph3D.tsx`: 3D and turning by default (the owner, after a first 2D version: "but it needs to be 3D and rotate";
  a narrower lens, 0.5 rad, so near points do not swell; framed tighter, as a cloud never fills its sphere), 2D on a click
  (drag moves, the wheel zooms at the pointer); small points
  sized by their links; thin, slightly curved edges in the hub's colour; no rings, floor grid or axis triad; labels only
  on hover, on a pick, for a tour step's notes, or with **Labels** (each community's hub and the most linked points).
- `BrainPage.tsx`: a **Communities** panel (Select all, a check box per community to show or hide it, its colour, name
  and count; a click on the name lights it up and frames it), switchable to **Areas**; layers as check boxes; 2D | 3D,
  Labels, Rotate (3D) and zoom along the bottom. The search box lets go of the keyboard after a pick. Two screenshots 5 s
  apart differ at every size: it turns.
- Colours: the validated dark palette for the eight largest groups, grey after; graphify's Tableau 10 fails the
  `validate_palette.js --mode dark` checks on `#0f1117` (lightness band, chroma floor, green↔teal ΔE 14.0 below 15).

**Tests.** `apps/web/src/graph3d.test.ts` (14), e2e "the Brain page draws the knowledge base as a graph of
communities…" and the demo arrival, in both viewports on Chromium. Screenshots at 1280×720, 1600×900 and 1920×1080 over a
synthetic 101-note knowledge base (12 areas, 507 links, 198 glossary terms, mapped by the real `knowledge_map`) and
synthetic news: 356 points, 1,497 edges, 10 communities, Q 0.485 (not committed).

## 2026-10-30 — Updates no longer start PowerShell (Defender flagged it)

The owner: "I'm getting malware name execution/mdp.powershell.m4192 repeatedly since I updated wizard." The update of
the same day ("Updates download the way Metronome's setup.ps1 does", below) made every update read a hidden
`powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand ...` running `Invoke-WebRequest
-OutFile` into `%TEMP%`, started by an unsigned WizardBar.exe: two minutes after start, every six hours, and up to 40
times per check while GitHub did not answer. The Settings check started `powershell.exe -Command` with the same download
up to 40 times each time Settings opened. That is how a downloader looks to Microsoft Defender.
- **WizardBar** (`Updater.cs`): each read runs in WizardBar's own process with `HttpClient`, on the network stack Windows
  PowerShell's `Invoke-WebRequest` uses (.NET Framework): `WebRequest.DefaultWebProxy` (Windows' proxy settings, a PAC
  script included) with the person's proxy sign-in (`DefaultNetworkCredentials`), TLS 1.2, the same User-Agent and
  Accept headers. Everything else stays: mirror first (`api.github.com`, `codeload.github.com`), then the release, up to
  20 attempts 5 seconds apart, size, SHA-256 and version checks, `bar.log`. A read that outlasts its limit (30 seconds
  for a manifest, 10 minutes for the installer) is stopped. The logged reason is the innermost error, not HttpClient's
  "An error occurred while sending the request."
- **Settings → Check for updates** (`settings_pane.check_update`): Wizard's own connection only, mirror manifest first
  (raw Accept header), then the release; an answer that is not a manifest is refused. One try each, so the page answers
  in seconds; when both fail, **Check with Windows** hands the check to WizardBar, which retries.
- Still started by Wizard on Windows, unchanged since before this update: the Windows proxy lookup for Python
  (`outbound._windows_system_proxy`, `GetSystemWebProxy().GetProxy`, once per host) and the installer's Stop-Process
  of Wizard's own processes. Neither downloads anything.
- One more update has to arrive the PowerShell way: the WizardBar installed now still downloads as it does today, so
  Defender may report that one download once more.

**Tests.** `tests/unit/test_settings_pane.py`: the mirror is asked first with the raw Accept header and the release only
when it fails (403, or a proxy's page that is not a manifest); both errors are named when both fail; the service's source
starts no process. `tests/unit/test_desktop.py`: Updater.cs holds no `powershell.exe` or `-EncodedCommand` and reads
with `HttpClient`. WizardBar built with `dotnet build -c Release` (warnings are errors; 0 warnings) on Linux with the
.NET 8 SDK. The new read (Route and Read copied verbatim into a .NET 8 console program) run against the real hosts: the
mirror manifest (236 bytes, version 1.0.100.0), the release manifest through its redirect, a missing release file
("The remote server returned an error: (404) Not Found."), the mirror zip with a 2-second limit (stopped: "No answer
within 2 seconds.") and in full (46,581,972 bytes). The Settings check run against the real hosts: 1.0.100.0. Windows
on the work network, and whether Defender stays quiet, is the owner's next update.

## 2026-10-30 — The Brain page is the whole knowledge base as a 3D graph

The owner: "The knowledge base. I want to create a neural network or graphify of the full knowledge base, in 3D", "And
we replace the /brain, with that. A bit more... serious", "make it scientific, and complex, but not overly ... quirky.
keep news and tour." [Decision update](decisions/2026-10-28-brain-page.md).
- **Server** (`brain.py`): `GET /api/v1/brain` adds mentions (a note's text naming another note by id, title or an
  alias of four or more characters, as whole words; names two notes share or found in over a quarter of the notes left
  out; 12 per note), each link's weight, the glossary terms (up to 3,000), all of a note's tags (up to 15) and its
  length in words, and counts mentions.
- **Graph** (`apps/web/src/graph3d.ts`): root, areas, notes, tags on 2 to 60 notes, glossary terms, documented systems,
  news categories; area membership, related, mentions, shared tags (off at first), tagged, terms, documents, news.
  A seeded 3D force layout with Barnes-Hut repulsion (an octree), membership pulling hardest so areas form modules;
  a refresh keeps the places it had. Network statistics over the note network: nodes, edges, m, ⟨k⟩, k max, ρ, ⟨C⟩,
  modularity Q by area, components, ⟨ℓ⟩, D (sampled above 800 notes), P(k). Search by name.
- **Page** (`Graph3D.tsx`, `BrainPage.tsx`): a canvas with a perspective camera (drag, wheel, double click or R to
  frame, a slow turn unless reduced motion), edges batched by style and faded with depth, nodes back to front, labels
  that do not collide (flipped left at the right edge), a floor grid and an axis triad. Legend on the left (areas, layers
  with counts, sources), statistics strip along the bottom, a card per point with its edges and neighbours. The news
  panel, the demo arrival (N) and the tour stay; the tour frames what each step speaks of. Removed: the 2D picture
  (`BrainCanvas.tsx`, `layoutBrain`), the pixel wizard, starfield, pulses, counters and the Simple / Advanced toggle.
  Area colours are the dataviz skill's dark categorical palette, validated against the page surface `#0c1016`
  (`validate_palette.js --mode dark`: all checks pass; worst adjacent CVD ΔE 8.4).

**Tests.** `tests/unit/test_brain.py` (10, two new or extended: mentions; terms, tags and words). `apps/web/src/graph3d.test.ts`
(13). `apps/web/src/brain.test.ts` (tour and news helpers; the 2D layout tests went with the 2D layout). e2e: "the Brain
page shows the knowledge base as a 3D graph and walks a presenter through it, beside the app" and the demo arrival, in
both viewports, on Playwright's Chromium. Screenshots in Chromium at 1280×720, 1600×900 and 1920×1080 over a synthetic
101-note knowledge base in 12 areas (681 links, of which 384 mentions; 163 glossary terms) mapped by the real
`knowledge_map`, with synthetic news (not committed). Layout timing: about 10 ms per iteration for 2,400 points in
Node, run a few iterations per frame so the page never blocks; the synthetic base settles in 252 iterations.

## 2026-10-30 — The question box holds 100,000 characters

The owner asked whether the box's limit (4,000 characters; 2,000 for a note while an answer runs) could be tripled,
"or nearly unlimited actually".
- A question, and a note typed in the box while an answer runs, now take up to 100,000 characters (about 15,000 words):
  `MAX_QUESTION_CHARS` in `app.py` (`RunBody.question`, `SteerBody.text`, the follow-up a note asks) and in
  `Composer.tsx`. Both Gemini routes take the prompt in the request body or over stdin, never on a command line, so
  Windows' 32,767-character command-line limit does not apply. Each earlier question goes back to Gemini in full with every
  follow-up (six at most), about 150,000 tokens at worst, well inside the 1M-token window. Longer text goes in as
  an attached file, which Gemini reads when it needs to (up to 300,000 characters per file).
- A paste that fills the box says so under it: "The box holds 100,000 characters. Attach longer text as a file."
- A long question shows its first 12 lines in the conversation (4 as the report's heading) with **Show all**
  (`LongText.tsx`); a printed report shows it whole.

**Tests.** 1 API test (a 100,000-character question and a 9,600-character note reach Gemini whole, a follow-up keeps
the paste, one character more is refused) and 3 component tests; contracts re-exported.

## 2026-10-30 — Updates download the way Metronome's setup.ps1 does, up to 20 attempts

The owner: "it seems github downloads got tightened on work pc. can you make it so the check for updates does the same
thing or uses the same method as metronome setup.ps1 does? and it retries 20 times. I keep having to switch to personal
network to update."
- **What setup.ps1 does.** Windows PowerShell's `Invoke-WebRequest -UseBasicParsing` after setting TLS 1.2, retried
  (10 attempts, 5 seconds apart), against `api.github.com` (the newest commit of its branch) and a branch zip from
  `github.com/.../archive/...zip`, which `codeload.github.com` serves. Wizard read `release-assets.githubusercontent.com`
  through .NET's `HttpClient` (WizardBar) and Python (the Settings check), with Windows PowerShell only as a one-try
  fallback for the check.
- **WizardBar** (`Updater.cs`): every read is one Windows PowerShell `Invoke-WebRequest -UseBasicParsing` over TLS 1.2
  (the person's proxy sign-in when it is allowed; the address and file passed as data), up to **20 attempts, 5 seconds
  apart**. Each attempt tries, in order: for the check, the manifest on the `desktop-download` mirror branch from
  `api.github.com`, then the release's manifest at a fresh address (`?nocache=`); for the installer, the mirror branch's
  zip from `codeload.github.com` (WizardSetup.exe taken out of it), then the release's installer. A download that is cut
  short, a proxy's page or another release's file counts as a failed attempt; size, SHA-256 and version are checked as
  before. Each failed attempt is logged in `bar.log`; the first one shows a notification that Wizard keeps trying.
- **Settings → Check for updates** (`settings_pane.check_update`): on Windows the same reads, mirror then release, up to
  20 attempts; Wizard's own connection tries once only when Windows could not. PowerShell that cannot start is not
  retried. Off Windows nothing changes.
- The mirror branch already existed for "proxies that time out on release downloads" (`desktop.yml` force-pushes it
  with every release). One more update has to arrive the old way: the WizardBar installed now still downloads as before.

**Tests.** `tests/unit/test_settings_pane.py`: Windows is asked first and Wizard's own connection only after it fails
(both errors named; the own connection still rescues); the PowerShell read uses setup.ps1's method, passes the address
as data, asks the mirror with the raw Accept header first and the release with `?nocache=` second; 20 attempts 5 seconds
apart (40 reads when both fail, both hosts named); a later attempt that gets through wins; PowerShell that cannot start
is not retried; a JSON answer that is not a manifest is refused. `tests/unit/test_desktop.py`: the updater's mirror
addresses are the branch CI pushes, and WizardBar's attempts equal the Settings check's. WizardBar built with
`dotnet build -c Release` (warnings are errors) on Linux with the .NET 8 SDK. The updater's PowerShell script was run with
PowerShell 7.4 against the real mirror manifest (`api.github.com`, raw), the real mirror zip (`codeload.github.com`,
46,570,057 bytes, its WizardSetup.exe matching the release's SHA-256) and a missing release file (exit 1 with the
404 message). Windows PowerShell 5.1 on the work network is the owner's next update.

## 2026-10-30 — "List the reports in GSCM" in a few steps instead of 28

The owner shared Gemini's review of a 29 October run on the work PC (before the map shipped): "go to gscm. Read me the list of reports" took 28 tool calls
and 13 minutes. [Decision update](decisions/2026-10-30-portal-maps.md#update-30-october-2026--list-the-reports-in-gscm-took-28-steps).
- Every portal read gets an evidence id, tables and anything else (as field/value rows), so Gemini cites a menu
  summary as it is instead of re-reading it as tables (16 of the 28 steps).
- `W.nexacro.menu()`: the menu tree (`gds_topMenu` on the work PC) as one citable table; `W.objects(table)`; the guide
  says tables are objects, not arrays (the `bookmarks.slice is not a function` crash).
- Catalog searches and `wizard_list_sources` say the catalog is not the portal's menu and point to `portal_map` /
  `portal_run`; the system prompt says an old platform note's catalog route predates the live portal; the
  `/wizard:platform-guide` command writes portal notes that point to the portal tools.

**Tests.** 3 new (one in real Chromium); contracts re-exported. The real GSCM is first read on the work PC.

## 2026-10-30 — Steer Wizard while it works, and choose the systems a question may use

The owner: "I want to be able to steer (for example I notice it's using a wrong table)" and "select what systems I want
it to access ... leave it on Auto as well"; then: both ways of steering, corrections kept per person, the knowledge
base on when systems are narrowed, and "only these". [Decision](decisions/2026-10-30-steering-and-systems.md).
- **Notes while Wizard works.** While an answer runs the question box takes a note ("Tell Wizard while it works").
  Code Assist hands it to Gemini before its next step (`code_assist.py`: after the tool results; the step's calls not
  yet run come back `not_run`; a note that arrives during the answer reopens the work). Gemini CLI and replay cannot
  take one: the note stops the run and asks again with it (`POST /api/v1/runs/{id}/steer` answers `follow_up`).
  The card lists the notes, waiting then read by Wizard.
- **Not this** on every data step (stage caption, a system's calls, Step by step): wrong table, filter, period or
  something else, plus what to use instead. Gemini gets the step's SQL or report and is told not to cite its evidence;
  citing it anyway is a warning. After the answer it asks again with the correction.
- **Follow-ups carry the work:** up to 15 steps of each earlier answer (SQL, result, evidence id, the person's notes),
  and stopped answers are part of the conversation.
- **Remember** under a note or a question keeps the person's own words (Account → What Wizard remembers: list, edit,
  delete; 50 at most), added to every question they ask (`/api/v1/memories`).
- **Systems picker** beside the question box: Auto, or only the systems ticked (the knowledge base comes on with the
  first; a file switches Attached files on; Metronome is not offered). The conversation keeps it, and so do Check my
  data and Make recurring. The card says "Only: ...", the stage dims switched-off systems. Strict inside the run: only
  their tools are offered, a call to a switched-off system is refused (`system_off`, MCP path too), the source list and
  catalog search list only what is on, Check my data does not re-run an off source. `wizard_ask_for_system` (23rd tool)
  lets Gemini ask; the card offers "Switch on GSCM and continue". Changing the picker mid-run applies at once
  (`POST /api/v1/runs/{id}/systems`).
- Contracts: `steer`, `steer_read`, `systems_changed`, `system_requested` (and `access_request_proposed`, emitted
  since 28 October but missing from the list) in the run-event schema; the report records `systems`, `steers` and
  `rejected_evidence`. Store: `runs.systems` and a `memories` table, added without a schema version change.

**Tests.** `tests/unit/test_steering_and_systems.py` (9): step naming and the work log, the follow-up prompt with steps,
systems and remembered notes, a note's wording, tool-to-system mapping and what is offered; Code Assist against the
scripted Google fake: a note mid-step skips the rest of the step and reaches the next turn, a note during the answer
reopens it, a system switched on brings its tools. `tests/integration/test_steering_api.py` (11) with a scripted
runtime that takes notes as Code Assist does: only the chosen systems offered and the others refused, unknown systems
refused, a live note and Not this (events and report validated against the contracts), an answer citing a rejected
step flagged, switching systems mid-run, Not this after the answer with the steps in the follow-up's prompt, a note
stopping a replay run and asking again, Check my data keeping the systems, a file switching Attached files on,
remembered notes per person. Real Gemini CLI 0.62: a run limited to NERP and the knowledge base is offered only their
tools and Wizard's own over MCP; an Auto run is offered every tool but `wizard_ask_for_system`, and the installation
probe (`run.py --check`) now compares the CLI's declarations with what Wizard offers the run, not the whole catalog.
`apps/web/src/components/Steering.test.tsx` (9). E2E (both viewports): the picker and
"Only:" through a reload; Not this after an answer, Remember, and the note in the account dialog. Seen in Chromium at
1280×900 and in the 420×640 panel with a scripted note-taking runtime (not committed); the real Code Assist route is
first steered on a work PC.

## 2026-10-30 — Wizard maps the portals, keeps the map, and reads them by their own requests

The owner: "I want this tool to be super agile ... I would love for gemini 3.8 flash to FULLY explore GSCM and get ALL
the technical details and shortcuts and save them in the knowledge base ... Then, wizard picks it up and QUICKLY uses
that", "add these functions to wizard itself", and "add a box for me to add the PAT token so that wizard can make
changes to wizard-content github repo". [Decision](decisions/2026-10-30-portal-maps.md).
- **Map GSCM** (Settings → Portals, every configured portal): Gemini explores in rounds (run kind `explore`, at most 80
  tool calls each, a fresh session that continues from the map), in a conversation of its own; rounds follow until
  nothing is left to map, two rounds add nothing, the person stops it, or 30 rounds ran. A question runs beside it.
- **The map** (`portal_map.py`): overview, topics (shortcuts with the calls that worked), and per report menu path and
  id, how to open it, filters, datasets, requests with `{{param}}` placeholders, saved script, status. Tools
  `portal_map` (summary, find, report, topic, todo) and `portal_map_save`; `portal_guide` shows the map; the system
  prompt and guides say to read it first.
- **`request` step**: a portal's data request sent with the person's session from a page on its own origin (a light
  `/robots.txt` page when the browser is elsewhere, never the portal's start page), with the write and host rules
  checked before sending and applied to the request; one dataset in the reply comes back as evidence.
- **Nexacro helpers**: `W.nexacro.appDatasets()`, `functions()`, `inputs()`, `lookup()`.
- **Redaction fix**: Nexacro component paths and long routes were shortened as if they were tokens, in everything
  Gemini saw; they now stay whole (JWTs, session ids and base64 values are still shortened).
- **Write token (PAT)** in Settings → Knowledge base (`WIZARD_KB_WRITE_TOKEN`, never in a company file); Test
  connection checks it can write; after a run that added to a map, Wizard commits `portal-maps/<portal>.json` and `.md`
  (one commit, only those files, private repository only, nothing when unchanged). **Publish now**, **Start over**.
- AGENTS.md: the ban on copied browser cookies, `/mstr` event URLs and a debugging browser is lifted (TLS checks stay);
  the portal exception and the company-content rule describe the map and the write token.

**Tests.** `tests/unit/test_portal_map.py` (13, new), `tests/unit/test_kb_publish.py` (2 new),
`tests/integration/test_portal_browser.py` (3 new, real Chromium), `tests/unit/test_portals.py` (redaction of names vs
secrets), `apps/web/src/components/PortalMaps.test.tsx` (3, new). Contracts re-exported (`tool-catalog.json`,
`openapi.json`). The real GSCM is first mapped on the work PC.

## 2026-10-28 — The Brain page: a simple and an advanced view, and more room for the news

The owner: "in the /brain, create a simple/adavnced toggle, advanced is current view (more mephasis on the news on the
bottom right, the section is too small) and the simple one is without anymations and the wizard logo and the cards at
the bottom." [Decision update](decisions/2026-10-28-brain-page.md).
- **Simple / Advanced** in the header; V switches, `?view=` opens one, the browser remembers the choice (local storage,
  a convenience only). Advanced is the page as it was. Simple: no wizard in his circle, no counters along the bottom,
  nothing moving (the canvas is drawn still, every CSS animation is off under `.brain-still`, the news total shows at
  once, the headlines do not scroll).
- **More room for the news**, in both views: the panel is 420 px wide (480 px from 1280 px screens), the chart is
  64 px high across the panel, the categories sit in two columns, and the latest articles list is at least 220 px with
  larger headlines. At 1440×900 it shows three to four articles where it showed two; at 1280×720, two where it showed
  almost none.
- With motion off (simple, or Windows' reduced-motion setting) the chart's running-total line used to stay invisible
  (it is drawn in by an animation); it is now drawn.

**Tests.** E2E (Brain page): Simple hides the wizard and the counters and keeps the picture, the choice survives a
reload, V switches back and both return. `apps/web/src/components/brain/NewsPanel.test.tsx` (2): in the simple view the
total shows at once and the headlines never scroll; in the advanced view it counts up and scrolls. Seen in Chromium at
1440×900 and 1280×720 with a synthetic news table (40 headlines, 1,512 total, 8 categories) answered by the browser
in place of the database (not committed).

## 2026-10-28 — The roadmap page: what Wizard does today and what comes next

The owner: "Create a /roadmap in wizard ... what wizard can already do on the left, the roadmap comes on the right.
make it visual", a deadline on each Friday from this one, controlled "with left and right arrows", with logos, and the
PowerPoint step taking two weeks. [Decision](decisions/2026-10-28-roadmap-page.md).
- **`/roadmap`**, a page of its own like `/brain`, on the same dark stage. Left: what Wizard already does (nine
  capabilities from the README's "What runs today") and the systems it reads, as logos. Right: a ruler from today to
  each Friday, and the steps: week 1 (Fri 30 Oct) more portals read live, SC+ Global Dashboard and the NERP BI Portal;
  weeks 2–3 (Fri 13 Nov) PowerPoint slides from an answer; week 4 (Fri 20 Nov) a richer knowledge base (metrics,
  business presentations, strategy) from meetings with the heads of business and each area's main PIC. Each card has
  its countdown ("Next · In 2 days"); a step past its Friday and not done says "Due date passed".
- **Presenting:** the roadmap starts empty; → (Space, Page Down) shows the next step, ← takes it back, End all, Home
  none, F full screen; buttons do the same.
- **Content in one file**, `apps/web/src/roadmap.ts`: each step's length in weeks sets its Friday, so a longer step
  moves the ones after it. No data is read and no sign-in is needed. New logo tiles for SC+ and PowerPoint
  (`SystemLogo`), ready for when SC+ joins the systems stage.

**Tests.** `apps/web/src/roadmap.test.tsx` (3): the Fridays from 30 October with slides taking weeks 2–3, a longer
step moving the rest, every item with a logo or icon, the meetings line; countdowns (In 2 days, Due tomorrow, Due
today, Due date passed, Delivered) and which step is next; the page showing nothing on the right until →, one step
per →, ← back, Home, End and the buttons. E2E: `/roadmap` served, arrows, weeks 2–3, back to the app. Seen in
Chromium at 1440×900 and 390×844 with no horizontal scroll.

## 2026-10-28 — Check for updates reads the release where Wizard's own connection cannot

The owner, on 1.0.59: "imn trying to click chceck for updates but I get: could not read the release ssl:c:1015 error".
- **Cause.** In the bundled Python (3.13.15), `_ssl.c:1015` is "The handshake operation timed out": the connection
  reached a server but the TLS handshake never finished: the likely cause is the route, not the certificate. The check
  resolved one proxy for `github.com` and reused it for GitHub's redirect to `release-assets.githubusercontent.com`,
  and Python cannot sign in to a proxy as the person. WizardBar's updater (Windows' own connection: the proxy for each
  address and the person's proxy sign-in) is what installed 1.0.59, and `setup.ps1` downloads releases the same way.
- **Fix.** Each redirect hop gets its own route (`outbound.proxy_for` for that address), and a handshake that does not
  finish fails after 10 s instead of 30 s. When Wizard's own connection still fails on Windows, Windows reads the
  manifest: Windows PowerShell's `Invoke-WebRequest` (proxy settings, PAC and the person's proxy sign-in), into a
  temporary file. An HTTP answer such as 404 or 503 is reported as it is. The message now names the host and the route
  (`outbound.explain`), and both failures when Windows fails too.
- **Settings → Version and updates**, in the desktop app: when the check fails, **Check with Windows** has WizardBar
  check and, if there is a newer release, install it with its own connection, as the tray's **Check for updates…** does.

**Tests.** `tests/unit/test_settings_pane.py`: a redirect served by a local HTTP server is routed hop by hop (each
address asked of `proxy_for`); the owner's handshake timeout falls back to Windows and finds 1.0.66; Windows failing
too names both; a 503 never asks Windows; off Windows Windows is not asked; the PowerShell reader passes the address
as data, reads a manifest with a byte-order mark and reports PowerShell's first error line.
`apps/web/src/components/SettingsDialog.test.tsx` (2): **Check with Windows** appears in the desktop app after a failed
check and sends `update` to WizardBar; it does not appear in a browser or after a check that worked. The real check on
the work PC is the owner's next click.

## 2026-10-28 — The Brain page: a demo "new article came in" for a static news table

The owner: "The table is a static table. I'm not updating anything. I want a fake 'new news article came in' animation,
not an actual true sql query please." [Decision update](decisions/2026-10-28-brain-page.md).
- **N** on the Brain page, or the tour's news step 2.5 s after it opens, plays the arrival: one of the table's own
  articles (below the top three, never the same one twice) slides in at the top as "just now", marked NEW, with
  "1 new article just arrived" and a flurry along the news synapses. Nothing is written and no count moves.
  `demoArrival` in `apps/web/src/brain.ts`; AGENTS.md records it as the page's one staged motion.
- The page no longer watches for real new rows: it reads the news on opening and every 10 minutes.
- A table loaded in one go: recency and weeks count by publication date (`news_queries`), the chart's right end names
  its last week, and "published in the last 7 days" / "newest … ago" show only when recent. The tour step is
  "Reading the market".

**Tests.** `brain.test.ts` (9, 1 new): the demo pick and its date and origin, never twice, none left. `test_brain.py` (9):
weeks and recency by publication date, the added time only reported. `test_brain_postgres_real.py` (2) updated on real
PostgreSQL 16 (2 in the last 7 days by publication date, the undated row in the total only). New e2e: N slides the
fourth headline to the top with NEW and "just now", the list keeps its length and the total stays 1,512 (desktop and
narrow). Checked in a screenshot at 1920×1080 over the synthetic 1,513-row table made static (newest three weeks old).
## 2026-10-28 — Access requests: Wizard opens the form and fills the answers you saved

The owner: "I want wizard to open the request access page at least. There also should be a form for access requests
(we fill in the same fields over and over) that we should be able to predefine in wizard."
[Decision](decisions/2026-10-28-bdp-access-requests.md).
- **Settings → Portals → Access request form** (shown when the Big Data Portal is configured): the fields answered on
  every request (as the form names them) with the usual answer, and an optional request page. Kept on this PC for this
  person (`access-requests.json`). After a request window closes, the labels Wizard saw on the form are offered as
  fields to add. **Open the request page** opens it straight away.
- **Under an answer:** when the person lacks access to a table, Gemini calls `portal_request_access` (the table's page,
  the tables, this request's own answers such as the reason). The answer shows a card with **Open the request form**;
  nothing opens before that click.
- **The window:** Wizard's browser opens visibly on the page and, as the form appears (also after the person presses
  Request access), writes the saved answers and this request's into fields whose label matches, outlines them and
  shows a note. Only empty fields, never one the person cleared, never a password; only that portal's own pages. It
  never clicks, presses a key or submits; the person submits in their window, which has no write filter. Gemini's
  portal reads wait until it is closed, and its own steps still refuse every access request.
- Fixed while previewing: a reopened answer dropped event types the server did not list, so the card would have
  vanished after a reload (`access_request_proposed` is now kept).
- AGENTS.md (the portal exception), the threat model, README, `docs/platforms.md`, `docs/desktop.md`, task 40, the
  guide and system prompt updated; contracts regenerated.

**Tests.**
- `tests/unit/test_access_requests.py` (7, new): the saved form's limits, the addresses a window may open, what it
  fills, Gemini's proposal (never sent), the API with its Wizard-header check and audit, a reopened answer keeping its
  card, and the activity labels.
- `tests/integration/test_portal_browser.py` (11, 1 new), real Chromium: a catalog table page whose form appears after
  Request access is filled from saved answers (label beside, `label` wrapper, table row, `aria-label`, select); a
  pre-filled field and the password are left alone; a field the person cleared is not refilled; nothing is sent until
  the person's own click, which goes through; the form's labels are kept; Gemini's reads wait while the window is open.
- `apps/web`: the run reducer keeps each request once; the stage places the tool on BDP (58 tests). The settings panel
  and the card were checked in screenshots.

## 2026-10-28 — The Brain page: what Wizard knows as one picture, and the news it keeps reading

The owner, preparing a meeting with the MENA President: "a 'brain' view with all the topics, the portals, etc", the
news table ("1500 news already curated and categorized") shown "as an ongoing automation", and "the brain view could be
something additional. I dont want to mess with the original functionality."
[Decision](decisions/2026-10-28-brain-page.md).
- **`/brain`**, a page of its own (like `/quick`): the chat, sidebar, systems stage and Settings are unchanged, and
  nothing in the app links to it. A dark stage for a meeting-room screen: the pixel wizard casting in his circle, the
  systems around him (ASAP, GSCM, BDP, the AI Team Database, the knowledge base, Metronome: whatever this person can
  use), each knowledge area as a cluster of notes, synapses for the notes' own links and their strongest topic links,
  and pulses running along them into the wizard. Hover or click a note for its title, summary and status (draft,
  checked by an expert, signed). Counters along the bottom: notes, topics, connections, news articles, systems, terms,
  datasets, readable tables.
- **The news panel**: the total, the date it starts, how many in the last 7 days and how long ago the newest came,
  articles per week with the running total, the categories, and the latest headlines scrolling slowly (a pointer stops
  them). The page asks every minute; new articles jump to the top with NEW and a flurry along the news synapses. "How
  this was read" shows the table and the queries.
- **A presenter tour** built from what was read (intro, up to six topics with their best-linked notes, the systems, the
  news, "Ask it anything"): → / Space / Page Down next, ← / Page Up back, Esc out, F full screen. The caption moves to
  the top when the topic it shows is at the bottom.
- **API.** `GET /api/v1/brain` (the map) and `GET /api/v1/brain/live` (readable tables and the news, through
  `PostgresQuery`: one statement as a subquery, read-only transaction rolled back, fresh connection, read-only account;
  only for people who may read the whole database; read at most every 45 s). New settings `WIZARD_NEWS_TABLE` and
  `WIZARD_NEWS_DATABASE` (`.env` or the company file), needed only when the table is not called `news`; a bad value
  is reported on the page and never stops Wizard. No Gemini tool changed. Contracts regenerated (`openapi.json`).

**Tests.** `tests/unit/test_brain.py` (9): the map's areas in the standard's order, stages, glossary terms, links to
notes that exist only, which notes document which system, counts; column matching (a text `date` is not a date, arrays,
names that contain the word); the table called `news` wins and a table needs a title; names quoted and array categories
unnested; every statement read-only and rolled back; a configured table checked, a missing one explained; the cache and
errors; the API's sign-in, rights (`not_allowed` without whole-database rights) and caching.
`tests/integration/test_brain_postgres_real.py` (2) on a real PostgreSQL 16 under a read-only role: the news read with a
`text[]` category column, NULL rows, a non-web link, weeks and the 7-day and 1-day counts; the table found by name and
the relations counted. `apps/web/src/brain.test.ts` (8): every note laid out once inside the page, news on the right
sized by articles, synapses, focus and pointer, names kept on the page, the tour's numbers and its six-topic limit,
running totals and "ago". E2E: the page signs in, shows EXAMPLE CONTENT, clusters, systems with reports, counters and
the news-missing reason, walks the tour with the keys and goes back to the app.

Seen in Chromium at 1280×720, 1600×900 and 1920×1080 against a local PostgreSQL 16 with a synthetic 111-note knowledge
base and 1,512 synthetic articles (scratch only, not committed); a row inserted while the page was open appeared within
a minute (1,512 → 1,513).
## 2026-10-28 — The portal sign-in outlives its window

The owner: "I filled in portal addresses. I signed in to them. Closed the browser. When I click check sign in I still
get that the sign in wasn't done. Possible that the browser headless profile is not the same as the one where we sign
in?" [Decision update](decisions/2026-10-23-portal-browser.md#update-28-october-2026--the-sign-in-outlives-its-window).
- **Cause.** The profile is the same folder. Chrome drops session-only cookies (no expiry date) when it closes, and
  most portal and sign-in sessions use them, so the sign-in ended when the person closed the window. Reproduced in
  Chromium: a session-only sign-in cookie fails Check sign-in after the window closes, a lasting one passes.
- **Fix.** As Metronome's Flows do with their browser's sign-in: Wizard notes its own browser's cookies while a window
  is open (once the last window closes, Chrome has already dropped them), keeps the session-only ones the portals and
  the sign-in hosts receive in `session.bin` through the secret store (DPAPI on Windows), and puts them back whenever
  its browser starts, also after a restart. The background browser's are kept after every call, so a renewed session
  is kept too. No password is stored; Gemini still never types one.
- **Check sign-in** names the page it ended on when a portal is not signed in: "GSCM: asks for a sign-in (Sign in ·
  login.company.example)".
- AGENTS.md's portal exception, the decision record, README and `docs/desktop.md` say the session cookies are kept.

**Tests.**
- `tests/integration/test_portal_browser.py` (11, 1 new), real Chromium, a portal whose sign-in is a session-only
  cookie beside a lasting one: signed in in the window, window closed, Check sign-in passes; after a Wizard restart it
  passes again; only the session-only cookie is kept. On the previous code it fails as the owner saw it (`Sign in`).
- The real portals are first checked on the work PC.

## 2026-10-28 — The Big Data Portal: its information catalog and Superset, both in Settings → Portals

The owner: "For bigdata portal, there's two things: the information catalog, where we search for tables and request
access to them. Then we have superset, the actual query tool." And: "In the wizard menu, we should have both links."
Wizard had one BDP address, Superset's. [Decision](decisions/2026-10-28-bdp-information-catalog.md).
- **Settings → Portals** has **Big Data Portal: information catalog** (`WIZARD_PORTAL_BDP_CATALOG_URL`, new) and **Big
  Data Portal: Superset** (`WIZARD_PORTAL_BDP_URL`, same key as before). Either alone turns BDP on; it stays one
  system with one set of rights. The section shows "Big Data Portal (Superset, information catalog)".
- **The Wizard browser** reaches both hosts, opens a sign-in tab for each and checks each ("Big Data Portal:
  information catalog: signed in"). `portal_guide` lists both addresses; a step's `/path` stays on the application the
  page is on. `GET /api/v1/portals` lists a portal's `parts`.
- **Gemini's guide** to BDP: find the table in the information catalog (explore it, then call its own search request),
  then query it in Superset. The system prompt says the same, and that requesting access is the person's own step.
- **Access is never requested by Wizard**, inside the tool: Request clicks are refused, `request` is a write verb (it
  also stops Superset's own `request_access`), a POST to an access-request address and a GraphQL mutation are refused.
  Searches and listing one's own requests still read.
- Work-PC task 40 also records the catalog's address, product, sign-in and request route.
- AGENTS.md is unchanged: the portal exception and its protections already cover a second BDP address. README,
  `docs/platforms.md`, `docs/desktop.md`, the decision records and contracts updated.

**Tests.**
- `tests/unit/test_portals.py` (52, 15 new, 2 extended): both addresses and either alone, hosts, relative paths per
  application, access-request writes against reads, GraphQL mutations against a search text, Request clicks, the
  settings fields, and `GET /api/v1/portals` with both addresses.
- `tests/integration/test_portal_browser.py` (10, 1 new), real Chromium with the catalog on `localhost` and Superset on
  `127.0.0.1`: the guide's addresses, a catalog table as evidence, a path that stays on the catalog, a refused Request
  access click and POST that never reach the server, and the per-application sign-in check.
- The real catalog and Superset are first read on the work PC.

## 2026-10-26 — Download of an edited workbook: Wizard saves it in Downloads itself

The owner: "when I try to download a file after it edited something, says: couldn't finish download in chrome."
[Decision update](decisions/2026-10-23-edited-attachments.md#update-26-october-2026--download-on-the-persons-own-pc-saves-into-downloads).
- **Cause.** Chromium shows "Couldn't finish download" (`FILE_UNFINISHED`) when the server sends fewer bytes than its
  Content-Length, when the file cannot be written or renamed (a sharing violation, often a scanner or a protection
  agent holding it), or when the browser stops. Here, the same edited copy downloads fine in Chromium, through the API
  and through the real Download button, so it fails on the work PC, where Excel saves the copy. NASCA-protected
  workbooks open only where Office saved them, so a browser download of one would not open even when it finishes.
- **Fix.** Where Wizard runs on the person's PC (signed in locally, page on the same PC, as for Outlook drafts),
  **Download** asks Wizard to save the copy into their Downloads folder itself:
  - `POST /api/v1/attachments/{id}/save` runs `wizard_docs.py save-copy` in its own process under the Office lock.
    Excel opens the copy read-only and writes it with `SaveCopyAs`, so a protected workbook opens where it lands.
    Without Office, or when Excel cannot, the bytes are copied, with a warning when Excel failed.
  - The Downloads folder is Windows' known folder (it may be redirected), else `~/Downloads`. An existing file is never
    overwritten: a taken name gets (1), (2)…, and names cannot leave the folder.
  - The card then says where the file was saved and offers **Open** (`POST /api/v1/attachments/{id}/open`), which
    opens only a copy Wizard saved since it started. Both are owner-only and audited.
  - Elsewhere (behind a proxy) the server answers `not_on_this_pc` and the page downloads through the browser as
    before. `GET …/file` now reads the whole file before answering, so an unreadable file is an error, never a
    download cut short.
- No new Gemini tool; AGENTS.md, README and the decision record updated; contracts regenerated.

**Tests.** `test_edit_attachment.py` (10, 4 new):
- Excel writes the saved copy (fake COM): read-only open, `SaveCopyAs`, Close without saving; never overwrites;
- a byte copy without Office, and when Excel fails (with the warning);
- through the API: saved in Downloads, the second save as "(1)", Open, Open's failure in words, the request header
  required, another user refused, a page on another PC told `not_on_this_pc` and served the whole file, an unreadable
  file refused before any byte;
- names never leave Downloads.

`RunCard.test.tsx`: on this PC no browser download starts and the card says where the file was saved, then Open;
elsewhere the browser downloads it; a failure is shown in words.

In a real Chromium against a local server (synthetic workbook, replay runtime): from `127.0.0.1` the Download button
saved `Gulf sales (edited).xlsx` into the Downloads folder with no browser download; from the container's own address
the browser downloaded all 5,508 bytes.

`verify_all.sh --allow-blocked=live-parity,postgres` with `CI=true`: every required layer passes (Python 451 passed and 5 skipped, real
Gemini CLI 4, portal-browser 9, web unit 57, e2e 16); postgres and live-parity are BLOCKED as allowed. Real Excel,
NASCA and the work PC's Downloads folder are first exercised on the work PC.

## 2026-10-23 (later) — Company content never stops Wizard; crashes name the build that ran

The owner reported, after updating: "wizard has an error and wizard stopped", quoting a `TypeError` (`build_services`
got an unexpected keyword argument `postgres_name`) and "connector status ROWS_VERIFIED is not allowed for real
content: no approved live adapter exists for this system yet".
- **ROWS_VERIFIED.** Start-up validated the company content and stopped the service (exit code 2, "settings have a
  problem") because a report catalog claimed `ROWS_VERIFIED`. The same rule made the knowledge-base sync refuse a
  whole commit.
  - Claims of readable rows (status `ROWS_VERIFIED` or `SYNTHETIC_FIXTURE`, `row_access` `ROWS`, a data `file`,
    data mode `SYNTHETIC`) are now warnings. `catalog.navigation_only` takes them back when real content loads, so
    such a catalog loads as navigation only, and a catalog edit can neither unlock rows nor stop Wizard.
  - At start-up, a content file with a real error (not JSON, no front matter, a credential) is left out and logged
    instead of stopping the service. The sync still refuses commits with errors.
  - Live portal reads go through the portal browser, not catalog flags.
- **The TypeError.** `build_services` has taken `postgres_name` since 20 October 08:54 (`8a7e07a`), and the installer
  replaces the whole program folder. So the line comes from an older copy of the code: an old line in the log, which
  keeps earlier runs, or another, older Wizard folder. The start-up log line and any start-up crash now name the build,
  the commit and the folder the code ran from.

**Tests.** `test_content.py`:
- readable claims are warnings;
- Wizard starts with a `ROWS_VERIFIED` catalog, a non-JSON catalog, a note without front matter and a note with a
  password;
- the catalog loads as navigation only, and the broken and leaky files are left out.

A local start with such content answers `/api/v1/health` and logs the warnings.
`verify_all.sh --allow-blocked=live-parity,postgres,e2e` with `CI=true`: every other layer passes (Python 447 passed and
5 skipped, real Gemini CLI 4, portal-browser 9, web unit 55). e2e cannot launch this sandbox's Chromium build, and the
UI is unchanged since its last pass.

## 2026-10-23 (later) — Wizard edits a copy of an attached workbook and hands it back

The owner attached an Excel file and asked for changes; Gemini answered with "a pastable code block". They want Wizard
to "edit the file and spit back an edited file". [Decision](decisions/2026-10-23-edited-attachments.md).

**What changed.**
- `wizard_documents/edit.py` (new): the operations and two engines.
  - Operations: set, clear, insert and delete rows and columns, delete rows where, sort, format, column width, find
    and replace, add, rename and delete sheets, freeze, autofilter.
  - `ExcelBook` (Office COM): opens the original read-only, uses Excel's own Sort, Replace and AutoFit, and saves with
    SaveAs in the same format.
  - `OpenpyxlBook`: for .xlsx and .xlsm without Office. Conditions read Excel's saved values, and it warns about
    charts and moved formulas.
- `wizard_docs.py edit`: runs the edit in its own process.
- `attachments.py`:
  - `Attachments.edit` makes the copy, converts it, and binds it to the conversation as the next F label (origin
    `edited`).
  - One thread lock now serialises every Office job, conversion or edit; edits run from tool threads.
- Tool `wizard_edit_attachment` (category present; 25 tools with portals configured). The run emits `file_made`.
  `GET /api/v1/attachments/{id}/file` downloads, for the owner only (audited). The prompt has one line for the
  failure the owner saw.
- Web:
  - The edited copy shows under the answer with **Download**.
  - Edited copies are not shown as files the user sent.
  - The stage puts edits on "Attached files" ("Editing a copy in").
- openpyxl 3.1.5 and et-xmlfile are added to the dependencies and the portable locks.
- Docs: AGENTS.md, README, decision record; contracts regenerated.

**Tests.** `test_edit_attachment.py` (6):
- value parsing;
- every operation on a copy with openpyxl, with the original unchanged;
- errors reported in words;
- Excel through fake COM objects;
- through the API: F2, read back, download, another user refused, `edit_failed`;
- the tool's description.

`verify_all.sh --allow-blocked=live-parity,postgres` with `CI=true`: every layer passes (Python 447 passed and 5 skipped,
real Gemini CLI 4, portal-browser 9, web unit 55) except postgres and live-parity, BLOCKED as allowed. e2e cannot launch
this sandbox's Chromium build; the same 16 e2e tests passed on the installed Chromium. Real Excel is first exercised on
the work PC.

## 2026-10-23 (later) — Gemini reads ASAP, GSCM and the Big Data Portal live, in the person's own Wizard browser

The owner asked how to be sure Wizard reads the portals it says it reads: "I think it's not actually going in and
exploring tables." It was not. The ASAP, GSCM and NERP report tools read synthetic fixtures, or refused with
`navigation_only` over the real catalogs. BDP had no tool. The systems stage said "Reading ASAP" for a search of Wizard's
own catalog. The owner then asked for Wizard to "spawn its own little browser (use google chrome in user machine)",
explore and query the portals in the background, and prefer MicroStrategy and Nexacro queries over the screens, with
Metronome's knowledge "relayed to gemini to use for its own scripts". [Decision](decisions/2026-10-23-portal-browser.md).

**What changed.**
- `wizard_connectors/portals.py` (new): portal settings (`WIZARD_PORTAL_ASAP_URL`, `WIZARD_PORTAL_GSCM_URL`,
  `WIZARD_PORTAL_BDP_URL`, `WIZARD_BROWSER`, `WIZARD_PORTAL_HOSTS`) and the read-only rules: reachable hosts (the
  portals, their company domain, configured and learned sign-in hosts), write detection (path segments, task ids,
  action fields and Nexacro XML service names that start with a write verb; PUT/PATCH/DELETE except MicroStrategy prompt
  answers; SQL Lab one SELECT), Metronome's forbidden clicks, redaction, tables from script results.
- `portal_browser.py` (new): one browser per person on its own thread. It runs Playwright 1.62.0 with the installed
  Chrome or Edge and Wizard's own profile. It is headless for Gemini, with every request routed through the rules,
  WebSockets checked, downloads and service workers off, and confirmations answered No. A visible window opens for the
  person's sign-in and remembers the hosts that sign-in used. A sign-in page stops a read with `sign_in_required`.
- `portal_helpers.js` and `portal_capture.js` (new): the W helpers in every script.
  - Nexacro: component paths, active WorkFrames, the wait overlay, Grid → Dataset → rows, `gds_bookmark`.
  - MicroStrategy: the session, and the `menuInfo.do` menu walk. The token stays in the page.
  - The page's own data requests: kept in the page, replayed with new parameters, and their SSV, XML and JSON replies
    parsed.
  - Superset SQL Lab.
- `portal_guides/` (new): Metronome's knowledge of GSCM and ASAP and Superset's API, as guides Gemini reads, plus a
  general guide. Two background agents read `datap0nd/data_governance` (`flow_gscm.py`, `flow_worker.py`,
  `flow_replay.py` and the docs), and I checked their main claims against the source. Company host names and GSCM's
  backend route names are left out.
- Tools (`portal` MCP server, 24 tools with portals configured): `portal_guide`, `portal_run`, `portal_save_script`.
  Tables become `LIVE` / `BROWSER_SESSION` evidence with the steps as their query. `wizard_list_sources` lists the
  portals. Check my data does not repeat a portal read. The system prompt asks Gemini to name the system each number
  came from.
- API: `GET /api/v1/portals`, `POST /api/v1/portals/sign-in`, `.../sign-in/done`, `.../check`. Portals appear on the
  stage, and the local Owner has rights to them. Portal settings are refused behind SSO.
  `WIZARD_BROWSER_EXECUTABLE` (tests) cannot come from a company file.
- Web:
  - Settings → Portals, with **Sign in to the portals** and **Check sign-in**. The same button appears under a step
    that hit a sign-in page.
  - The evidence drawer shows the steps and scripts.
  - The stage tells the truth: "Searching the catalog of ASAP", "Reading GSCM in your browser", and "Cross-checked"
    counts only systems something was read from.
- Packaging:
  - Playwright, greenlet and pyee are added to `pyproject.toml`, `uv.lock` and the portable locks; nothing else in the
    locks changed. `pywin32` was kept: pip on Linux drops it because of its Windows marker.
  - `py3-none-win_amd64` wheels are allowed.
  - The desktop workflow publishes the portable runtime release when the locks name a new one, for `setup.ps1`.
- Docs: AGENTS.md (third exception, `BROWSER_SESSION`), README, `platforms.md`, `desktop.md`, `threat-model.md`,
  decision record; contracts regenerated.

**Tests.**
- `test_portals.py` (37): the rules, redaction and the API.
- `test_portal_browser.py` (9), in a real Chromium against a simulated portal:
  - a Nexacro Dataset as evidence;
  - bookmarks, tables and the page outline;
  - an SSV transaction replayed with a new week;
  - the ASAP menu walked with the token never reaching Gemini;
  - refused clicks, writes, other hosts and a confirmation;
  - a sign-in page;
  - partial results;
  - a saved script rerun with parameters.
- Its own layer, `portal-browser` (BLOCKED without a browser).
- Web unit: 53, including portal stage mapping, honest verbs and the badge.
- `verify_all.sh --allow-blocked=live-parity,postgres` with `CI=true`: lock, spec, secrets, contracts, lint, types,
  Python 440 passed and 5 skipped, real Gemini CLI 4, portal-browser 9, evals, web types, unit, dist and build all pass.
  postgres and live-parity are BLOCKED, as allowed.
- e2e could not launch here: this sandbox has Chromium build 1194 and the web app's Playwright wants 1243. The same 16
  e2e tests passed against the installed Chromium. Settings → Portals was checked in a browser.
- The real portals, Chrome on the work PC, and Application Control's view of the Playwright driver are first checked on
  the work PC.

## 2026-10-23 (later) — Recurring briefs: the analysis as a newsletter email; a Recurring tab synced with Metronome

The owner tested a recurring Flow: creating it in Metronome worked, but "the file received sucked". They want the same
analysis by email, with the charts, the data and what it says, "a little newsletter they decided to receive on a topic
on a weekly basis", and a **Recurring** section in the sidebar. Their calls: the words come from rules over each run's
rows, with no AI at send time ("A for now"); matplotlib is on the Metronome host ("already have"); the tab is synced
with Metronome, and Delete turns the Flow off there rather than deleting it.
[Decision](decisions/2026-10-23-recurring-briefs.md).

**What changed.**
- `wizard_connectors/brief.py` (new): the email renderer. It draws key-number tiles with their change, bar and line
  charts (drawn once as shapes, saved as SVG for the preview and PNG on Metronome), tables, and the "what moved"
  sentences from eleven rules (`change`, `largest`, `smallest`, `biggest_rise`, `biggest_fall`, `rose`, `fell`,
  `above`, `below`, `record_high`, `record_low`). The email is 600 px, built from tables and inline styles in Wizard's
  colours, with every value HTML-escaped. Standard library only, so the script can carry it.
- `wizard_schedule_brief` replaces `wizard_schedule_extraction` (still 21 tools). Up to eight sections, each with its
  own query. It test-runs every query as `LIVE` evidence, and it refuses columns a query does not return. The
  proposal keeps the test rows for the preview.
- `metronome.py`: the generated script carries the brief, its SHA-256 and a verbatim copy of `brief.py`. It runs every
  query in one read-only transaction and writes one Excel sheet per section. When Metronome names
  `METRONOME_FLOW_EMAIL_DIR`, it also writes `body.html` and the PNG charts there; without matplotlib the charts go in
  as tables. A proposal from before briefs becomes a one-table brief. `preview_html` draws the card's preview.
- `metronome_client.py`: `status` (Flow, next and last run, recent runs with their email) and `deactivate`
  (`PATCH /api/flows/{id}/enabled`, after the Wizard-user check; never Metronome's delete).
- API: `GET /api/v1/schedules/{id}/preview`, `GET /api/v1/recurring` (the person's created briefs, even after their
  conversation is deleted, with Metronome's state; still listed with a note when Metronome is down), and
  `POST /api/v1/recurring/{id}/delete` (the audit records `metronome:deactivate_flow`). A run carries row counts, not
  the test rows.
- Web: the card shows the email in a sandboxed frame (no scripts), loaded only when opened, and lists every query. A
  **Recurring** tab sits beside Analyses and Sources when Metronome is connected. It shows Sent / Off in Metronome /
  Last run failed / Not in Metronome. Its detail panel has the schedule, the recipients, recent runs, the email and
  **Delete** with a confirmation.
- Gemini: the system prompt and the Make recurring request now ask for a brief that mirrors the answer, with lead
  rules for what matters most and no "why".
- Metronome (`datap0nd/data_governance`, PR "Python Flows can write their own email body with inline images"): the last
  script row gets `METRONOME_FLOW_EMAIL_DIR`. The Email step sends `body.html` with its `cid:` images inline and the
  file attached, adds a footer, and falls back to the standard message, with the reason, when a body breaks a rule.
- Docs: AGENTS.md (second exception), GEMINI.md, README, `desktop.md`, `threat-model.md`, decision record; contracts
  regenerated.

**Tests.** `test_brief.py` (7): formats, every rule, chart geometry and valid SVG, escaping, sheet names, the
standard-library-only rule. `test_schedule_tool.py` (19): rights, 14 refusals before any query, the test runs as
evidence, missing columns named, the proposal. `test_metronome.py` (23): the script with fake psycopg2, openpyxl and
matplotlib (one read-only transaction, four queries, the sheets, the email and its charts, no matplotlib, an older
Metronome, the row cap, a changed brief refused, values only as literals), and Flow status and turning off against
the fake Metronome with its owner rule. `test_schedules_api.py` (7): the preview, the tab following Metronome, Delete
only as Wizard. Web (51): the card's preview and queries, the tab, Delete after confirming, Metronome down. With real
matplotlib 3.11.2 and openpyxl 3.1.5 in a scratch environment, the generated script wrote a four-sheet workbook and
two PNG charts, and Metronome's own `script_body` accepted the email.
`verify_all.sh --allow-blocked=live-parity,postgres`: every layer passes (Python 398 passed and 5 skipped, real Gemini
CLI 4, web unit 51) except postgres and live-parity, BLOCKED as allowed, and e2e, which could not launch Edge here; the
same 16 e2e tests passed on the installed Chromium.

## 2026-10-23 (later) — No "Gemini is busy" on the stage

The owner: "users dont need to see 'gemini is busy' message. they should just have wizard working through the data.
they dont need to see that nothing's happening because gemini's busy."

**What changed.**
- `code_assist.py`: when both models refuse and Wizard waits (5 to 30 s a round, up to 10 rounds), it no longer sends a
  status line ("Gemini is busy; trying again in 22 s (attempt 3 of 10)", or "Gemini's per-minute limit … waiting").
  The stage keeps the wizard at work on the step it is on. The wait goes to `wizard.log` (`run … waiting 22 s for
  Gemini (capacity for gemini-3.8-flash and gemini-3.1-pro-preview, round 3 of 10)`, after the `Gemini refused` line
  with Google's reason) and to a `model_wait` event the page does not show.
- `runs.py`: Error details of a failed answer adds "Waited for Gemini: 4 times, 1 min 52 s in all (both models busy or
  rate-limited)", so a slow or timed-out answer still says where its time went.
- Unchanged: a used-up quota that moves the answer to the other model is still said once ("Your Gemini quota for … is
  used up. Wizard continues with …"); it is not a wait. An answer that stops because Google never had room still says so.
- `contracts/run-event.schema.json`: `model_wait`. Docs: `desktop.md`, `operations.md`.

**Tests.** Python, Code Assist: a busy Gemini, a per-minute limit, no capacity with no other model, both models
refusing, and a used-up quota followed by a wait all run with no status line and no warning for the wait, and record
each wait (reason, seconds, models, round); the quota is still told. These six fail on the previous code. Python,
runs: Error details counts two waits as "2 times, 1 min 5 s in all". Web: a run waiting on Gemini shows no waiting
line on the stage and nothing about Gemini being busy; a quota status line still shows.
`verify_all.sh --allow-blocked=live-parity,postgres`: every layer passes (Python 375 passed and 5 skipped, real Gemini
CLI 4, web unit 46) except postgres and live-parity, BLOCKED as allowed, and e2e, which could not launch Edge here; the
same 16 e2e tests passed on the installed Chromium.

## 2026-10-23 — Error details on every failed answer; an empty Gemini turn is asked again; no more "session expired"

The owner reported two things. WizardBar said "Your session expired. Reload the page to sign in again", and the panel
has no reload button, so Wizard had to be restarted. And an answer ended with "Wizard could not finish this answer.
Gemini finished without an answer." ("This can't happen, we need a little 'error details' button where I see exactly
why").

**Causes found in the code.**
- The session cookie lasted 12 hours from sign-in and was never renewed. WizardBar keeps the page open for days, so
  every request after 12 hours got "Sign in to use Wizard", and the only advice was to reload.
- On the Code Assist route (the desktop's), a model turn with neither text nor a tool call ended the run as if Gemini
  had finished. Gemini 3 sends such turns (an empty text part carrying a thought signature) after a tool call, and for a
  tool call it wrote but Google could not read (`MALFORMED_FUNCTION_CALL`). Gemini CLI calls this an invalid stream and
  asks again; Wizard did not, and it never read Google's `finishReason`, so nothing could say why.
- With `WIZARD_DIAGNOSTICS=false` (the desktop default) a failed answer showed only its one-line message.

**What changed.**
- `app.py`: a session in use is signed again once it is an hour old (any API request, the quota ring's polling
  included), so an open Wizard stays signed in. It still lapses 12 hours after the page last reached Wizard; sign-out
  is never undone by a renewal, and a lapsed cookie is not revived.
- `api.ts`, `App.tsx`: when a request finds the session lapsed (a PC asleep overnight), the page signs in again as the
  same person (fixture sign-in, as the desktop app does at start) and sends the request once more, one renewal for
  every request waiting on it. A live answer whose stream was refused is followed again. Where the page cannot sign in
  by itself (company SSO), it shows sign-in instead of a dead-end message.
- `code_assist.py`: each turn keeps Google's `finishReason`, `finishMessage`, `promptFeedback.blockReason`, blocked
  safety categories and `modelVersion`. A turn with neither text nor a tool call is asked again, silently: the same
  model once more, then the other model twice (Flash ×2, Pro ×2). If every try is empty, the answer stops with Google's
  reason in words ("Gemini wrote a tool call that could not be read (MALFORMED_FUNCTION_CALL)"); if Gemini wrote a
  message earlier in the answer, that message is shown instead, with a warning, as before. A request Google blocked
  (`blockReason`) is not asked again. The old "Gemini returned neither text nor a tool call" failure is the same case.
- Every failure now carries details (`AgentFailure.details`): Google's reply to an HTTP error (`HTTP 400: The input
  token count … (INVALID_ARGUMENT)`), Google's refusal kind, message, suggested wait and the models and rounds tried,
  the network error, or the exception and the line it came from. `runs.py` adds where the run had got to: model,
  connection, time, tool calls, the last tool call and how it ended, the last status line, run id and build. They go
  out on the `run_failed` event (`contracts/run-event.schema.json`), redacted, never the prompt, the answer or
  reasoning.
- `RunCard.tsx`: **Error details** next to **Ask again** opens them, label by label (stacked in the narrow WizardBar
  panel, two columns in a full window), with **Copy details** (with the question). A run that failed before this
  change, or under a restart, shows what the card knows.
- Docs: `desktop.md` (empty turns, Error details, staying signed in, troubleshooting), `operations.md` (`empty_answer`,
  `model_blocked`), README.

**Tests.**
- Python, Code Assist: an empty turn is asked again on the same model with the same conversation and the answer
  continues, silently; empty turns on both models fail after Flash ×2 and Pro ×2 with Google's finish reason, message,
  parts, step, tries, tokens and model version; no finish reason says the stream was cut; a blocked request is not
  asked again; a 400 keeps Google's words; running out of capacity keeps Google's message and the rounds. The first
  fails on the previous code (the run stopped after the empty turn).
- Python, runs: a failed answer's `run_failed` event carries the runtime's details first, then model, connection, tool
  calls, last tool call, last status and run id, with an access token redacted; an empty last turn after a message
  shows that message; an internal error names the exception and the line.
- Python, sessions: a session over an hour old is signed again for 12 hours; a fresh one is not; sign-out stays
  signed out; a lapsed one stays lapsed (fails on the previous code).
- Web: Error details shows the server's details and copies them with the question; an older failed run shows what the
  card knows; a cancelled run has none. A lapsed session is renewed once for two requests at the same time and both are
  sent again; one that cannot be renewed shows sign-in; under SSO nothing is retried.
- In a browser (Chromium, the e2e server): with the page open, the session cookie was deleted and a question asked; it
  was answered with no message and the cookie was set again. Error details was screenshot at 460 px (the WizardBar
  panel) and 1280 px, inside its box with no overflow.
- `verify_all.sh --allow-blocked=live-parity,postgres`: lock, spec, secrets, contracts, lint, types, Python 375 passed
  and 5 skipped, evals, web types, web unit 45, web-dist and web build pass; postgres and live-parity BLOCKED, as
  allowed (no PostgreSQL test server here; CI runs one). The real Gemini CLI layer, BLOCKED on the first run because
  the CLI was not installed, passed (4) after `npm --prefix .tools install @google/gemini-cli@0.62.0`. The e2e layer
  could not launch Edge here; the same 16 tests passed on the installed Chromium (`executablePath` override, not
  committed).

## 2026-10-22 — Flash and Pro stand in for each other both ways; a missing view says where to look; no sleep mid-answer

The owner sent two photos of "Analyze S26 launch, create a full report on it" ("pretty much unusable"): 28 steps, and
before nearly every step "Gemini is busy; trying again in 5 s … 11 s … 22 s … 33 s" (about a minute each). Two
queries failed with `relation "bi_reporting.global_lc_v" does not exist` and `bi_reporting.mena_lc`, others returned 0
rows, and the run ended with "Wizard could not finish this answer" after 59 minutes, its last step at 22:45.

**What the photos show, and the causes found in the code.**
- The waits carry no "Google said", so Google refused for capacity. That message only shows on the last model: the run
  had left Flash for Pro (silently, after one refusal) and then waited on Pro at every step. Wizard never went back to
  Flash in that run, and kept new questions on Pro for ten minutes.
- Gemini asked for one tool per step, so each of the 28 steps paid the wait.
- The dataset notes name views that this account's database does not have, and PostgreSQL's error gave Gemini nothing to
  go on, so it guessed.
- Nothing happened between 23 and 59 minutes, not even a wait: most likely the PC went to sleep while idle (the answer
  ran unattended) and the run failed on waking. The failure's own text is not in the photos.

**What changed.**
- `code_assist.py`: the two models take over from each other in both directions. When the model a run is on refuses,
  it gets Gemini CLI's two quick tries (1 s, 3 s, for capacity; none when Google asks for a longer wait), then the other
  model takes the step and the run stays on it. So Pro hands back to Flash just as Flash hands over to Pro. Wizard waits ("Gemini is busy"), 5 to 30 s, only
  when both have refused. After each wait it tries both again, for up to 10 rounds, and then fails, naming both models.
  A model with a used-up quota is not gone back to until Google's reset. Capacity is no longer remembered between
  questions: every question starts on Flash, at a cost of at most two quick tries. Each step logs its model, prompt
  tokens and tool calls (`run … step N on …`), so the next slow answer shows where the time went.
- `prompts/system.md`: every step is a round trip that a busy Gemini can make wait, so Gemini should ask for independent
  notes and queries in the same step (Wizard already runs every call of a step) and prefer one query to many.
- `postgres_query.py`: "relation … does not exist" now comes back with up to five readable tables or views with a similar
  name in that database (the same name in another schema or with capitals first, quoted where SQL needs it), and up to
  12 other databases on the server that have one by that name ("Found bi_reporting.global_lc_v in database dwh: set
  database to query it."). Or it says that no relation has a similar name, so Gemini stops guessing. These are catalog
  reads in a READ ONLY transaction that is rolled back. Another database gets its own connection, closed after one
  lookup, and the search stops after 10 s. `pg.error_text` also passes on PostgreSQL's own hint ("Perhaps you meant to
  reference the column …").
- `awake.py`: while a question runs, Wizard asks Windows to keep the system awake (`SetThreadExecutionState`, as a
  download does). The screen still turns off, and the lid or Sleep still sleeps. Elsewhere than Windows this does nothing.
- Docs: `desktop.md` (refusals, the step log, sleep), `operations.md` (slow answers, missing views), README, and the
  desktop decision record.

**Not changed:** the dataset notes themselves (company content, outside this repository). The tool now names where each
view really is, so the notes can be corrected.

**Tests.**
- Python, Code Assist: a run on Pro goes back to Flash after Pro's two quick tries, silently, with no wait. Both models
  refusing gives one wait, then a try on each, and so on. Every round refused fails naming both. A quota-exhausted Flash
  is not gone back to. A long wait Google asks for goes to the other model at once. The next question starts on
  Flash. These fail on the previous code, except the quota one, which guards existing behaviour.
- Python, PostgreSQL: a missing view lists similar names and the database that has it, under a fresh read-only
  transaction, with every other connection rolled back and closed. A name with capitals comes back quoted. No match
  says so. PostgreSQL's hint is passed on. Against a real PostgreSQL 16: a similar view in the same database, and a
  second database holding the exact view, which the suggested `database` then reads.
- Python, sleep: awake while any question runs and released after the last one; a refusal or an error never stops a
  question. End to end, a replayed question takes the keep-awake when it starts and releases it when it ends.
- `verify_all.sh --allow-blocked=live-parity`, run as CI does (`CI=true`, a local PostgreSQL 16, Gemini CLI 0.62 in
  `.tools`): lock, spec, secrets, contracts (unchanged), lint, types, Python 364 passed and 5 skipped, real Gemini CLI 4,
  PostgreSQL 16 through pg8000 11, web types, web unit 39, web-dist and web build all pass; live-parity BLOCKED, as
  allowed. The e2e layer could not launch here: this Playwright wants a browser build that is not installed. The same
  16 tests passed on the installed Chromium (`executablePath` override, not committed).

## 2026-10-20 — Show sources lists real sources; no "Google has no capacity" on every question

**Show sources.** The owner asked that the button show the sources actually used, "a file, a postgres table or a name of
a report in one of these modules (like sell in biz plan GSCM)", not "Show sources (14)" for 14 queries on one table.
The queries should show only when a source is opened.
- Each evidence summary (the `tool_finished` event and the run's stored evidence) now carries the query's `sql` and the
  report's `folder_path` (`runs.evidence_summary`, one helper for both).
- `apps/web/src/sources.ts` groups evidence into sources. A query counts under each table or view its SQL reads (the
  email's existing parser, moved here). A report is its system, module and name (GSCM › Biz Plan · Sell in). An
  attached file is one source whichever sheet was read. Lookups in `information_schema` or `pg_catalog` are listed last
  as "Table and column definitions" and not counted.
- The button reads "Show sources (2)": one table and one report. The drawer shows one card per source, with its system
  and module, data mode, newest as-of and how often it was read ("14 queries"). A card opens to one line per query (id, what
  sets it apart from the others, e.g. `… week_start = date '2026-07-01' …`, and rows; the whole SQL on hover). A line
  opens to the full SQL, rows and freshness, loaded only then. A citation chip
  opens the drawer on its source and query.
- The report page's "Sources consulted" and the email's source list use the same grouping. The email now names a
  report's module.

**"No capacity" notices.** The owner: "I don't want the user to see 'google has no capacity' message constantly".
Cause: every capacity refusal on Flash added a status line (two quick tries, then the switch to Pro). For ten minutes
after a switch, every new question also opened with "Google has no capacity for gemini-3.8-flash… Wizard answers with
gemini-3.1-pro-preview". In `code_assist.py`, as in Gemini CLI's default (errorVerbosity low):
- The quick tries and the switch to the fallback show nothing. Each refusal and the switch are still in
  `wizard.log`. The run still records the model that answered.
- New questions that start on the fallback because of capacity show nothing. A used-up quota still says so: that
  is the person's own limit, and it lasts hours.
- Waiting on the last model (Pro without capacity, or no fallback) shows "Gemini is busy; trying again in 10 s (attempt
  2 of 10)", without Google's capacity wording.
- Unchanged: if all 10 tries fail, the answer stops with "Google has no capacity for … This is on Google's side, not
  your quota", quoting Google.

**Tests.**
- Python: the Flash to Pro hand-over emits no status and no warning, and neither does the next question. A
  used-up quota still explains the switch and the next question's start on Pro. Waiting on the last model shows only
  "Gemini is busy". The evidence summary carries `sql` and `folder_path`, and so do the API's events and the restored
  run.
- Web:
  - `sourceGroups`: 14 queries on one table, a report with its module, a file read twice, joins, catalog lookups, full
    evidence. `distinctLines`: shared SQL openings are cut, keeping three words before the difference.
  - The drawer: two cards, opening to 14 query lines and then to the SQL; a citation opens its source.
  - The button reads "Show sources (2)", and the email names the module.
- E2E: the email test expects the module (`NERP › Marketing`). The compact-view test no longer waits for the host to
  get the "read" animation. In replay a report tool returns in about 3 ms, the same on `main` and this branch, and a
  browser did not always render a frame in between (main 16 of 20 runs, this branch 13 of 20, measured side by side).
  It now checks "think" and "write", which last long enough to see every time; the tool-to-animation mapping stays
  unit-tested. After that, 5 full runs without retries passed 16 of 16 each (Chromium; locally `msedge` is not
  installed, so `verify_all`'s e2e layer cannot launch here).

## 2026-10-20 — `uv.lock` back in step with `pyproject.toml`; a stale lock now fails CI

`uv lock --check` failed: `uv.lock` had not been updated since `truststore`, so it lacked pywin32 (added for Office
automation) and pg8000 (the driver behind `wizard_query_postgresql` and the catalog export), with pg8000's
dependencies scramp, asn1crypto, python-dateutil and six. CI's `uv sync --frozen` installs the lock as written without
comparing it to `pyproject.toml`, so CI started without pg8000. It stayed green only because `verify_all.sh` runs
`uv run`, which re-locks and installs silently on the runner.

- `uv lock` added exactly those six packages: pg8000 1.31.5, scramp 1.4.17, asn1crypto 1.5.1, python-dateutil
  2.9.0.post0, six 1.17.0 and pywin32 312 (marker `sys_platform == 'win32'`). No other pin moved.
- The desktop locks did not need regenerating. `dependencies.lock.json` is resolved by `lock_portable.py` from
  `pyproject.toml`, not from `uv.lock`, and already pinned all six packages. Each of its 24 wheels has the same file
  and SHA-256 as in `uv.lock`. `uv.lock` is not part of the desktop payload.
- CI installs with `uv sync --locked`, which refuses a lock that is out of date with `pyproject.toml`.
- `verify_all.sh` has a new first layer, `lock` (`uv lock --check`). It runs before any `uv run` can re-lock the
  file. Without uv the layer reports BLOCKED.
- `docs/deployment.md` builds with `uv sync --locked`. README and test plan list the new check.

**Results.**
- Before the fix, with the old lock: `uv sync --frozen` then `import pg8000` raised `ModuleNotFoundError`, and
  `uv sync --locked` refused the lock.
- After it: `uv lock --check` and `uv sync --locked` pass. Under `uv sync --frozen`,
  `uv run --frozen python -m pytest tests` gives 354 passed, 20 skipped.
- `verify_all.sh --allow-blocked=live-parity`, run as CI does (`CI=true`, a local PostgreSQL 16, Gemini CLI 0.62 in
  `.tools`):
  - lock, spec, secrets, contracts, lint and types: pass;
  - Python: 354 passed, 5 skipped;
  - real Gemini CLI: 4 passed;
  - PostgreSQL 16 through pg8000: 10 passed;
  - web unit: 32 passed; web types, web-dist and web build: pass;
  - browser E2E: 16 passed;
  - live-parity: BLOCKED, as allowed.

## 2026-10-20 (Metronome) — Recurring extractions in Metronome, owned by its Wizard user; Metronome and Orchestra logos

The owner asked for Metronome as a module: at the end of an answer, or in the question, a person can make an extraction
recurring, and a Metronome Flow emails the table on that schedule. Every Flow belongs to a Metronome user named
**Wizard**, which the owner creates. Only Wizard changes.

Then, with as few questions as possible: always Excel, to the person's own address (their sign-in email without the
`ax.` after the @: `name@ax.company.com` sends to `name@company.com`), at 08:00 Dubai time unless they say otherwise.
**Make recurring** is a menu (every day, every Monday, the 1st of every month, something else), so a usual schedule needs
no question at all; otherwise Gemini asks only how often.
[Decision](decisions/2026-10-20-metronome-recurring-extractions.md); AGENTS.md lists it as the second owner exception.

**How it works.**
- **Starting it.** **Make recurring** appears under a finished answer that queried the database, when Metronome is
  connected. Its choice starts a follow-up run (`kind: recurring`, "Make this recurring: every Monday") whose request
  tells Gemini to call the tool without asking; "Something else…" lets Gemini ask how often. Saying it in a question
  works the same way.
- **The tool.** `wizard_schedule_extraction` (`category: present`; Wizard declares 21 tools) checks:
  - the PostgreSQL right;
  - one statement (`postgres_query.one_statement`, sharing the scanner of `without_terminator`);
  - the recipients: by default the requester's own mailbox; at most 20, in `WIZARD_GOOGLE_DOMAINS` (each also
    without `ax.`), else the requester's own mailbox domain;
  - the schedule: daily, weekly on given days, or monthly on a day, at 08:00 or a given time on Metronome's Dubai clock.

  It then test-runs the query read-only (`LIVE` evidence) and stores a proposal `R1`, `R2`, …. The answer shows it as
  a card: when, to whom, the file, the owner (Metronome user Wizard), the query and the test run.
- **The click.** **Create in Metronome** (`POST /api/v1/schedules/{id}/create`) is the only path to Metronome
  (`wizard_api/metronome_client.py`, reached directly on the office network):
  1. `GET /api/me` with Wizard's key must name the Wizard user;
  2. the generated script is uploaded (`POST /api/flows/transform-script?target=python`);
  3. `POST /api/flows` creates an active Python-script Flow ("Produce a file"): an Excel file, the email step with the
     recipients, the schedule, and `owner_person_id` set to the Wizard user.

  The proposal moves to `creating` first, so a second click creates nothing. A refusal can be tried again. A
  timeout or 5xx becomes `uncertain` and is never resent. The click is audited (`metronome:create_flow`).
- **The script** (`wizard_connectors/metronome.py`) runs on Metronome's worker with Metronome's own Python. It holds
  the query and its SHA-256 and runs it as a subquery in a READ ONLY session and transaction that is rolled back. It
  writes at most 100,000 rows. It uses `WIZARD_EXTRACT_PG*` or Metronome's `PG*` scanner account, never `DG_UPLOAD_PG*`.
- **Linking.** Metronome has no API tokens: a caller is the person its `X-Client-Key` is signed in as.
  `scripts/metronome_link.py` (standard library only) runs once on the Metronome host PC. It makes a key, signs it in
  as Wizard and prints it.
- **Settings.** `WIZARD_METRONOME_URL`, `WIZARD_METRONOME_CLIENT_KEY` (DPAPI), `WIZARD_METRONOME_USER` (default
  `Wizard`). They are in the provisioning file and in Settings → Metronome, which has **Test connection**.
- **Logos.** The systems stage shows Metronome, with Metronome's own metronome logo in its teal, while Gemini prepares
  a schedule. Orchestra, a platform documented in the knowledge base, gets its blue-violet sound-wave tile, by id or by
  name.

**Tests.**
- `tests/unit/test_metronome.py`, against a fake Metronome with its real ownership and sign-in rules:
  - settings;
  - the mailbox rule (`name@ax.company.com` → `name@company.com`), recipient and schedule rules;
  - the Flow definition;
  - the client: created as Wizard; a key signed in as nobody, or as someone else, creates nothing; timeout and 5xx are
    uncertain, 409 is not;
  - the generated script run as Metronome runs it, with fake psycopg2 and openpyxl: a read-only session, the Excel
    file, the row cap, a changed query and a missing account refused, the dedicated account preferred over the
    scanner and never the uploader;
  - the link script against a local HTTP server.
- `tests/unit/test_schedule_tool.py`: rights, refusals before any query, domains, evidence and the proposal; by
  default the person's own mailbox at 08:00, in Excel.
- `tests/integration/test_schedules_api.py`:
  - a scripted model proposes a schedule, and the card streams;
  - the click creates one Flow as Wizard;
  - retry, uncertain and dismiss;
  - another user gets 404;
  - Make recurring: a menu choice reaches Gemini as "call the tool now, without asking"; "Something else…" asks only
    how often;
  - Settings' Test connection.
- Web: the card's states, the menu and when it shows, the stage and both logos.

**Results.** `verify_all.sh --allow-blocked=live-parity`, run as CI does (`CI=1`, a local PostgreSQL 16, Gemini
CLI 0.62 in `.tools`):
- spec, secrets, contracts, lint and types: pass;
- Python: 351 passed, 5 skipped;
- real Gemini CLI: 4 passed, including the CLI accepting every tool's schema (its pinned tool count is now 21);
- PostgreSQL 16: 10 passed;
- web unit: 32 passed; web types, web-dist and web build: pass;
- browser E2E: 16 passed;
- live-parity: BLOCKED, as allowed (it needs live sources).

`tool-catalog.json`, `openapi.json` and `run-event.schema.json` (`schedule_proposed`) were regenerated and reviewed.

**Not yet run against the real Metronome.** The first real use is on the work PC, after the owner creates the Wizard
user and runs `metronome_link.py`.

## 2026-10-20 (night) — Flash falls back to Gemini 3.1 Pro preview, as in Gemini CLI

The owner asked for "the exact same experience as Gemini CLI": when Flash has no capacity, fall back to Pro, Gemini 3.1
Pro preview. Read in Gemini CLI 0.62.0:
- `retry.ts`: two quick tries (1 s, 3 s), then the fallback handler.
- `policyHelpers.ts`: Gemini 3 chains wrap around, so Flash falls back to Pro.
- `useQuotaAndFallback.ts`: with the default `errorVerbosity: low`, it switches without a dialog or an error.

**What changed:**
- `WIZARD_GEMINI_FALLBACK_MODEL` defaults to `gemini-3.1-pro-preview` (was the model itself, `gemini-3.8-flash`). So a
  capacity refusal on Flash gets two quick tries, then the rest of the answer comes from Pro. For ten minutes new
  questions start on Pro. A used-up Flash quota also goes straight to Pro.
- The switch is a status line on the stage, not a warning in the answer, as the CLI shows no error. The answer's report
  still names the model that answered.
- Unchanged from the entry below: if Pro has no capacity either, Wizard waits on it (10 tries, about 4 minutes) before
  failing. Here Wizard is more patient than the CLI, which goes back to Flash once and then stops.
- `desktop.md`, `operations.md`, the decision record and the README name the fallback.

**Tests.** The hand-over test now uses the default settings: Flash to `gemini-3.1-pro-preview` after 1 s and 3 s, a
status line and no warning, thinking HIGH on Pro, and the next question starting on Pro. The settings test expects the
new default. Both fail on the previous code.

## 2026-10-20 (earlier) — "No capacity" no longer stops every answer: Wizard waits it out

The owner reported that Wizard "just stops with the Gemini capacity error constantly". Cause: the change below left
the fallback model equal to the model (both `gemini-3.8-flash`), so there was nowhere to go. A capacity refusal got the
two quick tries meant for switching models (1 s, 3 s), then the answer failed about 4 seconds after Google's first
refusal. Before the fallback change the same refusal was retried for about a minute and a half.

The two quick tries come from Gemini CLI, which follows them with a switch of model, not a wait. Gemini 3 chains wrap
around, so Flash without capacity falls back to Pro (`policyHelpers.ts`): silently on the auto model, otherwise after
asking. Wizard has one model, so it waits instead, as it did before the fallback (then 6 tries over about 90 s).

**What changed** (`wizard_agent/code_assist.py`):
- Two quick tries, then the switch, only when a different fallback model is set. Otherwise (the default, and on the
  fallback itself) a capacity refusal is waited for like a busy server: Google's suggested delay or 5, 10, 20, 30 s
  backoff. The stage shows each wait ("Google has no capacity for … trying again in 10 s (attempt 2 of 10)").
- Up to 10 attempts per step (was 6), Gemini CLI's default, about 4 minutes in all. No wait after the last attempt.
- Failure messages no longer point to the removed model chip (Code Assist and Gemini CLI runtimes). A capacity failure
  says Wizard already kept trying; a used-up quota says to try again once it resets.
- `docs/desktop.md` and `docs/operations.md` describe the waits.

**Tests.** 4 new tests replace 1:
- No capacity with no other model, or no fallback at all, is waited out with 5, 10, 20 s backoff, then answers.
- No capacity through all 10 attempts fails with `model_capacity` naming Google's side, after 9 waits.
- A fallback model without capacity is waited for, after the chosen model's two quick tries.
- The quota failure no longer mentions the model chip.

The new tests fail on the previous code. Python 317 passed, 20 skipped.

## 2026-10-20 (noon) — No model picker: Gemini 3.8 Flash for everyone

The owner asked to remove the model picker again and default to Gemini 3.8 Flash.
- **Removed:**
  - the model chip in the panel's header and the full app's top bar (`ModelPicker.tsx`);
  - the Model and Fallback model fields in Settings;
  - `/api/v1/models`.
- **Ignored:** a model or fallback saved with the picker in a PC's own settings (`data\settings`), so PCs that chose
  Pro are back on `gemini-3.8-flash` after the update.
- **Still possible:** the company file, `.env` or the environment can set `WIZARD_GEMINI_MODEL` and
  `WIZARD_GEMINI_FALLBACK_MODEL`.
- **Refusals:** Google's refusals are still read as below. With the default fallback being the same model, a capacity
  problem ends the answer with Google's reason instead of switching.

**Tests.** A new settings test saves Pro and "none" in this PC's layer the way the picker did. The PC then runs on
`gemini-3.8-flash` with the default fallback, Settings offers no model fields and refuses them, `/api/v1/models` is
gone, and the environment can still set a model. Python 314 passed, web 27 passed, `openapi.json` regenerated.

## 2026-10-20 (late evening) — "Gemini is at capacity": telling Google's refusals apart, and a fallback model

The owner reported many "Gemini is at capacity" lines. Wizard showed that text for every HTTP 429 from Google and
retried the same model up to six times, for minutes. Google's 429s mean different things, and only one of them is
worth waiting for.

**What changed** (`wizard_agent/code_assist.py`, after Gemini CLI's `googleQuotaErrors.ts` and `retry.ts`):
- `classify_limit` reads Google's error details (ErrorInfo reason, QuotaFailure ids, RetryInfo delay, the message):
  - **capacity:** `MODEL_CAPACITY_EXHAUSTED`, "no capacity available". Google has no room for the model; it is not the
    person's quota. Two quick tries (1 s, 3 s), as Gemini CLI does, then the model is left.
  - **quota:** `QUOTA_EXHAUSTED`, a per-day quota, "limit: 0", or a suggested wait over 5 minutes. No waiting.
  - **rate:** `RATE_LIMIT_EXCEEDED` or a per-minute quota. Wizard asks Gemini once per step, so a long answer can reach
    it. Wizard waits at least as long as Google asks (60 s for a per-minute quota without a hint).
  - **busy:** anything else, and 5xx. Retried with 5–30 s backoff.
- **Fallback model** (`WIZARD_GEMINI_FALLBACK_MODEL`, in Settings, default `gemini-3.8-flash`, `none` turns it off):
  - When the run's model has no capacity, no quota, or keeps refusing, the rest of the answer continues on it.
  - A warning says so in plain words, and the run's model (report, history) becomes the one that answered.
  - Earlier turns' thought signatures get Google's documented placeholder, so the new model accepts them.
  - New questions start on the fallback for 10 minutes after a capacity problem, or until the quota resets, and say so.
- Without a fallback the failure says whose side it is: `model_capacity` ("on Google's side, not your quota") or the
  new `model_quota` (with the reset time).
- Each refusal is logged with Google's reason (`wizard.gemini` in `wizard.log`). The first wait, the switch and the
  failure also quote Google's own words (`Google said: "..."`), so the real reason is on screen.
- The stage shows the wait or the switch instead of "Gemini is deciding the next step".
- The Gemini CLI runtime's error text now tells capacity, quota and rate limits apart too.

**Tests.** 16 new Python tests:
- Google's refusal bodies classified as Gemini CLI does: capacity, daily, quota exhausted, rate with and without a
  delay, "limit: 0", a list-wrapped body, 503 and 500.
- Pro handing over to Flash after two quick tries, with the warning, the recorded model, the signature placeholder and
  the next question starting on Flash.
- A used-up quota is not waited for.
- A per-minute limit waits as long as Google asks.
- No capacity without a fallback names Google's side.
- The fallback setting is saved, applied live and validated.

One new web test: the stage shows the wait. Python 317 passed, web 27, plus spec, contracts, secrets, lint and types.
Google's real refusals are not reproducible here; the cases follow Gemini CLI's own tests and Google's error format.

## 2026-10-20 (evening) — The pixel wizard everywhere, a bigger stage, an animated button, files dropped on it

The owner asked for:
- a bigger, more animated stage;
- a file dropped on the **Ask Wizard** button attached to the conversation;
- a button animated on hover and on a click, and a panel that opens with more animation;
- "the wizard pixel character we had recently" as the logo everywhere.

**What changed.**
- **The character** is commit `8eb22fc` (branch `claude/fervent-maxwell-wwwa07`), brought in whole: `scripts/wizard_art.py`,
  `brand/`, the sprite and the logos.
  - The web app: the hat mark in the sidebar, the panel header, the answer cards, Wizard's own module and the favicon.
    The logo and the resting wizard on sign-in. The waving wizard on the start screens, the panel's included, where he
    waves each time the panel opens.
  - Its own sticky strip on a running answer was dropped: the wizard now stands in the stage.
- **The desktop icon** (tray, taskbar, Start menu, setup) is drawn by the same script into `apps/desktop/assets/wizard.ico`:
  the hat at 16 px, his portrait at 32 and 64, the whole wizard from 48 up. The script also writes the bar's copy of the
  sheet and `SpriteSheet.g.cs`, and `--check` (a unit test) covers them.
- **The stage** (`SystemsStage.tsx`) is bigger:
  - The pixel wizard (3x on a wide card, 2x in the panel) stands in a magic circle with turning rune rings and a glowing
    floor. The systems sit around him in two arcs, an orbit, on 58 px tiles. A narrow panel puts them in rows that
    fit its width.
  - He acts out the step in progress, and keeps acting out a fast step while its system stays lit.
  - Beams bend like a vortex and carry pixel "data bits". A finished call floats its result up from the wizard
    ("+ 4 rows · as of 2026-10-01"). An active tile hops, glows and pings. Pixel stars twinkle while he works.
  - When the answer lands live he hops with pixel confetti in the colours of the systems used (fizzles on failure).
    The stage folds into the journey strip 2.4 s later.
  - While the view follows a long answer down, a slim bar pinned to the top shows him writing, the systems used, and
    the landing hop. It appears only while the stage is out of view and takes no room.
  - Reduced motion still stops all of it.
- **The button** (`TopButton.cs`) is a light tab with the wizard in it, drawn from the embedded sprite sheet at a whole
  scale (1x, 2x from 175 %):
  - At rest he twinkles his staff every 9 s.
  - On hover the tab eases down, glows blue, shows "Click, Ctrl+Alt+W, or drop a file", and he waves. A click makes him
    cast.
  - While a question runs he acts out what the page shows (the page sends `activity`), and a glint runs along the
    bottom edge.
  - He hops and a green dot pulses when an answer is ready; he fizzles when the service stopped.
  - It redraws only when the picture changes, at 16–250 ms depending on what moves.
- **The panel** slides down from under the tab (230 ms, ease-out). The page unrolls downwards on the host's `focus`
  message, with a glint along the header.
- **Dropping files:**
  - Up to five files on the tab, from Explorer, or Outlook attachments and messages (saved under `dropped\`, kept a day).
  - Or on the panel's page: WebView2 hands the host the paths. In a plain browser the page uploads them instead.
  - WizardBar grants exactly those paths through `POST /internal/v1/desktop/drop` (control token, loopback). The page
    then attaches each one once, within ten minutes, through From this PC, so protected files still open from their
    place.
  - A full-window "Drop to attach" target with the wizard reading shows while a file is dragged over the page.
  - See the [decision addendum](decisions/2026-10-20-desktop-app.md).
- **Setup's pages** show the pixel wizard too (`installer/wizard-large.bmp`, `wizard-small.bmp`, drawn by the script).
- **CI** draws every look of the button on Windows (`WizardBar.exe --snapshot`), fails if the sprite is missing,
  uploads the PNGs and prints the 100 % one at the end of the log.

**Tests.**
- Python: 299 passed, 5 skipped. A new desktop test drops a CSV from a folder outside the attachment folders, a PDF
  and a missing file: only WizardBar can grant, errors come back per file, and a grant allows one attach.
- Web unit tests: 26 passed. New: the wizard in the stage reads, draws a chart, writes, hops and folds; a stored run has
  no finale; the orbit keeps every module clear of the circle and of each other.
- Browser tests: 16 passed with the sandbox's Chromium. The compact test now also checks the `activity` message, a drop
  on the page going to the host with the file, and a refused file from the host showing on the composer.
- Also passing: the spec, contracts (`openapi.json` regenerated for the drop endpoint), secrets, lint and types.
  `wizard_art --check` passes and WizardBar builds with warnings as errors.
- Screenshots of a slowed replay show the orbit, the beams and data bits, the floating result, the pinned bar while
  writing, the landing confetti, the panel's waving start and the drop target.
- The button's eight looks, drawn by GDI+ on the Windows runner and read back from the CI log at 100 %: rest, hover
  (glow, second line), click (cast), a file over it (dashed outline), starting, working (glint), answered, stopped, on
  light and dark title bars. That check moved the "answer waiting" dot from the staff's orb to after the caption.
- Not yet seen on a real desktop: the button's animation over time, the slide, and drops from Explorer and Outlook.
  Outlook's virtual files use the standard FileGroupDescriptorW/FileContents formats (stream, memory, or a structured
  storage saved as `.msg`) and are untested until a work PC.

## 2026-10-20 (late) — The knowledge base on the company's GitHub Enterprise Server

The owner reported that Wizard could not reach the knowledge base. It called public GitHub (`api.github.com`), but the
repository is on the company's GitHub Enterprise Server, `https://github.sec.samsung.net`.

**What changed (owner decision, 20 October 2026: built in, not changeable).**
- **One fixed server.** `wizard_connectors/github.py` holds `https://github.sec.samsung.net/api/v3`. No setting,
  provisioning file or `.env` value changes it.
- **Everything that talks to the repository uses it:** the desktop sync, Settings → Knowledge base → Test connection,
  `docs.ps1 kb-publish` and `docs.ps1 kb-check`. The publish's commit link points to the same server.
- **Visible:** the sync status reports the server, and `run.py --check` names it in the knowledge-base line.
- **No mix-ups:** a snapshot synced before the server was fixed (its state has no server recorded) is not used; the
  first sync from the company's server replaces it.
- **Unchanged:** the app's own updates still come from the public release on github.com.

**Tests.** Python suite 296 passed, including a new test that every sync request goes to the company's server
whatever the environment says, and that an older snapshot is not used. The publish and Settings tests now also check the
server. Web unit tests and the 16 browser tests pass. The spec, contracts, secrets, lint and types checks pass. The
Gemini CLI layer is BLOCKED in this sandbox (the CLI is not installed); PostgreSQL and live parity are BLOCKED as usual.
Not yet tried against the real server: the first sync on a work PC confirms it.

## 2026-10-20 (afternoon) — The systems stage: a visual view of what Wizard pulls from each system

The owner asked for a more visual, interactive and gamified view of a run. Each system should have its own logo and
light up while Wizard checks data there, showing what it is searching. The PostgreSQL database should appear as
"AI Team Database", and the knowledge base should be a module of its own.

**What was added.**
- **The stage** (`SystemsStage.tsx`, `stage.ts`, `SystemLogo.tsx`) at the top of every answer:
  - The Wizard orb sits in the centre, with each system this person can use around it as a module with its own mark
    and colour. Bootstrap's new `systems` list provides them: the report platforms, the AI Team Database, the
    knowledge base, and attached files once used. A platform without a mark, such as BDP, gets a monogram.
  - While Gemini reads from a system, its module pulses and an SVG beam streams particles into the orb.
  - The caption names the system and the call, shows the actual SQL when there is one, then the result
    ("→ 4 rows · as of 2026-10-01").
  - Gemini's latest interim note shows below, and "Gemini is deciding the next step" shows between calls.
  - A module stays lit for 2.2 s after a call, because most tools finish in milliseconds. A long query stays lit while
    it runs. Stored runs never linger.
  - Interactive: clicking a module lists its calls with the arguments, results, durations and evidence links.
  - Counters (systems used, calls, rows, notes) count up.
  - Badges only state facts about the finished run: cross-checked N systems, data + definitions, a deep dive of
    1,000+ rows, checked.
  - When the answer is done, the stage folds into a strip of the systems used, with their counts and badges, and
    "Show the journey" opens it again.
  - Narrow cards place the modules in a row under the orb. Reduced motion stops the animations and the particles.
  - Only observed tool calls drive it (AGENTS.md: never invent steps). The step-by-step list stays below, folded.
- **AI Team Database:** `WIZARD_PG_NAME` (default "AI Team Database", also in Settings) names PostgreSQL in the app,
  the sources list and the evidence. Tool labels read "Queried the AI Team Database". SQL and attachment queries now
  have proper labels and row-count summaries.

**Tests.** Python suite 295 passed. Web unit tests: 20 passed, including the stage logic and a render of an active
module with its SQL. The browser tests (16, with the sandbox's Chromium) now also unfold the journey and open NERP's
calls. The spec, contracts, secrets, lint and types checks pass. Screenshots of a slowed replay show modules lighting
and streaming in the full app and in the 720 px desktop panel.

## 2026-10-20 (later) — Settings in the app, a model picker, an Update button, publishing the knowledge base

The owner asked for:
- the credentials editable in a settings pane;
- a model picker, to use Gemini 3.1 Pro as well as 3.8 Flash;
- an Update button that gets the latest release;
- a way for Gemini 3.8 Flash on the work PC to create the knowledge-base repository properly.

See the [decision addendum](decisions/2026-10-20-desktop-app.md) and the [owner guide](desktop.md).

**What was added.**
- **Settings pane** (`wizard_api/settings_pane.py`, `SettingsDialog.tsx`):
  - Fields: Gemini (model, project, company domains), the knowledge base (repository, read-only token, branch, folder,
    interval), the company database (server, port, database, read-only user, password, SSL) and the proxy.
  - Each field shows its source: company file, this PC, `.env`, environment (locked) or default.
  - Values go to a new "this PC" store (`data\settings`, DPAPI for secrets), between the company file and `.env`.
    Saving a key `.env` had moves it out of `.env`.
  - Secrets are write-only.
  - Every save is validated by loading the settings again, and rolled back on error.
  - **Test connection** for the knowledge base (one GitHub request with the proposed token) and the database (a
    read-only session reporting the user).
  - Changes other than the model restart the desktop service by itself, after a running question.
  - Only the local Owner on their own install sees it: ⚙ in the panel, Settings in the sidebar, **Settings…** in the
    tray.
- **Model picker:** a chip in the panel header and the full app's top bar.
  - The list is the models in the person's own Gemini quota answer (`/api/v1/models`). Any id can be typed in Settings.
  - The model switches without a restart. Code Assist keeps one model per run.
- **Update button:** Settings → Version and updates.
  - `/api/v1/updates` reads the public release manifest and compares it with the installer's `BUILD.json` version
    (CI now stamps it).
  - **Update to 1.0.N** asks WizardBar to download, verify and install the release, as from the tray.
  - In a browser it offers the download link.
- **Publishing the knowledge base** (`wizard_documents/kb.py`, `.\docs.ps1 kb-publish`, `kb-check`, `provision`; work-PC
  task 50):
  - One commit through GitHub's Git Data API, because the work PC has no git.
  - Only `knowledge/**/*.md`, `contracts/sources/*.json` and a README the first time are published.
  - It validates first, refuses a public repository, uploads only changed blobs (same git blob ids), deletes notes
    deleted locally, keeps other files, and offers a dry run.
  - Its settings (`WIZARD_KB_PUBLISH_REPO`, `WIZARD_KB_PUBLISH_TOKEN`, `WIZARD_KB_READ_TOKEN`) are names the app never
    reads, so they cannot break the work PC's own install, and provisioning refuses them.
  - Task 50 walks Gemini CLI and the user through the steps: check the notes for errors and for anything that must not
    reach every PC, create the repository and two tokens in the browser, dry run, publish after a yes, check the users'
    token, then the Settings pane or a provisioning file. Gemini never sees a token: `private\` is in `.geminiignore`.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres,gemini-cli` in a Linux sandbox:
- PASS: spec, secrets, contracts (four new endpoints), lint, types, python-tests (292 passed), evals-schema, web-types,
  web-unit (14), web-dist and web-build.
- BLOCKED: gemini-cli, postgres and live-parity.
- e2e: the layer FAILs here because the local configuration launches Microsoft Edge, which the sandbox lacks. With the
  sandbox's Chromium, all 16 browser tests pass.
- New: `tests/unit/test_settings_pane.py` (25 tests) and `tests/unit/test_kb_publish.py` (9 tests, against a fake GitHub
  that keeps a real tree).
- The settings pane and the model picker were also driven in a browser against a throwaway install. The update check
  read the real release manifest (1.0.4.0).
- WizardBar compiles with warnings as errors. Its new message handling runs on Windows only and is untested.

## 2026-10-20 — Desktop app: always-on button, knowledge base from a private GitHub repository

The owner wants Wizard always on: a button at the top of the screen that opens a prompt box. The knowledge base lives
in a private enterprise GitHub repository that only the owner sees, each person signs in to Gemini with their own
account, and a read-only PostgreSQL account and other company settings are stored in the app. The owner pointed to
Scribble's installer as the model. See the [decision](decisions/2026-10-20-desktop-app.md) and the
[owner guide](desktop.md).

**What was added.**
- **WizardBar** (`apps/desktop/WizardBar`, C# .NET Framework 4.8, WebView2 1.0.2903.40 as in Scribble):
  - a per-pixel-alpha tab hanging from the top edge of the main screen; it never takes the focus, steps aside for
    full-screen apps and slide shows, can be dragged, and shows starting, working, answered and stopped states;
  - a borderless, resizable panel with `/quick`; only Wizard's own local pages load inside, other links open in the
    browser, and Esc hides it;
  - the tray menu, Ctrl+Alt+W, and a balloon when an answer arrives while hidden;
  - supervision of `run.py --desktop`: restart on exit code 75, a back-off after crashes, a health watchdog, and
    leftover-process clean-up;
  - an updater from the `desktop-continuous` release that checks size, SHA-256 and version, and never downgrades.
- **Installer and CI.**
  - `installer/Wizard.iss` installs per user, with no admin rights, and picks up `wizard.provision` placed next to it.
  - `scripts/build_desktop_payload.py` assembles the app code, the embeddable Python and the vendored wheels, from the
    same SHA-256-locked archives `setup.ps1` uses.
  - `.github/workflows/desktop.yml` (Windows) builds the bar and the payload, starts the packaged service, checks
    `/quick` and the control API, builds `WizardSetup.exe`, installs it silently, runs `--check` and uninstalls it.
    On `main` it publishes to `desktop-continuous`, and never over a newer build.
- **Service.**
  - `run.py --desktop` (`wizard_api/desktop.py`):
    - adds missing `.env` defaults: code-assist, port 8771, diagnostics off;
    - imports the provisioning file and syncs the knowledge base before serving;
    - logs to `%LOCALAPPDATA%\Wizard\logs`, beside WizardBar's own log;
    - signs in the local Owner only.
  - `/internal/v1/desktop/{status,sync,stop}` need a per-launch token on loopback.
  - `wizard_api/knowledge_sync.py` handles the private repository: a conditional commit check, the zipball,
    path-checked unpacking, the same validation as `WIZARD_CONTENT_DIR`, an atomic switch, the previous version kept,
    and errors explained.
  - Background sync runs every 30 minutes, with a restart onto a new version after 10 idle minutes. With a knowledge
    base configured, the synthetic catalog and demonstration questions are never shown.
- **Provisioning** (`wizard_api/provisioning.py`, `scripts/make_provision.py`, `run.py --import-provision`):
  - company settings sit under the PC's `.env`;
  - `_PASSWORD`, `_TOKEN`, `_SECRET` and `_KEY` values go to the SecretBox (DPAPI on Windows);
  - per-PC keys are refused;
  - the plaintext file is deleted after the import.
- `WIZARD_GOOGLE_DOMAINS` refuses a Gemini link from a non-company Google account.
- **Web.**
  - `/quick` is the compact view: header, conversation, composer, and the account prompt first.
  - Messages go to the WebView2 host (busy, finished, hide), and the composer focuses when the panel opens.
  - "Open in a full window" links to `/?c=<conversation>`.
  - A single local Owner identity signs in without the picker.
- **Guards.**
  - `scan_secrets.py` flags fine-grained GitHub tokens and refuses `.provision` files.
  - The content validator flags GitHub tokens.
  - `.gitignore` excludes `*.provision` and `company.env`.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres,gemini-cli` in a Linux sandbox:
- PASS: spec, secrets, contracts, lint, types, python-tests (258 passed), evals-schema, web-types, web-unit (14),
  web-dist and web-build.
- BLOCKED: gemini-cli and postgres (not installed in the sandbox), and live-parity.
- e2e: the layer FAILs in the sandbox because Playwright 1.63 wants Chromium 1243 and the sandbox has 1194. Run with
  the sandbox's Chromium (`launchOptions.executablePath`), all 16 browser tests pass, including the new compact-view
  test on both viewports.
- New: `tests/unit/test_desktop.py` (27 tests) covers provisioning, the sync against a fake GitHub, desktop start-up, a
  real `run.py --desktop` process stopped through the control API, the domain rule, and the C#, installer, CI and
  Python pieces naming the same files and codes.
- WizardBar compiles with warnings as errors (`dotnet build`, .NET SDK 8 on Linux against the .NET Framework 4.8
  reference assemblies).
- The `desktop` workflow on `windows-latest` passed every functional step on its first run:
  - built WizardBar (version 1.0.1.0);
  - assembled the payload from the locked archives;
  - started the packaged service from the embeddable Python, served `/quick`, answered the control API and stopped
    when asked;
  - built `WizardSetup.exe`, installed it silently, passed `run.py --check` on the installed copy, and uninstalled it.
  - The last step failed on a version-text comparison: Inno writes "1.0.1", the numeric version is 1.0.1.0. It now
    compares numbers, as the updater does. The next run (2) passed every step and produced a 21 MB `WizardSetup.exe`.
- WizardBar's windows (the tab, the panel, the hotkey, the tray, the update) have not run on a desktop yet. The first
  run is on a work PC.

## 2026-10-12 — Big Data Portal: discovery task and `bdp-check`

The owner wants the Big Data Portal (BDP) as another platform. BDP is not a report platform: people request access to
tables and query them with SQL in Superset. The owner decided Wizard will query it through Superset under each
person's own company sign-in (the same SSO as ASAP and GSCM), never a shared account or browser cookies
([decision](decisions/2026-10-12-bdp-superset.md)). Nobody knows yet which engines sit behind Superset or how its API
signs people in, so this change is discovery only. Wizard has no BDP tool yet.

**What was added.**
- `wizard_documents/bdp.py` and `.\docs.ps1 bdp-check --url <address>`, anonymous GET requests only:
  - Superset's health check and version;
  - the sign-in route read from the login page's redirects and bootstrap data: protocol, identity provider, a gateway
    in front of Superset, Windows integrated sign-in;
  - what the REST API and its description answer.
  - Redirects that leave Superset's host are recorded, not followed. Only parameter names are kept, never values.
  - The result goes to `content\inbox\bdp\superset-check.md`. A database list the user saved from their signed-in
    browser (`superset-databases.json`) is summarised: engine, DML allowed, background queries, SQL Lab.
- Work-PC task 40 (`/wizard:tasks 40`, meant for Gemini 3.8 Flash):
  - search the documents for BDP;
  - run the check;
  - guide the user through two saved pages and two questions;
  - write `outbox\40-bdp-discovery.md` (internal, with the questions for the BDP team) and
    `outbox\40-bdp-shareable.md`.
- The docs kit launcher adds `services/agent` to its path, so `bdp-check` uses Wizard's own proxy resolution and
  certificate store (`wizard_agent.outbound`).

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres` in a Linux sandbox:
- PASS: spec, secrets, contracts, lint, types, python-tests (231 passed), evals-schema, web-types, web-unit, web-dist
  and web-build.
- BLOCKED: gemini-cli (the CLI is not installed in the sandbox), postgres and live-parity.
- FAIL: e2e. Playwright 1.63 could not launch: the sandbox has Chromium build 1194, not the 1243 it needs. This change
  touches no web code.
- New: `tests/unit/test_bdp_check.py` (13 tests) runs against simulated Superset servers (OAuth through Entra ID, a
  SAML gateway, a password page with Windows sign-in, an unreachable host). It checks that only anonymous GETs to
  Superset's own host are sent and that no parameter value is written.
- The real Superset is first checked on the work PC.

## 2026-10-09 — Wizard's logo and character

The owner's ask: Wizard is being productised and gamified. It needs a sprite, a logo, and the wizard as a character that
animates while the work is done, in Samsung colours (Samsung Blue `#1428A0`, white, black; colours only, no Samsung logo).

**What changed.**
- **`scripts/wizard_art.py`** (standard library only) draws the wizard and the logo from text grids. It writes:
  - `brand/`: logo, mark, app icon (SVG and PNG), the sprite sheet (48 x 48 frames, 11 animations), its JSON atlas
    and animated previews;
  - the web app's copies, and the favicon in `apps/web/index.html`.
  - `--check` fails on a stale file. `tests/unit/test_wizard_art.py` runs it, so CI catches art that was not redrawn.
  - Full guide: [brand/README.md](../brand/README.md).
- **Web app.**
  - The sidebar, the answer cards and the favicon carry the hat mark. Sign-in shows the logo and the resting wizard.
  - The start screen's wizard waves, then rests.
  - A running answer has a sticky stage: the wizard acts out the step in progress, with what it is and the step's own
    label. Search tools search, read tools read, `wizard_calculate` casts, `wizard_render_visual` draws a chart, Check
    my data checks. Streaming text writes; otherwise he thinks.
  - When the answer lands live he hops, or fizzles on a failure. A reopened run has no stage.
  - The animation comes from observed run events only (`apps/web/src/wizard.ts`). Nothing is acted out that Wizard did
    not do.
  - Reduced motion holds the first frame.

**Tests.** All passing:
- spec, secrets, contracts, lint, types;
- python-tests (with the 3 new art tests);
- web-types, web-unit (19, with the new mapping and stage tests), web-dist;
- e2e: 14 passed, desktop and narrow. Run against this container's Chromium build, since Playwright 1.63's own build
  could not be downloaded here.

Replay mode runs its tools instantly, so there the stage mostly shows thinking, writing and the hop at the end. With
live Gemini, each tool step lasts seconds and gets its own animation.

## 2026-10-07 (later) — Metric notes say where the data is

A structure review of the work PC's knowledge folder after the first live sell-in run:
- The 39 dataset notes from task 18 follow the standard well.
- The layer above them was missing. `metrics/sell-in-sell-out.md` defines sell-in but names no object, filter or week
  column. The dataset notes carry the business word only in tags, and their example questions are about plans.
- So Gemini found by trial which rows are weekly actual sell-in. Tasks 20-25, which write metric and glossary notes
  from documents, have not run there yet, and as written they never read the dataset notes either.

**What changed (documentation only).**
- **Knowledge standard, section 11 (new):** every metric note ends with `## Where to get it`, one block per object:
  - dataset note id and exact name;
  - measure column and unit;
  - filters with exact values;
  - period and market columns;
  - one example query, every name and value checked against the dataset notes.
  - The dataset notes point back: the metric's id goes in `related`, and its name and aliases in `aliases` or `tags`
    and in "Questions this note answers".
  - Guidance Gemini may follow or adapt, not a rule for building answers.
- **Section 10:**
  - dataset notes gain `## Example query`, using exactly quoted column names and the filters from Pitfalls;
  - `aliases` gain the business words;
  - "Questions this note answers" uses executives' words.
- **Tasks:**
  - 22 always plans a priority 1 metric note for each measure a dataset holds;
  - 23 reads the dataset notes when writing a metric note, then updates their links and aliases;
  - 24 points ambiguous measures at their metric notes;
  - 18 adds the new sections on its next pass.
- Not done: the catalog export covers materialized views only, so mapping tables such as a country map or date
  dimension cannot be documented from the export yet.

**Tests.** Documentation only. Run in a clean worktree, all passing: spec, secrets, contracts, lint and python-tests
(223 passed, on top of the long-runs change). The web layers were not re-run because nothing in `apps/web` changed.

## 2026-10-07 — Long runs end with an answer: higher limits, a loop check, a wrap-up window

Prompted by a live run on the work PC ("tell me market share by market in august 2026": 27 steps, 20 sources, killed
at 600 s with an empty result). Before this change, the time limit was a hard kill: everything Gemini had gathered was
thrown away. The owner's direction: Gemini 3.8 Flash may take 15-20 minutes when it needs to; stop loops, not thoroughness.

**What changed.**
- **Backstops, not budgets** (`config.py`, `.env.example`): run time limit 600 s → 1,800 s, tool calls 40 → 150 (allowed up
  to 500), concurrent runs 4 → 8. The code-assist runtime's hidden 24-turn cap is now 200 (`code_assist.MAX_STEPS`).
- **Loop check** (`RunManager._bound`): tools are read-only, so an identical call (same tool and arguments; whitespace
  inside strings ignored) returns what it did before.
  - The second try runs, since a view being refreshed can time out once. The third is refused (`repeated_call`) and
    logged on the server, naming the tool, because a loop usually means a tool's answer was unclear.
  - After three refusals, the data and knowledge tools refuse further calls (`loop_stopped`): answer with what you have.
- **Wrap-up window**: in the last fifth of the time limit (at most 4 minutes), the data and knowledge tools refuse
  calls (`time_nearly_up`) and Gemini writes its answer with what it has. Calculate, visual and Check my data stay open,
  so the answer can still have its chart.
- None of this picks a route: every refusal is a tool error Gemini reads, and the run goes on.
- **Where the time went**: each step in "What Wizard did" shows when it started in the run and how long its tool took
  (`2:35 · 58.1 s`). The gap between steps is Gemini deciding. A running answer shows a live timer. Durations of a minute
  or more read "10 min 6 s".

**Tests.**
- New: `tests/unit/test_run_bounds.py` (6), `RunCard.test.tsx` (live timer and step timing), and run-state and format cases.
- Python suite: 238 tests, 227 passed, 11 skipped (postgres, live and gemini_cli layers need their servers or sign-in).
- Also passed: ruff, mypy, web typecheck, web unit (14), `verify_spec.py`, contracts (unchanged), web dist rebuilt and verified.
- Checked in the browser with the replay runtime: step timings render beside each step.
- Not verified: a real 20-minute run. The work PC is the first place a long live run happens.

## 2026-10-07 — Email an answer; a calendar in every request

Prompted by the first live SIBP run on the work PC ("Sell in by market for last week": 41 steps, 26 evidence items, 283 s).
Gemini spent a knowledge lookup and a query establishing which week was "last week" before it could start.

**What changed.**
- **Email button** on a finished answer (`apps/web/src/email.tsx`, `wizard_api/outlook.py`). It opens an unsent Outlook
  draft. The draft holds:
  - the question;
  - the answer, with tables kept and charts as their data tables;
  - how long the answer took, its data mode and check status;
  - the sources the answer cites or charts, one line per table or report. Table names are read from the SQL; CTEs and
    set-returning functions are left out.
  - The page builds the message. `POST /api/v1/runs/{id}/email` hands it to Outlook through the new
    `wizard_docs.py outlook-draft` command, in a subprocess with a 60 s limit.
  - `Display()` runs first, so the user's signature is kept, and Outlook is never quit.
  - Only when the browser and Wizard share the PC (fixture sign-in, loopback client). Behind an SSO proxy, or when
    Outlook cannot open, the page downloads the same message as an `.eml` file (`X-Unsent: 1`).
  - Wizard never sends mail. This is a button for the user, not a Gemini tool; AGENTS.md's no-email-tool rule is
    unchanged.
- **Calendar block** at the top of every request (`prompting.calendar_block`):
  - today's date, local to the server: on the work PC (Gulf time, UTC+4) the previous UTC date was still yesterday
    until 04:00, so "this week" was wrong early on Mondays;
  - this and last ISO week with week numbers and dates, the last 4 complete weeks;
  - this and last month and quarter, year to date.
  - A dataset's own week or fiscal calendar wins where its notes define one. Context, not a rule.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres` on a second development PC (x64, Windows 11):
- PASS: spec, secrets, contracts, lint, types, python-tests (217 passed), gemini-cli, evals-schema, web-types,
  web-unit (11), web-dist, web-build and e2e (14, Chrome channel).
- BLOCKED as allowed: postgres (no test server here; CI runs PostgreSQL 16) and live-parity.
- New tests:
  - the calendar, including ISO week 53;
  - the Outlook draft, against fake Outlook objects: shown, never sent, signature kept, Outlook left running;
  - the email endpoint: opens, 404, Outlook unavailable (503), behind a proxy (409);
  - table names from SQL and the final-sources list;
  - the e2e Email flow with the request intercepted, and the `.eml` fallback.
- Not verified: real Outlook. It first runs on the work PC.
- Environment notes for this PC:
  - uv is installed as a Python module, not on PATH, so verify_all ran with `.venv\Scripts` on PATH.
  - Edge's `msedge.exe` is missing, so e2e ran with `WIZARD_E2E_CHANNEL=chrome`.
  - `uv sync` rewrote `uv.lock`: the committed lock lacks pg8000's dependencies. That change is not included here.

## 2026-10-06 (evening) — Gemini writes its own SQL on PostgreSQL; the report-entry connector is withdrawn

Decision: [2026-10-06 live PostgreSQL](decisions/2026-10-06-live-postgresql.md). The owner withdrew the connector
below the same day. It constrained Gemini before any failure had been seen: report entries, aggregation rules, a
review task and a parity sign-off. The owner had already found Gemini 3.8 Flash excellent on this data.

**What changed.**
- **New tool `wizard_query_postgresql(sql, database?, max_rows?)`** (`wizard_connectors/postgres_query.py`). It reads
  whatever the read-only account's grants allow, guided by the task 18 dataset notes, and `wizard_list_sources` lists
  PostgreSQL when it is connected.
- **Protections:**
  - one statement through the extended protocol, with pg8000's placeholder parsing bypassed. pg8000's simple protocol
    would have accepted chained statements;
  - wrapped as a subquery;
  - START TRANSACTION READ ONLY, always rolled back;
  - a fresh connection per call, closed afterwards;
  - 60 s statement and 2 s lock timeouts;
  - at most 500 rows.
- **Labels and evidence.**
  - Data mode `LIVE` ("Live"), connector status `READ_ONLY_SQL`.
  - The sources drawer shows the SQL and the database.
  - Check my data runs the same SQL again and reports UNCHANGED or CHANGED.
- **Rights.** The tool needs the `postgresql` right for every market. The local Owner has it whenever a connection is
  set.
- **Removed:**
  - `postgres_source.py`, `postgres_contract.py`, task 19, and `.\docs.ps1 postgres-contract` / `postgres-sample`;
  - `relation`, `parity` and `column` in report entries;
  - `LIVE_UNVERIFIED`, `ROWS_UNVERIFIED`, and the system-prompt line about unchecked figures.
  - Catalog, validator and contract schema are back to `7ba5025`.
- **Kept:** the attachment tables and `wizard_query_attachment`, the shared `pg.py`, the PostgreSQL settings, and the
  start-up check (now always shown: reachable and read-only, or not configured).
- **Docs.** The knowledge standard asks dataset notes to name the database and say in `## Pitfalls` what a correct query
  must know. AGENTS.md allows this one SQL tool as an owner exception. Wizard declares 20 tools.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres` on the development PC: spec, secrets,
contracts, lint, types, python-tests (214 passed), gemini-cli (4 passed; the real CLI accepts all 20 tool schemas),
evals-schema, web-types, web-unit (6 passed, including the drawer showing the SQL), web-dist, web-build and e2e (12
passed) PASS. postgres and live-parity are BLOCKED here.
- `tests/unit/test_postgres_query.py` covers:
  - the SQL sent as written, inside a read-only transaction that is rolled back;
  - caps, types and error hints;
  - rights, evidence and Check my data;
  - the local Owner's access.
- `tests/integration/test_postgres_query_real.py` (CI's PostgreSQL 16, under an account allowed to write):
  - real analysis with a CTE, a join and window functions;
  - six write attempts, each refused and leaving the data unchanged;
  - a setting changed by one query does not outlive it.

## 2026-10-06 (later) — Live PostgreSQL reports and totals over attached spreadsheets

Withdrawn the same evening (entry above), except the attachment tables.

Decision: [2026-10-06 live PostgreSQL](decisions/2026-10-06-live-postgresql.md). Gemini CLI had told the owner that
Wizard could not give a GSCM or SIBP number: every real report was navigation-only.

**What was added.**
- **Live connector.**
  - `wizard_connectors/postgres_source.py` runs a catalogued PostgreSQL report through the same contract as the
    fixtures (`filters`, `group_by`, `measures`, `sort`, `limit`). The SQL is built from the entry's columns, with
    quoted identifiers, bound values, LIMIT 500 and market rights in the WHERE clause.
  - Aggregation rules run in SQL: `sum`; `sum_same_currency` (a total only within one currency); `last` (latest
    period per group); `none` (a value only for one row). Text columns holding numbers are cast safely.
  - Freshness comes from commit timestamps when the server tracks them.
  - Connection code shared with the export moved to `wizard_connectors/pg.py`.
- **Labels.**
  - New data mode `LIVE_UNVERIFIED` ("Live · not yet checked") and connector status `ROWS_UNVERIFIED`.
  - A report's signed `parity` (date, who, reference) makes its rows `LIVE_VERIFIED`.
  - The run result tells Gemini the figures are not yet checked, and the system prompt asks it to say so once.
  - The web badge, source explorer and API catalog show both states.
- **Contract.** `relation` (database, schema, view), `parity`, and `column` on dimensions, measures and attributes.
  The validator allows row reports only for PostgreSQL and checks:
  - the `last` and currency rules;
  - the parity date;
  - that parity is set only on live reports.
- **Kit.**
  - `.\docs.ps1 postgres-contract --view schema.view` drafts entries from the export and dataset notes, marking every
    guess `UNCERTAIN:`.
  - `.\docs.ps1 postgres-sample --report <id>` runs Wizard's own query for a parity check.
  - Task 19 walks Gemini CLI and the owner through choosing (SIBP first), reviewing and signing.
- **Start-up.** `run.py --check` reports whether PostgreSQL is reachable and the session read-only, whenever the catalog
  has PostgreSQL reports.
- **Attached spreadsheets.**
  - Each sheet or CSV is also saved as a full typed table (`converted/tables.json` plus CSV, up to 300,000 rows and 60
    columns).
  - The new tool `wizard_query_attachment` filters, groups and totals every row (sum, avg, min, max, count). It warns
    about rate columns and non-numeric cells.
  - Evidence stays `USER_PROVIDED`. Wizard now declares 19 tools.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres` on the development PC: spec, secrets,
contracts, lint, types, python-tests (207 passed), gemini-cli (4 passed; the real CLI accepts all 19 tool schemas),
evals-schema, web-types, web-unit, web-dist, web-build and e2e (12 passed) PASS. postgres and live-parity are BLOCKED
(no PostgreSQL or live source here).
- New unit tests:
  - the generated SQL: quoted, bound, with rights applied;
  - each validator rule;
  - LIVE_UNVERIFIED before parity and LIVE_VERIFIED after it;
  - the draft and sample commands;
  - the attachment query engine and its evidence.
- `tests/integration/test_postgres_source_real.py` compares every aggregation rule with independently computed values on
  CI's PostgreSQL 16.
- The corporate views are first read on the work PC, in task 19.

## 2026-10-06 — PostgreSQL materialized views documented from the server's catalog

The owner chose to document the PostgreSQL server first, and only its materialized views, with the server as the
source of truth and a light profile of the data.

**What was added.**
- `wizard_documents/postgres.py` exports, over a read-only session (60 s statement timeout, 2 s lock timeout, SELECT
  only):
  - every visible materialized view: columns, types, comments, owner role, indexes, the SQL definition;
  - lineage both ways (through `pg_rewrite`/`pg_depend`);
  - the pg_cron job that refreshes it, statistics, and freshness from commit timestamps when tracked;
  - a light profile: exact row count, null rates and distinct counts (TABLESAMPLE above 200,000 rows), date and
    period ranges, and the values of code columns with at most 25 values.
  - No sums or numeric ranges are read, and columns that name people are never listed.
- `.\docs.ps1 postgres-check` and `postgres-catalog`.
- Settings: `WIZARD_PG_*` in `.env`, else the scanner account's `PG*` variables. The password is never printed or
  written.
- pg8000 (pure Python; psycopg2's DLL was blocked by Application Control on a development PC) is in the portable
  runtime: release `portable-cp313-win_amd64-ebab720ef8aa0947cf47`. It was verified to import and connect from the x64
  embeddable Python with `site` off.
- Task 18 writes `platforms/postgresql.md` and one `datasets/` note per view. The knowledge standard gains the
  `dataset` type and section 10: the export wins over documents.

**Tests.**
- Unit tests against a fake catalog assert that only SELECTs are sent, plus sampling, ranges, value lists, person
  columns, lock timeouts and output files.
- `tests/integration/test_postgres_real.py` runs on a PostgreSQL 16 service in CI. It builds a staging table, a
  materialized view, a view on top and a SELECT-only role, checks the export, and proves the session refuses a write.
  It is BLOCKED locally (no PostgreSQL here).
- The corporate server is first read on the work PC.

## 2026-10-05 (late) — Company documentation kit, expert quizzes and attached files

Decision: [2026-10-05 company documentation](decisions/2026-10-05-company-documentation.md).

**Knowledge retrieval.**
- `wizard_lookup_definitions` now ranks `##` sections (glossary entries one by one) with BM25 and stopwords, and
  boosts title, aliases, tags and summary.
- A long note returns its lead plus the matching sections and the headings it left out.
- New tools `wizard_browse_knowledge` (index with summaries) and `wizard_read_knowledge` (by id); 18 tools in all.
- Notes gain `type`, `summary`, `aliases`, `related`, `sources`, `updated`, `reviewed`, `reviewed_by`, under
  [the knowledge standard](../templates/content/schema/knowledge-standard.md).
- The content validator enforces the standard: flat front matter, unique kebab-case ids, known types, ISO dates, no
  email addresses. It warns about missing summaries, oversized notes and dangling `related` ids.
- A content folder with notes but no report catalogs is accepted.

**Document converter (`services/documents`, `scripts/wizard_docs.py`, `docs.ps1`).**
- Office through pywin32, following data_governance's rules: borrow a running application, open read-only in place,
  macros off, no SaveAs, restore settings, quit only what it started.
  - PowerPoint: text, tables, SmartArt, chart values, speaker notes, pictures of mostly-visual slides.
  - Excel: column profiles with formulas, pivot tables, charts, named ranges.
  - Word: headings and tables.
  - Outlook: display names, body, attachments.
- Standard-library fallback for plain .docx/.pptx/.xlsx, plus .eml, text, CSV and HTML. Office parts that declare a
  DOCTYPE are refused.
- Bulk inbox:
  - stable source ids (`S-` + SHA-256 prefix), with duplicates recognised;
  - email attachments followed and linked to their email;
  - email addresses and phone numbers masked;
  - folders listed in `inbox/_sources.txt` read in place (for NASCA files);
  - incremental re-runs.
- Outlook export of chosen folders and dates; private and confidential items skipped.
- Kit commands: progress, next sources, topics, coverage, quiz check, quiz answers.
- `run.py --check` reports whether pywin32 loads.
- pywin32 312 is added to the portable runtime (release `portable-cp313-win_amd64-19ef1695a72713055a2f`). It was
  verified to load from a vendor folder in the x64 embeddable Python with `site` off.

**Gemini CLI tasks 20-25 and 30-31.**
- Collect, digest (Gemini 3.5 Flash), topic map, write, glossary and ambiguous terms, coverage.
- One HTML quiz per area and stakeholder (`workpc/templates/quiz-template.html`: offline, autosave, "Save my answers"
  produces a filled copy to attach, "Copy my answers" gives a base64 block safe in quoted replies).
- Applying answers as cited sources (`A-<quiz>-<question>`).
- `setup.ps1` installs `docs.ps1`, `templates\` and `documents\quiz-*`, and refreshes `content\schema\` and
  `content\.gemini\commands\`.

**Attached files.**
- Upload or "From this PC" (`WIZARD_ATTACHMENT_FOLDERS`; off behind SSO).
- Conversion in a time-limited child process, one at a time.
- Files bound to the run as F1, F2…, listed in Gemini's prompt and read with `wizard_read_attachment`.
- Evidence uses the new data mode `USER_PROVIDED` (above SYNTHETIC, below approved sources). The drawer shows the text
  read.

**Tests.**
- `verify_all.sh --allow-blocked=live-parity`: every required layer PASS.
  - 189 Python tests, including new converter tests with fake COM objects, kit, knowledge, attachment and validator
    tests.
  - The real Gemini CLI accepts all 18 tool schemas.
  - 12 Playwright tests, including attaching a file.
  - live-parity is BLOCKED (no corporate access).
- The quiz page was exercised in a browser: answer, copy, reopen the saved answers, phone width.

**Not verified here.**
- Office and Outlook automation: this development session cannot start Office COM servers (`CO_E_SERVER_EXEC_FAILURE`).
  The first real run is task 20 on the work PC, which reports every file it could not read.
- `uv.exe` is now blocked by Application Control on the development PC, so `uv.lock` was not refreshed for pywin32.
  CI re-locks on Linux, where pywin32 is skipped. `WIZARD_E2E_PYTHON` lets Playwright start the E2E server without
  uv.

## 2026-10-05 (night) — Tool schemas checked against Gemini's rules (fixes 400 on every question)

**Work PC.** Every question failed with
`400 INVALID_ARGUMENT: schema at top-level requires unspecified property 'title'`.

**Cause.**
- `flatten_schema` dropped every `"title"` key to remove pydantic's metadata titles.
- That also deleted `wizard_render_visual`'s real `title` parameter from `properties`, while it stayed in `required`.
- All 15 tools are declared on every request, so Google rejected every request before the model ran.
- The offline fake-response tests never send schemas to Google, so they could not see it.

**Fixes.**
- Only metadata titles are dropped; property names are kept.
- Tool schemas now carry only the keywords Gemini documents
  ([structured output](https://ai.google.dev/gemini-api/docs/structured-output),
  [`FunctionDeclaration`/`Schema`](https://ai.google.dev/api/generate-content)), plus `anyOf`.
- `pattern`, `minLength`, `maxLength`, `const` and `default` are folded into the description. The registry still
  enforces them through the closed pydantic models.

**New guard: `wizard_connectors/gemini_rules.py`.** It checks:
- every `required` name exists in `properties`;
- only documented keywords, and no `$ref`/`$defs`/`oneOf`/`allOf`;
- single `type` values, and no `anyOf` with null;
- arrays declare `items`, and enums are strings;
- parameter names match `[A-Za-z_][A-Za-z0-9_]{0,63}`;
- function names follow Gemini CLI 0.62's `generateValidName` limits.

**Where it runs.**
- Contract tests on every tool, in both forms: as the CLI declares it (`mcp_<tool>`, `parametersJsonSchema`) and as
  the Code Assist runtime converts it (`parameters`).
- The real-CLI integration test, on the exact request body the CLI sends to Google.
- `run.py --check` on the work PC. That one FAILs with "Gemini would reject this request (400)" instead of letting a
  question fail.

**Also fixed.** `mypy` found that a local `onboard` variable shadowed `resolve_project`'s new `onboard` parameter.

**Still unverified.** A live call to Google cannot run on the dev laptop. These checks enforce Google's documented
rules.

## 2026-10-05 (evening) — Gemini quota ring

- **What it shows.** A small ring next to the account at the bottom left shows how much of the person's quota for the
  configured model (`gemini-3.8-flash`) is used. The hover text gives the % left (or N of M left) and the reset time.
- **Where the number comes from.** `GET /api/v1/account/gemini/quota` calls the Code Assist `retrieveUserQuota` method,
  the call Gemini CLI 0.62 makes. It uses the person's own linked sign-in and their project. The lookup:
  - never onboards an account;
  - is cached for a minute;
  - refreshes after each answer and every 5 minutes.

  The ring is hidden when quota is unavailable, and the reason goes to the server log.
- **Selection.** `summarize_quota` picks the configured model's most constraining bucket; a `-preview` variant also
  matches.
- **Not verified live.** Real bucket names for the enterprise licence are still to be confirmed on the work PC.

## 2026-10-05 (latest) — HTML reports folder setting

**Decision.** Power BI is dropped; standalone HTML reports (local files for now, fed from PostgreSQL) are the
reporting path.

**Setting.** `WIZARD_HTML_REPORTS_DIR` names the folder of HTML reports (subfolders allowed; relative paths resolve
against the install folder). It is configuration only: no tool reads the folder yet.
- A path that is not a folder stops start-up with a clear message.
- `run.py --check` prints the folder and how many `.html`/`.htm` files it holds.
- `setup.ps1` adds a commented `# WIZARD_HTML_REPORTS_DIR=` line to `.env` once, for you to fill in.

**Tests.** `uv run python -m pytest tests`: 130 passed, 1 skipped. `verify_spec.py` passed.

## 2026-10-05 (later) — Dev diagnostics in the UI, minimal chrome

**Feedback.** "Hey" failed after 59 s with "Gemini stopped with an error". Gemini CLI was named in three places.

**Diagnostics** (`WIZARD_DIAGNOSTICS`, on by default while in dev):
- Every Gemini CLI run attaches a diagnostic, shown under the answer and opened automatically on failure:
  - the CLI's full stderr and any non-JSON stdout;
  - the CLI's own error report (message and stack);
  - exit code and elapsed time;
  - the setup it ran with: CLI version, node, model, proxy, certificates, project.
- Unexpected failures attach their traceback.
- A **Log** button in the sidebar shows the server's recent log.
- Secrets are redacted.

**Bug found.** An earlier shell edit had turned the classifier's `\b` word boundaries into backspace characters, so
401, 403 and 429 never matched and fell through to the generic message. Fixed, and two guards added:
- a regression test for the classifier;
- a test that rejects control characters in source files.

New codes: `project_required`, `model_not_found`, `model_unavailable`, `model_rejected_request`, plus broader network
patterns.

**Project.** `GOOGLE_CLOUD_PROJECT` now falls back to the person's own Gemini CLI `.env` (`~/.gemini/.env`,
`~/.env`), which Wizard's isolated CLI home cannot see. `run.py --check` prints the project and where it came from.

**UI.** Gemini is named only in the account status at the bottom of the sidebar. Replay stays labelled. Dated reports
keep their runtime badge as provenance.

**Local build note.** Smart App Control blocks Tailwind's arm64 native module. Building with
`@tailwindcss/oxide-wasm32-wasi` installed via `--no-save` works and leaves `package.json` unchanged.

## 2026-10-05 — Work-PC Gemini sign-in fixes (first feedback from the work PC)

**Feedback.** The user saw only the synthetic test identities, none with their email. Pasting the Google code gave
"Wizard hit an internal error".

**Causes and fixes:**
- **No Owner identity.** The Owner was only added when `whoami /upn` produced an email, which often fails or returns a
  directory domain that differs from Google. An install now always lists the Owner first, and the Owner takes its email
  from the Google account it links (kept across restarts). Test identities explain that no real account can be linked
  to them, and point to the Owner.
- **The "internal error".** Wizard's Python called Google with certifi and no proxy. On a corporate PC, TLS inspection
  and proxy/PAC routing break that, as the data-governance app found on the same PCs. All Google calls now verify
  against the Windows certificate store (`truststore`) and use the resolved proxy, in this order:
  1. `WIZARD_PROXY`
  2. `HTTPS_PROXY`
  3. the user's own Gemini CLI `proxy` setting
  4. the Windows/PAC settings
  5. direct

  The Gemini CLI that Wizard starts receives that proxy and `NODE_USE_SYSTEM_CA=1`.
- **Error messages.** A network failure is now a 502 that names the host, the cause and the route, with the
  `WIZARD_PROXY` fix. `run.py --check` now tests both Google hosts.

**Portable runtime.** Republished as `portable-cp313-win_amd64-6bfe2f91b55233a53dd8`, which adds `truststore` 0.10.4
and leaves every other pin unchanged.

**Verification.**
- Smart App Control now blocks `uv` and the arm64 `pydantic_core` on this laptop (see
  [decisions/2026-10-02-dependencies.md](decisions/2026-10-02-dependencies.md)).
- Tests ran on the portable amd64 runtime: 122 passed. 2 failed, both contract tests that start the shim with `-m`
  from a working directory; the embeddable Python ignores the working directory by design, so they run in CI.
- `ruff`, `verify_spec` and the secret scan are clean. `mypy` and the full `verify_all` run in CI.
- New tests cover:
  - an Owner without an email, and one whose `whoami /upn` differs from the Google email;
  - a test identity being refused with a pointer to the Owner;
  - TLS and timeout failures returning 502 with an explanation;
  - the proxy resolution order and the CLI environment.

## 2026-10-02 (evening) — Work-PC install, update loop and Gemini CLI task kit

- **Install like B2B:** `setup.ps1` / `start.ps1` / `update_app.ps1` at the repository root, guide in
  [workpc-setup.md](workpc-setup.md), decision in [decisions/2026-10-02-workpc-install.md](decisions/2026-10-02-workpc-install.md).
  Portable CPython 3.13.15 plus 17 locked wheels, published as release
  `portable-cp313-win_amd64-f77a70401bd85a63d2e5` by `scripts/lock_portable.py --publish`. The web app is committed
  prebuilt (`apps/web/dist`, fingerprint checked by the new `web-dist` layer).
- **Install-folder mode:**
  - `run.py --home <folder>` reads `.env` and keeps `data\` in the install folder.
  - `run.py --check` gates every new release: does the app start, does content validate, and an offline Gemini CLI
    probe. The probe confirms exactly Wizard's 15 tools, Wizard's prompt, thinking HIGH, and no `GEMINI.md` leaking in
    from a parent folder.
  - `WIZARD_LOCAL_USER_EMAIL` adds an Owner identity with the real work email.
- **Fix found by the probe:** Gemini CLI loaded `GEMINI.md` from parent folders into the analyst's context. Wizard's
  per-user CLI settings now point `context.fileName` at a name that never exists.
- **Gemini CLI task kit** (`workpc/`):
  - `/wizard:tasks` and tasks 00–17, 90 (environment report, inventory, platform guides, report catalogs,
    definitions, question coverage, validation, owner questions, switch to real catalog, feedback pack).
  - `GEMINI.md` and `.geminiignore` keep `data\` and `.env` out of reach.
- **Verification:**
  - New `tests/unit/test_workpc.py`, which parses all four PowerShell scripts with the PowerShell parser.
  - The real-CLI probe test.
  - Local `verify_all.sh --allow-blocked=live-parity`: every layer PASS, only live parity BLOCKED.
- **End-to-end install from GitHub** (dev PC, empty folder, token from `gh auth token`, exactly the documented
  bootstrap):
  - **First install** of `f483db8`: 18 archives downloaded and verified, portable Python started under x64
    emulation, the check passed. It warned "Gemini CLI not found" because this PC has no global CLI, and
    `whoami /upn` is empty because the PC is not domain-joined.
  - **`update_app.ps1 -NoStart`** after setting `WIZARD_GEMINI_CLI_JS` and `WIZARD_LOCAL_USER_EMAIL` in `.env`:
    archives reused, every check PASS, including the real-CLI compatibility probe on the portable Python.
  - **`start.ps1`**: health/ready OK, Owner identity listed first, chat UI and the "Link your Gemini account" dialog
    working.
  - **`/wizard:tasks 00`** (Gemini CLI 0.62 in the install folder, offline): the command expands with its argument and
    the folder's `GEMINI.md` loads, but **only in a trusted folder**. CLI 0.62 refuses untrusted folders headless and
    asks interactively, so the guide and setup now say to trust the folder.
- **Not testable here:** linking a real enterprise Google account and a live answer. Those are the first things to try
  on the work PC.

## 2026-10-02 (later) — Real-content loader, documentation kit, CI type fixes

- **Content folder:** `WIZARD_CONTENT_DIR` loads an internal wizard-content repository instead of the synthetic examples.
  It is validated at start-up (`wizard_connectors/content.py`, also `scripts/validate_content.py`). Real reports must be
  NAVIGATION_ONLY with no data file; secrets, stray data files, bad front matter, wrong ids and summed percentages
  stop the service. Not allowed with the replay runtime. Navigation-only platforms make no data-mode claim in the UI.
- **Documentation kit:** `templates/content/` (layout, authoring rules, Gemini CLI commands `/wizard:platform-guide` and
  `/wizard:report-catalog`, schema copy kept in sync by `verify_spec.py`); [documentation-guide.md](documentation-guide.md),
  [how-it-works.md](how-it-works.md). The ASAP importer now emits strictly valid drafts.
- **CI:** the first CI run failed only on mypy (18 typing findings; mypy had never run, as it was blocked on the dev PC).
  All fixed, plus 3 more found once a source-built mypy ran locally. Local `verify_all.sh --allow-blocked=live-parity`:
  every layer PASS (101 Python tests, 3 real-CLI tests, 10 E2E, types clean); only live parity BLOCKED.

## 2026-10-02 — Release A foundation (SYNTHETIC)

**Mode of operation:** SYNTHETIC data only. Runtimes available: `replay` (default; recorded transcripts),
`gemini-cli` and `code-assist` (live routes, implemented; **no real enterprise account has been used yet**).
No corporate system, credential or data has been touched. Nothing here is LIVE_VERIFIED.

**Built on:** Windows 11 ARM64 development PC, Python 3.13.15 (uv 0.12.5), Node v24.19.0, Gemini CLI 0.62.0 (pinned in
`.tools/`, offline fake responses only).

### What was implemented

| Plan step | Delivered |
|---|---|
| 00 | New repository; agent-first AGENTS.md/GEMINI.md; [repo-references.md](repo-references.md) (B2B design system reused, Scribble's working Gemini sign-in located at `41ab532` and ported, Metronome policy/MCP patterns); spec and fail-closed verification gates |
| 01, 03, 04 | Drafts: product requirements, coverage matrix, source register, typed source contracts, unsigned knowledge notes, synthetic goldens |
| 02 | Two runtime routes behind one interface; per-user isolation verified against the real CLI (forced file credential storage, `tools.core=[]`, policy file, system-prompt override); in-app per-user Google linking with email match; two-user spike script (offline check passes); threat model |
| 05–07 | FastAPI run manager with SSE, SQLite store, 15 read-only tools, MCP stdio shim, Check my data, calculator, B2B-style web app (timeline, evidence drawer, charts/tables, source explorer, dated reports), 30 draft eval cases + runner |
| 08 | Fixture and trusted-header identity, rights on search/run/reopen, audit log, retention expiry |
| 09, 14 | ASAP navigation states in the explorer, Library REST client groundwork, metadata-only catalog importer, BLOCKED parity test; per-platform guides ([platforms.md](platforms.md)) |
| 12–13 | Planner and conquest stories over synthetic data (screening and observed-count framing) |

### Verification output (`scripts/verify_all.sh --allow-blocked=live-parity,types`)

```
spec             PASS   verify_spec passed: fixtures, contracts, goldens, transcripts, knowledge and links are consistent.
secrets          PASS   Secret scan clean.
contracts        PASS   Published contracts match the code.
lint             PASS   ruff: All checks passed!
types            BLOCKED  mypy: DLL load failed while importing ast_serialize: An Application Control policy has blocked this file.
python-tests     PASS   88 passed, 4 deselected
gemini-cli       PASS   3 passed (real Gemini CLI 0.62.0, offline fake model replies)
evals-schema     PASS   1 passed
web-types        PASS   tsc --noEmit
web-unit         PASS   4 passed
web-build        PASS   vite build
e2e              PASS   10 passed (Playwright, Edge, desktop 1440x900 + narrow 1024x768)
live-parity      BLOCKED  live ASAP parity not configured (WIZARD_PARITY_* unset)
verify_all: all required layers passed.
```

`types` runs in CI on Linux; it is blocked only on this PC. `live-parity` stays BLOCKED until Step 09 has an approved
route, report and signed reference.

### Problems found and fixed while building

- Gemini CLI headless mode silently dropped every MCP tool (policy engine turns "ask user" into deny) → per-home policy
  file passed with `--policy`.
- Gemini CLI keychain token storage is shared across `GEMINI_CLI_HOME`s → `GEMINI_FORCE_FILE_STORAGE=true` everywhere.
- The CLI blocks `PYTHONPATH` for MCP servers → shim started with `cwd`.
- Error classification matched digits inside ids as HTTP codes → word-boundary patterns, most specific first.
- A denied market was also reported as "no data in source" → denied values excluded from missing-data warnings.
- E2E projects collided on one user's single active run → one worker.

### Open decisions (owner / IT), defaults in force

See plan section 7 and [issue-board.md](issue-board.md). Highlights: which runtime route is approved (default: none for
executives; local synthetic only); fiscal calendar and markets (synthetic Q3 2026 only); which reports cover spend,
sell-through, share and switching (three mock adapters); ASAP Library REST access (navigation only); pilot host, TLS,
backups and operator (local development only); retention and sharing (creator only, 30 days).
