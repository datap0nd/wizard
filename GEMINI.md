# GEMINI.md — context for Gemini CLI sessions that develop this repository

This file is for **developers using Gemini CLI on the Wizard codebase**. It is not the prompt Wizard gives Gemini at
runtime; that is `services/agent/wizard_agent/prompts/system.md`, injected through `GEMINI_SYSTEM_MD` into each user's
isolated CLI home, where this file is never loaded.

Follow [AGENTS.md](AGENTS.md). In short:

- Agent-first: improve tools, descriptions and definitions; do not script the analysis.
- Tools are read-only and enforce rights/bounds inside the tool. No write, shell, SQL, URL or export tools.
- SYNTHETIC data only in Git. Never commit corporate data, credentials, tokens or `.env`.
- Run `uv run python scripts/verify_spec.py` and `scripts/verify_all.sh --allow-blocked=live-parity` before proposing a
  change, and report BLOCKED layers honestly.
- When testing Wizard's Gemini CLI runtime, use `--fake-responses` transcripts under `fixtures/gemini_fake/` instead of
  a live model in CI, and never point `GEMINI_CLI_HOME` at your own home for a multi-user test.
