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
| Agent runtime **gemini-cli**: Gemini CLI 0.62 headless `stream-json`, one isolated `GEMINI_CLI_HOME` per user, Wizard tools over MCP | Working end-to-end with the real CLI and offline fake model replies; needs a real sign-in to answer live |
| Agent runtime **code-assist**: the Code Assist API Gemini CLI uses, per-user Google sign-in (ported from Scribble `41ab532`) | Implemented; tested against a scripted Google fake; needs a real account |
| Agent runtime **replay**: recorded transcripts over synthetic data for CI and demos | Working; labelled REPLAY everywhere |
| Read-only tools: NERP, GSCM, ASAP (search, schema, run report) + catalog, definitions, calculate, visual, Check my data | Working over SYNTHETIC fixtures with per-user report and market rights |
| ASAP MicroStrategy Library REST client | Groundwork only, not validated against the tenant; ASAP stays NAVIGATION_ONLY for live use |
| Real platform documentation | `WIZARD_CONTENT_DIR` loads an internal wizard-content repo (template in `templates/content/`, Gemini CLI authoring commands, validator); real reports are navigation-only until live adapters exist | Working; no real content yet |
| Corporate SSO | Trusted-header mode implemented for an SSO reverse proxy; not connected to a real IdP |

## Work PC (install, test, update)

Same model as the B2B tools: no admin, git, pip or Node build. With `DG_GITHUB_TOKEN` (Contents: read on this repo):

```powershell
mkdir C:\Wizard; cd C:\Wizard
$h = @{ Authorization = "Bearer $env:DG_GITHUB_TOKEN"; Accept = 'application/vnd.github.raw' }
Invoke-WebRequest https://api.github.com/repos/datap0nd/wizard/contents/setup.ps1 -Headers $h -OutFile setup.ps1 -UseBasicParsing
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
.\start.ps1
```

Then `.\update_app.ps1` after every push to `main`. Documentation and checks are Gemini CLI tasks: in `C:\Wizard`, run
`gemini -m gemini-3.8-flash` and type `/wizard:tasks`. Full guide: [docs/workpc-setup.md](docs/workpc-setup.md).

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
