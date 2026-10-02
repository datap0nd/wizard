# 2026-10-02 — Build two Gemini runtime routes; choose by the Step 02 spike

**Owner:** builder, with identity/model IT. **Status:** both built; choice pending the spike.

**Context.** The plan defaults to Gemini CLI under per-user isolated sessions, with a per-user OAuth/enterprise API route
as the fallback if CLI sessions are not an approved web integration. The owner noted that Scribble authenticated to
Gemini successfully in an earlier revision.

**Options.**
1. Gemini CLI headless (`stream-json`), one `GEMINI_CLI_HOME` per user, Wizard tools over MCP.
2. Code Assist API (what Gemini CLI itself calls) with each user's own Google token, Wizard's loop, same tools.
3. Vertex AI / enterprise model API with a service identity. Rejected for now: loses the per-user enterprise entitlement
   the plan requires.

**Decision.** Implement 1 and 2 behind one runtime interface, sharing the tool registry, evidence capture and events.
Route 2 ports Scribble's `GeminiCodeAssistGateway` and `GoogleSignInFlow` (commit `41ab532`) to Python, switching to the
CLI's user-code redirect for remote browsers and adding an email-match check. Pick the default after the spike on the
intended host.

**Evidence so far.** Route 1 runs end to end with the real Gemini CLI 0.62.0 and offline fake model replies (tests in
`tests/integration/test_gemini_cli_real.py`). Route 2 passes against a scripted Google fake. Neither has used a real
enterprise account yet.
