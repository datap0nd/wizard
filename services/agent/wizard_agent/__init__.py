"""Gemini agent runtimes behind one interface.

- gemini-cli:   the Gemini CLI in headless stream-json mode, one isolated GEMINI_CLI_HOME per user, Wizard tools over MCP.
- code-assist:  the Code Assist API Gemini CLI itself uses, with the user's own Google sign-in (ported from Scribble).
- replay:       frozen tool transcripts for CI and offline demos; always labelled REPLAY, never presented as a model.

All three use the same tool registry, so tool rights, bounds and evidence capture do not depend on the runtime."""
