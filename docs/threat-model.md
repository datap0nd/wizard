# Threat model (Step 02 draft)

Scope: Wizard web app and API on the pilot host, the per-user Gemini runtimes, MCP shims, source adapters, and the
store. Method: assets → entry points → threats (STRIDE-style) → controls → residual risk. Status: draft for IT/security.

## Assets

Source rows and reports (confidential business data); per-user Gemini credentials; session cookies; run tokens;
saved reports and evidence; audit log; the session-signing key.

## Data flow

Browser ⇄ Wizard API (HTTPS via the corporate proxy) → runtime (CLI subprocess or Code Assist HTTPS to Google) → MCP shim
(stdio) → Wizard internal API (loopback) → tool registry → source adapters (live: HTTPS to NERP/GSCM/ASAP) → store.
Model inputs (questions, tool results) leave the host for Google under the user's enterprise entitlement: the
processing region and data-classification approval are **OPEN** decisions for IT/security.

## Threats and controls

| Threat | Example | Controls in place | Residual / open |
|---|---|---|---|
| Spoofed user | Forge a session or SSO header | HMAC cookie (HttpOnly, SameSite=Strict, Secure on HTTPS); SSO header accepted only from allowlisted proxy IPs | Real IdP integration and header hardening at the proxy (Step 08) |
| Shared Gemini login | Executives run under one cached login | Per-user `GEMINI_CLI_HOME` + forced file credential storage; per-user DPAPI token; email-match on link; no fallback | Confirm Google-side attribution in the spike |
| CSRF | Malicious page posts a question | Custom header + same-origin check on every state change; SameSite=Strict | — |
| Prompt injection via source text | NERP note tells the model to export data | Tools are read-only; no export/send/shell/URL tools exist; closed schemas; untrusted-data notice; CLI `<untrusted_context>` wrapping; test with an injected note | Model may still repeat injected text in an answer; answers are reviewed by humans |
| Tool escalation | Model calls a non-existent or other-scope tool | Registry allowlist; scope check per shim; CLI policy denies non-Wizard MCP; `tools.core = []` | — |
| Cross-user data access | Guess a report URL or evidence id | Owner check on every read; reopen re-checks current rights; 404 for others | Report sharing is not implemented (P1 decision) |
| Over-broad data | Model pulls everything | Row cap (500), tool-call budget, run timeout, entitlement filtering, aggregated Smart Switch only | Cost caps per user (Step 15) |
| Run token theft | Another local process calls the internal API | Loopback only; token bound to an active run and user; short TTL; never on argv or disk | Host hardening (service account, file ACLs) |
| Credential leakage | Tokens in logs or responses | Redaction of tokens in diagnostics; responses tested for secret patterns; secret scan in CI | Log retention policy (Step 15) |
| Windows command injection | User text through `gemini.cmd` | CLI launched as `node gemini.js`; prompt via stdin | — |
| Malicious dependency | Supply chain | Locked dependencies; no runtime downloads; minimal Python deps (no MCP SDK) | Dependency review in approved CI |
| Portal browser misuse | A page's text tells Gemini to export a report, or a link leads to another site | Portal tools act only on allowlisted hosts; other pages are stopped before they load; save/delete/export/share/send controls, downloads, uploads, passwords and code editors are refused in the tool; page text is marked untrusted; each step is shown to the person as a screenshot; 60 steps per run ([decision](decisions/2026-10-20-portal-browser.md)) | Refusals work from control names: a write control with a reading name could be clicked; company policy on automated browsing is OPEN ([questions](it-questions.md)) |
| Portal session theft | Another process uses the person's portal sign-in | The session lives in Wizard's own Edge profile in the person's data folder (Edge encrypts cookies with DPAPI), and its session cookies only in the Wizard service's memory; Edge is driven over a pipe, not a debugging port; nothing is copied from or to the everyday browser | Same-user malware can read any of the person's browser profiles, or the service's memory |
| Repudiation | "I never queried that" | Audit log of source tool calls, report opens, link/unlink (no row values) | Audit export and review cadence (Step 15) |
| Availability | Model or source outage | Clear failure states; interrupted runs closed on restart; concurrency caps | Monitoring/alerts (Step 15) |

## Data handling defaults

SYNTHETIC only in Git. Live rows are stored in evidence only within approved retention (default 30 days, configurable).
Aggregated Smart Switch and app usage only. No corporate exports, DOCX or raw logs in the repository.
Portal screenshots stay in the person's data folder, are served only to them, follow report retention and are deleted
with their conversation.
