# Build report

The single running record the plan asks for: what is implemented, actual test output, operating mode and open
decisions. Update it with every change that alters behaviour.

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
