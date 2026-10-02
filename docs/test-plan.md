# Test stack and release gates (plan section 5)

`scripts/verify_all.sh` runs every layer below and fails closed. "BLOCKED" means the layer could not run here (no live
credentials, a policy-blocked tool, no browser) and fails the run unless allowed by name.

| Layer | Where | What it proves today |
|---|---|---|
| Specification and fixtures | `scripts/verify_spec.py` | Fixtures match generator + manifest and are SYNTHETIC; contracts validate and match CSV headers; goldens for all three stories re-derived independently (ranking, missing-spend market, screens, conquest rates); transcripts use published tools/reports and never claim ROI; knowledge has approval status; doc links resolve |
| Static quality, supply chain | `ruff`, `mypy` (CI), `tsc`, locked deps (`uv.lock`, `package-lock.json`), `scripts/scan_secrets.py`, `export_contracts.py --check` | Lint/type clean, no secrets or corporate document types, published contracts current |
| Tool and backend unit | `tests/unit` | Query bounds, sums vs balances vs rates, missing ≠ zero, market rights, navigation-only refusal, safe calculator, Check my data (MATCH / DISCREPANCY / PERIOD_MISMATCH / NOT_VERIFIABLE / replay CHANGED), CLI settings/env isolation, stream-json mapping, Code Assist loop with thought signatures and 429 retry, OAuth PKCE, DPAPI secret box, signed tokens, config validation, ASAP grid normalisation |
| Schema and MCP contracts | `tests/contract` | Tool catalog equals the published contract; all schemas closed; MCP stdio shim with a live server (initialize, list, call, errors, unknown method, expired run); run events and reports validate against JSON schemas; OpenAPI surface |
| Agent and API integration | `tests/integration` | Three stories end to end; SSE order and resume; report reopen; conversation restore; Check my data marks the original without rewriting it; evidence ids continue across follow-ups; one run per user; cancel; model outage; unlinked account never falls back; source outage disclosed; restart marks interrupted runs; two-user isolation of conversations, runs, events, reports, evidence |
| Real Gemini CLI (offline) | `tests/integration/test_gemini_cli_real.py` (marker `gemini_cli`) | CLI 0.62.0 calls Wizard tools via MCP; model sees exactly the 15 Wizard tools and Wizard's system prompt with thinking HIGH; per-user homes; no blocked env |
| Frontend unit and browser E2E | `apps/web/src/*.test.ts`, `apps/web/e2e` (desktop + narrow) | Event reducer, citation parsing, formatting; three questions in the browser; timeline, evidence drawer rows, report reopen after reload, Check my data, prompt-injection callout, cross-user report link refused, entitlement-filtered source explorer, keyboard path |
| Security and adversarial | `tests/security` | Session required; CSRF header and same-origin; forged cookie; security headers; internal API token, active-run and cross-user checks; scope check; injected tool call refused; no secrets in responses; Google account email match and single-use sign-in state; per-user token storage; repository secret scan |
| Evaluations | `tests/evals/cases.json` (30 draft), `scripts/run_evals.py` | Schema test in CI; live runs produce a review sheet for the owner. Failures go to [eval-log.md](eval-log.md) |
| Live source parity | `tests/parity` (marker `live`) | BLOCKED until an approved ASAP route, report and signed reference exist |
| Performance, availability, cost | not yet automated | Measure on the pilot host (Step 15/16): p50/p95 time to first event and to full report, concurrency, outages, cost ceiling |
| Operations and recovery | [operations.md](operations.md) | To be rehearsed on the pilot host |
| Human UAT | — | Step 16 |

## Non-negotiable release scenarios and where they are covered

1. Two executives' Gemini sessions, tool calls and source rights stay separate — `test_isolation_and_failures.py`,
   `test_gemini_cli_runtime.py`, `test_boundaries.py`, `scripts/spike_two_users.py` (live: BLOCKED until Step 02).
2. Paraphrased CEO question answered from real tool data, not a script — needs a live model (evals `ceo-02..05`).
3. SA/AE/EG/MA fixture gives one numeric reference with missing spend exposed — `verify_spec.py`, goldens, E2E.
4. Check my data finds an altered figure or mismatched period — `test_checker.py`.
5. An adversarial report cannot grant itself new tool actions — `test_boundaries.py`, `test_tools.py`, E2E.
6. A user cannot retrieve another's restricted report — integration + E2E.
7. Source outage disclosed — `test_source_outage_is_disclosed`.
8. ASAP parity uses REST rows, not navigation — `tests/parity` (BLOCKED).
9. Model outage shows a clear failure state — `test_model_outage_is_a_clear_failure`.
10. Backup/rollback on the selected host — Step 15 rehearsal (not started).
