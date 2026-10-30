# Wizard

A permission-aware executive analyst. The CEO, CFO and directors ask a business question in a chat interface; **Gemini,
running under each user's own enterprise Google sign-in, decides which approved read-only sources to consult**, compares
what it finds and writes the answer. Wizard handles identity, tool boundaries, evidence capture, streaming, checks and
dated web reports. Every number links to the rows it came from, and every answer carries its data mode and check status.

> **Status (2 October 2026): Release A foundation — SYNTHETIC data only.** Nothing here is connected to corporate
> systems, and no answer is a corporate figure. The live Gemini routes are implemented and tested offline with the real
> Gemini CLI; they still need the Step 02 sign-in spike with two enterprise accounts on the intended host.
> See [docs/build-report.md](docs/build-report.md) for exactly what runs, what was tested, and what is blocked.

## What runs today

| Area | State |
|---|---|
| Web app (B2B design system): chat, live "What Wizard did" timeline, answers with evidence chips, charts/tables, Show sources (one entry per table, report or file, opening to its queries), source explorer, dated report pages, Check my data | Working, browser-tested |
| Email an answer | The Email button on a finished answer opens an unsent Outlook draft: the question, the answer (tables kept, charts as their data), how long it took, data mode and check status, and the tables and reports the answer cites (table names read from the SQL). Without classic Outlook, or behind an SSO proxy, it downloads the same message as an `.eml` file. Wizard never sends mail and Gemini has no email tool | Tested with fake Outlook objects; real Outlook first runs on the work PC |
| Recurring briefs (Metronome) | **Make recurring** under an answer that queried the database (every day, every Monday, the 1st of the month, or something else), or asking for it ("send me this every Monday"). Gemini turns the answer into a brief, a short newsletter email: key-number tiles, bar and line charts, tables and "what moved" sentences that rules write from each run's rows (no AI at send time), each section with its own query whose dates move with `CURRENT_DATE`. `wizard_schedule_brief` test-runs every query and the card shows the email as it would look today. It goes to the person's own address (sign-in email without the `ax.` after the @) at 08:00 Dubai time unless they say otherwise, with an Excel file of every row attached. Nothing is scheduled until the person presses **Create in Metronome**: Wizard checks its key is signed in as Metronome's **Wizard** user and creates an active Python-script Flow owned by that user. Its generated read-only script carries Wizard's email renderer, draws the charts with matplotlib and writes the email, which Metronome's Email step sends. The sidebar's **Recurring** tab lists the person's briefs with Metronome's state (on or off, next and recent runs); **Delete** turns the Flow off in Metronome. Recipients must be company addresses. Settings → Metronome, `scripts/metronome_link.py`. [Decision](docs/decisions/2026-10-20-metronome-recurring-extractions.md), [briefs](docs/decisions/2026-10-23-recurring-briefs.md) | Tested against a fake Metronome with its real ownership rules, the generated script with fake drivers and fake matplotlib, the charts with real matplotlib in a scratch environment, and Metronome's email step in its own repository; the real Metronome is first used on the work PC |
| Run limits | A run may take up to 30 minutes and 150 tool calls: backstops, not budgets. Wizard refuses a third identical call, tells Gemini to answer after three such refusals, and in the last 4 minutes closes the data tools, so a long run ends with an answer instead of nothing. "What Wizard did" shows when each step started and how long its tool took; a running answer shows a timer. An answer that could not finish has **Error details**: Google's finish reason and words, what Gemini sent back, the models tried, the last tool call, timings, with Copy | Unit-tested |
| Steering and the systems picker | **While an answer runs, the question box takes a note** ("use the weekly sell-out view"): on the Code Assist connection (the desktop app's) Gemini reads it before its next step, without starting over; on Gemini CLI or replay the note stops the run and asks again with it. **Not this** on any step that read data (the stage's live SQL caption, a system's calls, Step by step): wrong table, filter or period and what to use instead; Gemini leaves that step's evidence out. Follow-ups carry what each earlier answer read (SQL, results, evidence ids). **Remember** under a note or a question keeps it for every later question of that person (Account → What Wizard remembers). **Systems** beside the question box: Auto, or only the systems ticked (the knowledge base comes on with the first); only their tools are offered and the others refuse inside the run, and Gemini can ask to switch one on with a button. [Decision](docs/decisions/2026-10-30-steering-and-systems.md) | Unit, API (a scripted runtime that takes notes), component and browser tested; the real Code Assist route is first steered on a work PC |
| Relative dates | Every request starts with a calendar: today's local date, this and last ISO week with dates, the last 4 weeks, this and last month and quarter, year to date. A dataset's own calendar wins where its notes define one | Unit-tested |
| Agent runtime **gemini-cli**: Gemini CLI 0.62 headless `stream-json`, one isolated `GEMINI_CLI_HOME` per user, Wizard tools over MCP | Working end-to-end with the real CLI and offline fake model replies; needs a real sign-in to answer live |
| Agent runtime **code-assist**: the Code Assist API Gemini CLI uses, per-user Google sign-in (ported from Scribble `41ab532`). A turn with neither text nor a tool call is asked again (the same model once, then the other twice), as Gemini CLI does | Implemented; tested against a scripted Google fake; needs a real account |
| Agent runtime **replay**: recorded transcripts over synthetic data for CI and demos | Working; labelled REPLAY everywhere |
| Read-only tools: NERP, GSCM, ASAP (search, schema, run report) + catalog, knowledge (search, browse, read), attached files, PostgreSQL SQL, calculate, visual, Check my data | Working over SYNTHETIC fixtures with per-user report and market rights. These report tools read fixture files or a navigation-only catalog, never the portals themselves: live portal reads are the row below |
| Company portals, live (ASAP, GSCM, Big Data Portal) | Gemini reads them in the person's own **Wizard browser**: Playwright drives the installed Google Chrome (or Edge) with Wizard's own profile, in the background. **Settings → Portals → Sign in to the portals** opens it visibly once, one tab per portal, for the person's own sign-in, which then lasts as long as the portals' own sessions, across restarts too: Wizard keeps its browser's session-only cookies through the secret store (DPAPI), never a password. `portal_run` runs Gemini's own steps (open, click, fill, wait, look, read a table) and JavaScript in the page, where `fetch()` carries the person's session: W helpers read Nexacro Datasets (GSCM), walk ASAP's MicroStrategy menu without the token leaving the page, replay the portal's own data requests with new parameters and parse SSV/XML/JSON, and query Superset (BDP). `portal_guide` relays what Metronome learned driving each portal; `portal_save_script` keeps steps that worked. Inside the tool: only the portals' hosts, their company domain and the person's sign-in hosts are reachable; requests named for a write and Metronome's forbidden clicks are refused; SQL Lab runs one SELECT; secrets are redacted from what Gemini sees. Evidence is `LIVE` / `BROWSER_SESSION` with the steps as its query. Desktop app and work-PC installs only. [Decision](docs/decisions/2026-10-23-portal-browser.md) | Tested in a real Chromium against a simulated portal (Nexacro datasets, an ASAP session, SSV transactions, refusals); the real portals are first read on the work PC |
| Company knowledge | Notes in `content\knowledge\<area>\` to [the knowledge standard](templates/content/schema/knowledge-standard.md); section-level search, a browse index and read-by-id; draft/expert-checked/signed status shown to Gemini | Working; real notes come from the Gemini CLI tasks below |
| Documentation kit (work PC) | Gemini CLI tasks 20-25 collect chosen Outlook folders and files, convert them through Office (pywin32; NASCA files read in place), digest, plan and write the notes; tasks 30-31 build one HTML expert quiz per area and stakeholder and apply the answers. `.\docs.ps1` does the converting and checking | Tested with standard-library files, fake Office objects and the quiz page in a browser; real Office/Outlook first runs on the work PC |
| PostgreSQL data dictionary (work PC) | Task 18: `.\docs.ps1 postgres-catalog` exports every materialized view from the server's catalog over a read-only pg8000 session (structure, SQL, lineage, pg_cron refresh, light profile); Gemini CLI writes one `datasets/` note per view, with the catalog as the source of truth | Tested against fake catalog answers and, in CI, a real PostgreSQL 16; the corporate server is first read on the work PC |
| Big Data Portal access requests | When the person lacks access to a table, Gemini prepares the request (`portal_request_access`) and the answer shows **Open the request form**; Settings → Portals has the **Access request form** (the answers given on every request, kept on this PC) and **Open the request page**. Wizard opens the catalog page in a visible window of its browser and fills those answers, and this request's, into the form's empty fields as it appears; the person checks every field and submits. Wizard never clicks, presses a key or submits, and its own portal steps still refuse every access request. [Decision](docs/decisions/2026-10-28-bdp-access-requests.md) | Tested in a real Chromium against a simulated catalog form (labels, table rows, select, password left alone, no submit until the person's click); the real catalog is first used on the work PC |
| Big Data Portal (work PC) | Two applications, each with its address in Settings → Portals ([decision](docs/decisions/2026-10-28-bdp-information-catalog.md)): the **information catalog**, where Gemini finds tables, and **Superset**, where it queries them, both read live in the person's own Wizard browser (row above). Discovery ([decision](docs/decisions/2026-10-12-bdp-superset.md)): Task 40: `.\docs.ps1 bdp-check` checks BDP's Superset with anonymous requests (reachable, sign-in route and gateway, REST API, version) and summarises the database list the user saves from their signed-in browser (engines, DML, background queries); the task also records the catalog's address, product and request route; Gemini CLI writes the findings and the questions for the BDP team | Tested against simulated Superset servers, and in a real Chromium with a catalog and Superset on two hosts; the real ones are first checked on the work PC |
| PostgreSQL, live | `wizard_query_postgresql`: Gemini writes its own SELECT (joins, window functions, CTEs) against whatever the read-only account can read, guided by the task 18 dataset notes. One statement per call, as a subquery, in a READ ONLY transaction that is rolled back, on a fresh connection; at most 500 rows back. A query on a table or view that does not exist comes back with readable relations of a similar name and the other databases that have it. Answers are labelled "Live" and the drawer shows the SQL | Tested against fake sessions and, in CI, a real PostgreSQL 16 (analysis queries, and every write attempt refused under an account allowed to write); the corporate server is first queried on the work PC |
| Attached files | Upload or "From this PC" (in place, for protected files): PowerPoint, Excel, Word, email, CSV; Gemini reads them with `wizard_read_attachment` and filters, groups and totals every row of a sheet with `wizard_query_attachment` (up to 300,000 rows); evidence is `USER_PROVIDED`. **Edits:** asked to change an attached workbook, Gemini calls `wizard_edit_attachment` (set values and formulas, insert/delete rows and columns, delete rows that meet a condition, sort, format, widths, find and replace, sheets, freeze, filters) and the edited copy appears under the answer with **Download** (on the person's own PC, Wizard saves it into Downloads itself, written by Excel so protected workbooks open, then **Open**); Excel does the edit on the work PC (charts, pivots and NASCA protection kept), openpyxl elsewhere; the original is never written. [Decision](docs/decisions/2026-10-23-edited-attachments.md) | Working; Office conversion and Excel edits need the work PC (plain files convert and .xlsx/.xlsm edit anywhere) |
| ASAP MicroStrategy Library REST client | Groundwork only, not validated against the tenant; the ASAP report catalog stays NAVIGATION_ONLY (ASAP is read live in the Wizard browser instead) |
| Real platform documentation | `WIZARD_CONTENT_DIR` loads an internal wizard-content repo (template in `templates/content/`, Gemini CLI authoring commands, validator); real reports are navigation-only (PostgreSQL is queried directly, above) | Working; no real content yet |
| Corporate SSO | Trusted-header mode implemented for an SSO reverse proxy; not connected to a real IdP |
| Desktop app (WizardBar) | An always-on **Ask Wizard** tab at the top of the screen with the animated pixel wizard (he waves on hover, casts on a click, acts out the running step), Ctrl+Alt+W, files dropped on the tab attached to the question, and a panel that slides down with the compact view (`/quick`) in WebView2. A tray menu, a notification when an answer arrives, and self-update. It runs and watches the local service (`run.py --desktop`, code-assist runtime). Sessions renew while in use, and after a long sleep the page signs in again by itself (no reload needed). One per-user `WizardSetup.exe` (Inno Setup, like Scribble) with portable Python. CI builds it on Windows and publishes it to `desktop-continuous` on `main`, mirrored to the `desktop-download` branch for proxies that time out on release downloads. [docs/desktop.md](docs/desktop.md) | Service, `/quick` and installer tested (unit, browser, Windows CI smoke install); WizardBar compiles; its windows first run on a work PC |
| Knowledge base from a private GitHub repository | `WIZARD_KB_REPO` + a read-only fine-grained token, always on the company's GitHub Enterprise Server (`https://github.sec.samsung.net/api/v3`, built in, not a setting). Syncs at start-up and every 30 minutes with a conditional request, validates each commit before using it, keeps the previous version, and restarts onto a new one when idle. Users never see the repository | Tested against a fake GitHub; the real repository is first synced on a work PC |
| Systems stage | Every answer shows Wizard at work: the pixel wizard in a magic circle, with each system this person can use around him in an orbit, each with its own logo (AI Team Database, the knowledge base, ASAP, GSCM, NERP, attached files, Metronome with its own metronome logo, Orchestra with its sound wave, and any other new platform such as BDP with a monogram). A system lights up and streams pixel data into the circle while Gemini reads from it (the caption says "Searching the catalog of ASAP" for a catalog search and "Reading GSCM in your browser" for a live portal read, and "Cross-checked" counts only systems something was read from), and the wizard acts out the step (reading, searching, calculating, charting, writing). The caption shows the actual SQL, report and filters, then the result, which also floats up from the wizard ("+ 120 rows"). Counters, a click-through list of each system's calls with evidence, and badges are earned from the run itself. When the answer lands live he hops with pixel confetti, then the stage folds into a strip of the systems used. A bar pinned to the top keeps him in view while a long answer streams. Driven only by observed tool calls | Unit and browser tests; checked in screenshots mid-run, writing and landing |
| Settings pane, Update button | ⚙ Settings on a person's own install: Gemini project and allowed domains, the knowledge base, the read-only database and the proxy. It shows where each value comes from, keeps secrets write-only (DPAPI), has **Test connection** for the knowledge base and the database, and restarts by itself to apply. The model is Gemini 3.8 Flash for everyone, with Gemini 3.1 Pro preview as the fallback when Google has no capacity for Flash and back again, as in Gemini CLI (no picker; only the company file, `.env` or the environment can change them). **Update** installs the newest release through WizardBar | API unit-tested; pane checked in a browser |
| Knowledge-base publishing (work PC) | Task 50 and `.\docs.ps1 kb-publish` / `kb-check` / `provision`. One commit through GitHub's API (no git): notes and catalogs only, validated, private repositories only, changed files only, deletions followed, dry run first | Tested against a fake GitHub with a real tree |
| Provisioning file | `wizard.provision` (made with `scripts/make_provision.py`) carries the company settings and credentials: the knowledge-base token, the read-only PostgreSQL account, the Gemini project, `WIZARD_GOOGLE_DOMAINS`. Imported once, with secrets kept by DPAPI; never in the public installer | Unit-tested |
| Brain page (`/brain`) | A page of its own beside the app (the chat is unchanged) for showing Wizard to people: everything it knows as one living picture. The pixel wizard in the middle, the systems this person can use around him (with the reports catalogued in each and the tables the database account can read), and each knowledge area as a cluster of notes joined by their links, pulses running along them. Hover a note for its summary and status. The news table an automation fills (`news`, or `WIZARD_NEWS_TABLE`) is read with fixed read-only queries: total, articles per week by publication date, categories, the latest headlines. N (or the tour's news step) plays a demo arrival: one of the table's own articles slides in at the top as just arrived, nothing written and no count moved. A presenter tour built from the counts it read (→, ←, Esc, F, N). Example notes show as EXAMPLE CONTENT; the motion is decoration. [Decision](docs/decisions/2026-10-28-brain-page.md) **Simple / Advanced** (V): simple has no wizard, no counters and no motion; both give the latest news articles more room ([update](docs/decisions/2026-10-28-brain-page.md)) | Unit tests, real PostgreSQL 16 for the news queries, e2e; checked in screenshots over a synthetic 111-note knowledge base and 1,512 synthetic articles |
| Roadmap page (`/roadmap`) | A page of its own beside the app for showing Wizard to people: on the left what Wizard does today and the systems it reads, on the right the roadmap, one Friday at a time from 30 October 2026 (week 1, more portals: SC+ Global Dashboard and NERP BI Portal; weeks 2–3, PowerPoint slides; week 4, a richer knowledge base from meetings with the heads of business and each area's main PIC), each with its countdown and logos. → shows the next Friday, ← takes it back, F full screen. No data and no sign-in: the content is `apps/web/src/roadmap.ts` ([decision](docs/decisions/2026-10-28-roadmap-page.md)) | Unit, component and browser tested; seen at 1440×900 and 390×844 |
| Logo and character | A pixel-art wizard in Samsung colours, with a logo, favicon and the desktop app's icon (tray, taskbar, setup). He waves on the start screens, acts out each step on the systems stage and on the **Ask Wizard** button, hops when the answer lands and fizzles on a failure. Driven by observed run events only. Sprite sheet and atlas ready for gamification: [brand/README.md](brand/README.md) | Unit-tested; browser-checked in replay mode; the button drawn on Windows in CI |

## Desktop app (for the people who ask questions)

Run `WizardSetup.exe` from the [desktop-continuous release](https://github.com/datap0nd/wizard/releases/tag/desktop-continuous)
with the company's `wizard.provision` in the same folder. No admin rights are needed. An **Ask Wizard** tab appears at
the top of the screen, and Ctrl+Alt+W opens it from any app. Owner guide: knowledge-base repository, token,
provisioning file, updates. See [docs/desktop.md](docs/desktop.md).

If the download spins and then fails (some office proxies open github.com but time out on release downloads), take
[desktop-download.zip](https://github.com/datap0nd/wizard/archive/refs/heads/desktop-download.zip) instead: the same
installer from every release, served by `codeload.github.com`. Unzip it and run `WizardSetup.exe`.

## Work PC (install, test, update)

Same model as B2B: **only `setup.ps1` is needed**. Save it in an empty folder (e.g. `C:\Wizard`) and run it; it
downloads everything else from this public repository. No admin, git, pip or Node build. A GitHub token is optional
but recommended: `DG_GITHUB_TOKEN` in the environment or as a line in that folder's `.env`. Without one, GitHub limits
anonymous API calls per IP address, and an office network shares one.

```powershell
.\setup.ps1
.\start.ps1
```

Then `.\update_app.ps1` after every push to `main`. Documentation and checks are Gemini CLI tasks: in `C:\Wizard`, run
`gemini -m gemini-3.8-flash`, trust the folder when asked, and type `/wizard:tasks`. Full guide: [docs/workpc-setup.md](docs/workpc-setup.md).

## Quick start (Windows, development)

Prerequisites: Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node.js 20+.

```powershell
.\scripts\dev.ps1
```

That creates `.env` from `.env.example` (replay mode), installs dependencies, and starts the API on
<http://127.0.0.1:8770> plus the web app on <http://127.0.0.1:5173>. Sign in with a test identity and try the three
demonstration questions. Each identity has different source rights.

To serve the built web app from the API only: `.\scripts\dev.ps1 -ApiOnly` and open <http://127.0.0.1:8770>.

### Run with real Gemini (enterprise)

1. Install the CLI on the host: `npm install -g @google/gemini-cli@0.62.0` (or into `.tools/`, see below).
2. In `.env`: `WIZARD_AGENT_RUNTIME=gemini-cli` (or `code-assist`), `WIZARD_GEMINI_MODEL=gemini-3.8-flash`,
   `GOOGLE_CLOUD_PROJECT=<your organisation's Gemini project>`.
3. Start Wizard, sign in, open **Account → Sign in with Google**, sign in with *your own* enterprise account and paste
   the code Google shows. Wizard refuses an account whose email differs from the signed-in Wizard user.
4. Run the Step 02 spike with two people: `uv run python scripts/spike_two_users.py --runtime gemini-cli --user ... --user ...`.

Details, isolation findings and the decision checklist: [docs/gemini-runtime.md](docs/gemini-runtime.md).

## Verify

```bash
scripts/verify_all.sh --allow-blocked=live-parity
```

Layers: `uv.lock` current with `pyproject.toml`, spec/fixtures, secret scan, published contracts, lint, types, Python
unit/contract/integration/security tests, real-Gemini-CLI tests, eval-set schema, web types/unit/build, browser E2E,
live parity. It fails closed: a layer that cannot run is BLOCKED and fails the run unless allowed by name.
`python scripts/verify_spec.py` is the quick spec gate.

The real-CLI tests need the pinned CLI: `npm --prefix .tools install @google/gemini-cli@0.62.0`
(after `cd .tools && echo {"name":"wizard-dev-tools","private":true} > package.json`). Without it they report BLOCKED.

## Layout

```
apps/web/             React/TypeScript UI (Vite, Tailwind, Radix, ECharts) and Playwright E2E; /quick is the desktop panel
apps/desktop/         WizardBar (C#, .NET Framework 4.8, WebView2): the always-on button, panel, tray and updater
installer/            Inno Setup script for WizardSetup.exe
services/api/         FastAPI: sessions, run manager + SSE stream, reports, sources, Gemini account linking
services/agent/       Gemini CLI runtime, Code Assist runtime, replay runtime, Google OAuth, prompts
services/connectors/  Source contracts, entitlements, read-only tools, MCP stdio shim, ASAP Library REST client
services/checks/      Safe calculator and Check my data
contracts/            Source contracts, tool catalog, OpenAPI, run-event and report schemas
knowledge/            Retrievable business definitions (DRAFT_UNSIGNED until an owner signs)
fixtures/             SYNTHETIC data, identities, goldens, replay transcripts, fake CLI replies
tests/                unit, contract, integration, security, evals, parity
docs/                 Plan-step documents, decisions, runbooks, build report
scripts/              verify_spec, verify_all, fixture_reset, dev, spike_two_users, run_evals, ...
```

Start with [AGENTS.md](AGENTS.md) (rules for anyone changing this repo), [docs/architecture.md](docs/architecture.md),
[docs/platforms.md](docs/platforms.md) (how platforms, report catalogs and MCP servers fit together),
[docs/how-it-works.md](docs/how-it-works.md) (flowcharts) and [docs/documentation-guide.md](docs/documentation-guide.md)
(how the real platform documentation is written, with which model and prompts, and where it lives)
and [docs/issue-board.md](docs/issue-board.md).
