# 2026-10-02 — Force per-home file credential storage for Gemini CLI

**Owner:** builder. **Status:** implemented and tested.

**Context.** Gemini CLI 0.62.0 stores OAuth credentials through `HybridTokenStorage`: the OS keychain by default, under
service `gemini-cli-oauth`, account `main-account`. That entry does not depend on `GEMINI_CLI_HOME`. On a host where
all users' CLI processes run under one Windows service account, every user would read and overwrite the same keychain
entry, so executives would share one Google login without any visible sign.

**Decision.** Every Wizard CLI process gets `GEMINI_FORCE_FILE_STORAGE=true`, which makes the CLI use `FileKeychain` at
`<GEMINI_CLI_HOME>/.gemini/gemini-credentials.json`. Wizard also sets `USERPROFILE`, `HOME`, `APPDATA`, `LOCALAPPDATA`,
`TEMP` and `TMP` inside the user's home, so nothing reads the service account's own profile. Credentials seeded by the
in-app link are written to that home only.

**Residual risk.** The CLI's file store derives its key from hostname + OS username, so it protects against copying the
file to another machine, not against another process of the same service account. Host ACLs on the data directory and a
dedicated service account are required (Step 15). Tests: `tests/unit/test_gemini_cli_runtime.py`,
`tests/integration/test_gemini_cli_real.py`.
