# Work-PC installation: portable runtime, pull-only updates, Gemini CLI task kit

**Date:** 2026-10-02 · **Owner:** project lead (proposed by the build agent) · **Status:** accepted for pilot testing

**Context.** Wizard must be tested on a corporate work PC where nobody can install Python packages, run a Node build
or hold a git checkout, and where Windows Application Control blocks some unsigned binaries. The B2B and
data-governance tools already install there with `setup.ps1` / `update_app.ps1` and a `DG_GITHUB_TOKEN`. Platform
documentation must be written on that PC, by Gemini CLI, because the source documents may not leave it.

**Options.** (a) Ask IT for a Python/Node toolchain; (b) a packaged executable (PyInstaller), which is unsigned and
likely blocked; (c) the B2B model: download the exact commit plus a pinned, checksummed portable Python and wheels.

**Decision.** (c).
- `setup.ps1` downloads `main` as a zipball through the GitHub API, `runtime.lock.json` / `dependencies.lock.json`
  pin python.org's embeddable CPython 3.13 and 17 wheels (only `none-any` and `cp313-win_amd64`), published as a
  `portable-…` release by `scripts/lock_portable.py --publish`. Every archive is SHA-256 verified.
- The web app ships prebuilt in `apps/web/dist/` with a source fingerprint checked by `verify_all.sh` (`web-dist`).
- Releases are immutable folders. `current.json` / `previous.json` select one. `run.py --check` must pass before a new
  release is selected:
  - start-up failure blocks it;
  - a Gemini CLI problem only warns.
- Settings and state live in the install folder: `.env`, `data\`, `content\`, `outbox\`. Updates only add missing
  `.env` keys.
- A local Owner identity (`WIZARD_LOCAL_USER_EMAIL`) with the user's real email and all platform rights is listed first
  in fixture mode, so the Google email-match rule works on a single-user test PC.
- The Gemini CLI configuration Wizard writes sets `context.fileName` to a name that never exists, so no `GEMINI.md` in a
  parent folder (the install folder has one for the task kit) can leak into the analyst's context. The `--check` probe
  verifies this with a planted marker.
- `workpc/` holds the Gemini CLI task kit:
  - `tasks/`, refreshed on every update;
  - `GEMINI.md` and `.geminiignore` (`data\` and `.env` are excluded);
  - the `/wizard:tasks` command.
  Shareable outputs go to `outbox\`; internal documentation goes to `content\`.

**Consequences.** Upgrading Python or a library means `lock_portable.py --publish` and committing the new locks
(`verify_spec.py` checks their hashes and wheel tags). The work PC never pushes; feedback returns as
`outbox\FEEDBACK-FOR-CLAUDE.md`, pasted by the user. Production hosting (shared server, SSO) remains a Step 15 decision.

**Evidence.**
- `tests/unit/test_workpc.py`.
- `tests/integration/test_gemini_cli_real.py::test_installation_probe_passes_and_ignores_parent_gemini_md`.
- The end-to-end install recorded in [build-report.md](../build-report.md).
