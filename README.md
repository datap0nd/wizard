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
| Web app (B2B design system): chat, live "What Wizard did" timeline, answers with evidence chips, charts/tables, evidence drawer, source explorer, dated report pages, Check my data | Working, browser-tested |
| Email an answer | The Email button on a finished answer opens an unsent Outlook draft: the question, the answer (tables kept, charts as their data), how long it took, data mode and check status, and the tables and reports the answer cites (table names read from the SQL). Without classic Outlook, or behind an SSO proxy, it downloads the same message as an `.eml` file. Wizard never sends mail and Gemini has no email tool | Tested with fake Outlook objects; real Outlook first runs on the work PC |
| Run limits | A run may take up to 30 minutes and 150 tool calls: backstops, not budgets. Wizard refuses a third identical call, tells Gemini to answer after three such refusals, and in the last 4 minutes closes the data tools, so a long run ends with an answer instead of nothing. "What Wizard did" shows when each step started and how long its tool took; a running answer shows a timer | Unit-tested |
| Relative dates | Every request starts with a calendar: today's local date, this and last ISO week with dates, the last 4 weeks, this and last month and quarter, year to date. A dataset's own calendar wins where its notes define one | Unit-tested |
| Agent runtime **gemini-cli**: Gemini CLI 0.62 headless `stream-json`, one isolated `GEMINI_CLI_HOME` per user, Wizard tools over MCP | Working end-to-end with the real CLI and offline fake model replies; needs a real sign-in to answer live |
| Agent runtime **code-assist**: the Code Assist API Gemini CLI uses, per-user Google sign-in (ported from Scribble `41ab532`) | Implemented; tested against a scripted Google fake; needs a real account |
| Agent runtime **replay**: recorded transcripts over synthetic data for CI and demos | Working; labelled REPLAY everywhere |
| Read-only tools: NERP, GSCM, ASAP (search, schema, run report) + catalog, knowledge (search, browse, read), attached files, PostgreSQL SQL, calculate, visual, Check my data | Working over SYNTHETIC fixtures with per-user report and market rights |
| Company knowledge | Notes in `content\knowledge\<area>\` to [the knowledge standard](templates/content/schema/knowledge-standard.md); section-level search, a browse index and read-by-id; draft/expert-checked/signed status shown to Gemini | Working; real notes come from the Gemini CLI tasks below |
| Documentation kit (work PC) | Gemini CLI tasks 20-25 collect chosen Outlook folders and files, convert them through Office (pywin32; NASCA files read in place), digest, plan and write the notes; tasks 30-31 build one HTML expert quiz per area and stakeholder and apply the answers. `.\docs.ps1` does the converting and checking | Tested with standard-library files, fake Office objects and the quiz page in a browser; real Office/Outlook first runs on the work PC |
| PostgreSQL data dictionary (work PC) | Task 18: `.\docs.ps1 postgres-catalog` exports every materialized view from the server's catalog over a read-only pg8000 session (structure, SQL, lineage, pg_cron refresh, light profile); Gemini CLI writes one `datasets/` note per view, with the catalog as the source of truth | Tested against fake catalog answers and, in CI, a real PostgreSQL 16; the corporate server is first read on the work PC |
| PostgreSQL, live | `wizard_query_postgresql`: Gemini writes its own SELECT (joins, window functions, CTEs) against whatever the read-only account can read, guided by the task 18 dataset notes. One statement per call, as a subquery, in a READ ONLY transaction that is rolled back, on a fresh connection; at most 500 rows back. Answers are labelled "Live" and the drawer shows the SQL | Tested against fake sessions and, in CI, a real PostgreSQL 16 (analysis queries, and every write attempt refused under an account allowed to write); the corporate server is first queried on the work PC |
| Attached files | Upload or "From this PC" (in place, for protected files): PowerPoint, Excel, Word, email, CSV; Gemini reads them with `wizard_read_attachment` and filters, groups and totals every row of a sheet with `wizard_query_attachment` (up to 300,000 rows); evidence is `USER_PROVIDED` | Working; Office conversion needs the work PC (plain files convert anywhere) |
| ASAP MicroStrategy Library REST client | Groundwork only, not validated against the tenant; ASAP stays NAVIGATION_ONLY for live use |
| Real platform documentation | `WIZARD_CONTENT_DIR` loads an internal wizard-content repo (template in `templates/content/`, Gemini CLI authoring commands, validator); real reports are navigation-only (PostgreSQL is queried directly, above) | Working; no real content yet |
| Corporate SSO | Trusted-header mode implemented for an SSO reverse proxy; not connected to a real IdP |

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

Layers: spec/fixtures, secret scan, published contracts, lint, types, Python unit/contract/integration/security tests,
real-Gemini-CLI tests, eval-set schema, web types/unit/build, browser E2E, live parity. It fails closed: a layer that
cannot run is BLOCKED and fails the run unless allowed by name. `python scripts/verify_spec.py` is the quick spec gate.

The real-CLI tests need the pinned CLI: `npm --prefix .tools install @google/gemini-cli@0.62.0`
(after `cd .tools && echo {"name":"wizard-dev-tools","private":true} > package.json`). Without it they report BLOCKED.

## Layout

```
apps/web/             React/TypeScript UI (Vite, Tailwind, Radix, ECharts) and Playwright E2E
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
