# Gemini runtime: enterprise sign-in, per-user isolation and the Step 02 spike

Wizard supports two live routes with the same tool loop, so the Step 02 decision can be taken on evidence:

| | Route A — `gemini-cli` | Route B — `code-assist` |
|---|---|---|
| What runs | Gemini CLI 0.62.0 headless (`--output-format stream-json`) | Wizard's own loop over the Code Assist API (`cloudcode-pa.googleapis.com/v1internal`) |
| Identity | User's own CLI credentials inside their own `GEMINI_CLI_HOME` | User's own refresh token (DPAPI on Windows) |
| Tools | Wizard MCP stdio shims (asap, gscm, nerp, wizard) | Same registry, in-process function calls |
| Behaviour | Exactly the CLI's agent loop, retries, compression, safety | Same model and tools; Wizard's loop (thought signatures echoed, 429 backoff) |
| Origin | Plan default | Scribble's working Gemini integration, ported |

Both use the sign-in flow the open-source Gemini CLI uses (same OAuth client, scopes and PKCE), so whatever an
administrator has allowed for Gemini CLI applies. `GOOGLE_CLOUD_PROJECT` selects the enterprise (Code Assist
Standard/Enterprise) project, as for the CLI.

## Findings verified against the real Gemini CLI 0.62.0 (2 October 2026)

All observed by running the pinned CLI with `--fake-responses` (no Google call) and reading its published bundle:

1. **stream-json events** are `init`, `message` (assistant deltas), `tool_use`, `tool_result`, `error`, `result`
   (`gemini-cli-core` `output/types.ts`). Wizard maps them in `stream_json.py`.
2. **The OAuth token store is shared across homes unless forced to files.** By default the CLI keeps OAuth credentials
   in the OS keychain under one fixed entry (`gemini-cli-oauth` / `main-account`), which ignores `GEMINI_CLI_HOME`. Two
   executives under one Windows service account would silently share a Google login. With
   `GEMINI_FORCE_FILE_STORAGE=true` the CLI uses `<GEMINI_CLI_HOME>/.gemini/gemini-credentials.json` instead. Wizard always
   sets it, and tests assert it ([decision](decisions/2026-10-02-cli-credential-isolation.md)).
3. **`tools.core: []` removes every built-in tool.** The model is offered no shell, file, web or memory tools.
4. **Headless mode denies tools whose policy would "ask the user", including MCP tools with `trust: true`.** Wizard writes a
   policy file per home (`toolName = "*"`, `mcpName = <scope>`, `decision = "allow"`, plus a deny for every other MCP
   server) and passes it with `--policy`. Result: the model sees exactly Wizard's 15 tools as `mcp_<server>_<tool>`.
5. **The CLI blocks `PYTHONPATH` in MCP server env.** Wizard starts the shim with `cwd` set instead.
6. **`GEMINI_SYSTEM_MD` replaces the coding-agent system prompt** with Wizard's short analyst instructions.
7. **Gemini 3 thinking is already `thinkingLevel: HIGH`** in the CLI's requests. The plan's "highest supported thinking"
   needs no extra setting on route A. Route B sends `thinkingConfig.thinkingLevel = "HIGH"` (configurable).
8. **Settings support `$VAR` expansion**, so the run token reaches the MCP shim through the environment and is never
   written to disk or put on a command line.
9. **Calling `gemini.cmd` with user text is unsafe on Windows** (cmd.exe argument parsing). Wizard runs
   `node <bundle>/gemini.js` directly and sends the prompt over stdin.
10. **MCP output is wrapped in `<untrusted_context>`** by the CLI. This adds to Wizard's own untrusted-data notice.

## Sign-in flow for web users

Scribble used a loopback redirect (`http://localhost:<port>`), which only works when the browser runs on the host.
Wizard uses the CLI's "user code" variant (`authWithUserCode`): redirect to `https://codeassist.google.com/authcode`,
where Google shows a code that the user pastes into Wizard. Then:

1. Wizard exchanges the code (PKCE verifier kept server-side, single use, 10-minute expiry).
2. It reads the Google account's email and **refuses it unless it matches the signed-in Wizard user** (configurable,
   on by default).
3. It stores the refresh token in the user's own home (DPAPI on Windows) for route B.
4. It writes `oauth_creds.json` into the user's own CLI home for route A. The CLI migrates that file into its per-home
   encrypted store.

Unlink deletes both. Nothing is shared between users; a user with no link gets a clear "link your account" state.

## Step 02 spike — what to run on the intended host

Prerequisites: IT confirms the runtime may be used; Node 20+; `npm i -g @google/gemini-cli@0.62.0`; two consenting
enterprise users with Gemini entitlements; `GOOGLE_CLOUD_PROJECT` set; Wizard reachable by both users.

1. Each user signs in to Wizard (SSO or test identity mapped to their real email) and links Gemini via **Account**.
2. Run `uv run python scripts/spike_two_users.py --runtime gemini-cli --identities <file> --user <a> --user <b>`.
3. Repeat with `--runtime code-assist`.
4. In the Google admin console, confirm which account each request was attributed to and that history is not shared.
5. Record the result, latencies and the chosen route in a decision file under `docs/decisions/`.

The script writes `artifacts/step02-spike-*.json|md` with the checks: distinct homes, own credentials, distinct
sessions, linked email equals user email, tools called per user, operator home untouched. An offline harness check
(`--fake`) passes today. That proves the plumbing, not the enterprise route.

## Not proven yet (needs the spike)

- That the enterprise policy permits either route for a web-hosted analyst.
- Billing/attribution per user, quotas, and real latency at `gemini-3.8-flash` (the model id is configured, not verified).
- Corporate proxy, TLS inspection (`NODE_EXTRA_CA_CERTS`) and reachability of `codeassist.google.com` from users' PCs.

## Operator fallback

`scripts/gemini_user_login.py --user <id>` opens the interactive CLI inside one user's isolated home for a supervised
sign-in. Prefer the in-app link, which enforces the email match.
