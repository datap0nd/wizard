# Build report

The single running record the plan asks for: what is implemented, actual test output, operating mode and open
decisions. Update it with every change that alters behaviour.

## 2026-10-06 (later) — Live PostgreSQL reports and totals over attached spreadsheets

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
contracts, lint, types, python-tests (206 passed), gemini-cli (4 passed; the real CLI accepts all 19 tool schemas),
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
