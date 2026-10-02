# Repository references reviewed for Wizard (Step 00)

Reviewed on 2 October 2026 from local checkouts on the development PC. Nothing was copied wholesale. Patterns were
re-implemented to fit the agent-first design; licences are the owner's own repositories unless noted.

## B2B — `datap0nd/b2b-local-data` (`Documents/ChatGPT/B2B Project`, HEAD `9bdcd74`)

What it is: local Qwen questions over a Salesforce extract. The model emits a validated query plan and a deterministic
engine executes it (the prescribed-pipeline style Wizard deliberately does not use).

Reused as **visual and interaction reference**:

- Design tokens (warm page `#f5f4f0`, white panels, cobalt accent `#315bd6`, Inter, 16px card radius, soft shadow): copied
  into `apps/web/src/styles.css`, extended with amber "synthetic" and teal "verified" signals.
- Layout and behaviour: collapsible history sidebar grouped by date, composer (Enter submits, Shift+Enter newline, IME-safe),
  follow-the-latest scrolling, result card with accent top border, Chart/Data toggle, evidence-first details, freshness
  signals, Radix dialog/menu/tooltip primitives, ECharts SVG rendering with `aria` labels.
- Engineering habits: closed request models (`extra='forbid'`), signed identity cookie, local-boundary middleware,
  SQLite with `PRAGMA user_version` migrations, an acceptance runner with an independent reference evaluator (becomes
  Wizard's `verify_spec.py` goldens + Check my data), CSV formula-guard thinking, NSSM Windows service install.

Not reused: the query-plan contract and deterministic engine, the Qwen/OpenAI-compatible client, the portable
dependency installer (Wizard needs Node for Gemini CLI anyway; packaging is decided in Step 15).

## Scribble — `datap0nd/scribble` (`Documents/ChatGPT/Scribble`)

The **working Gemini enterprise sign-in** the owner pointed to:

- Built on 18 Aug 2026 in the pre-rename (AI365) history, which survives only in the local `continuous` tag. It never
  went through a PR: `3c852a7` "Add Gemini provider with browser-based Google account sign-in", `6d48b52` "Fix Gemini
  HTTP 500: resolve the project the way Gemini CLI does", `d81746b` "Add a Google Cloud project field to Settings for
  enterprise Gemini onboarding", plus capacity/thought-signature fixes.
- Last working revision before it was gated: **`41ab532`** (27 Aug). `b0889a4` "Streamline endpoint setup and disable
  direct Gemini" did not delete it; it put direct Gemini behind a `SCRIBBLE_DIRECT_GEMINI` build flag.
- Ported to Python in `services/agent/wizard_agent/google_oauth.py` and `code_assist.py`: Gemini CLI's installed-app OAuth
  client and scopes, PKCE, `loadCodeAssist`/`onboardUser` project resolution with `GOOGLE_CLOUD_PROJECT`, SSE
  `streamGenerateContent`, `thoughtSignature` echo, 429 backoff honouring `retryDelay`, and the "never call with an empty
  project" rule. Changed for a web app: user-code redirect instead of loopback, a per-user token store, an email-match
  check, no silent fallback to `~/.gemini/oauth_creds.json` (Scribble read the machine user's CLI login, which would be a
  shared login on a server).
- Also noted: a hand-written C# MCP client (`Chat/McpConnection.cs`), which supports hand-rolling the MCP stdio server.

## data_governance / Metronome (`projects/data_governance`, `Documents/ChatGPT/Metronome*`)

- A Gemini CLI **extension** (`integrations/metronome-gemini`) with Node MCP servers (`@modelcontextprotocol/sdk`),
  `readOnlyHint`/`destructiveHint` annotations, `isError` tool errors, and a TOML policy file with `ask_user` rules.
  This informed Wizard's policy file and tool annotations. Its installer resolves `gemini.cmd` on Windows; Wizard avoids
  `.cmd` for safety (see [gemini-runtime.md](gemini-runtime.md)).
- Per-user state under `GEMINI_CLI_HOME` (`settings.mjs`) and treating an unexpanded `${NAME}` as unset: adopted in the shim.
- No headless `stream-json` consumer existed in any repo; Wizard's parser is new and verified against CLI 0.62.0.

## Constraints carried forward

Credential handling (never in Git, never in browser responses), per-user entitlement checks, DLP (no corporate exports or
the blocked DOCX in Git), honest source labelling, and fail-closed verification are kept from the earlier scaffold.
The internal Wizard scaffold branch on the corporate workstation (`gemini/overnight-v1`) still needs reconciling there
(Step 00, on-site); see [issue-board.md](issue-board.md).
