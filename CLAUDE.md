# CLAUDE.md

Read and follow [AGENTS.md](AGENTS.md). It holds the repository rules (agent-first design, read-only tools, per-user
Gemini identity, honest data modes, no corporate data in Git) and the verification commands.

**Every change to Wizard ships: merge to main and release, without being asked** (owner, 20 Oct 2026, restated: "I
never want to say this again"). For every change, once the checks pass:

1. Merge the work branch into `main` (bring `main` in first and resolve conflicts) and push `main`.
2. That push releases: the `desktop` workflow builds `WizardSetup.exe` and publishes it to the `desktop-continuous`
   release, which the in-app Update installs. Confirm it: the `desktop` run for that commit succeeded, and
   `https://github.com/datap0nd/wizard/releases/download/desktop-continuous/wizard-desktop.json` names that commit.
3. If the release did not publish (a failed run, a newer build already there), fix it and push again. Never stop at a
   branch, or at `main` without a release.

Do not ask whether to merge or release, and do not wait to be told.

Quick commands:

```bash
uv sync
uv run python scripts/verify_spec.py
uv run python -m pytest tests            # never the pytest.exe shim on Application-Control PCs
npm --prefix apps/web run typecheck && npm --prefix apps/web test
scripts/verify_all.sh --allow-blocked=live-parity,postgres   # CI runs PostgreSQL, so it allows only live-parity
```
