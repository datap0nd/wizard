# Issue board (plan steps 00–16)

One branch or reviewed ticket per step. Status as of 2 October 2026. "Done (synthetic)" means built and tested over
SYNTHETIC data; it is never a claim about live data.

| Step | Ticket | Status | What exists / what is next | Blocked on |
|---|---|---|---|---|
| 00 | Trusted baseline, agent-first rules, repo references | Partly done | New repo with AGENTS.md/GEMINI.md rewritten agent-first; [repo-references.md](repo-references.md); verify_spec + verify_all. **Next on the corporate workstation:** inspect the internal Wizard remote and `gemini/overnight-v1`, merge only reviewed scaffold pieces, protect the default branch, set up the approved CI runner | Corporate workstation access |
| 01 | Users and demonstration questions | Draft | [product-requirements.md](product-requirements.md), 30 draft eval cases | Owner and executive interviews |
| 02 | Two-user Gemini spike, deployment and data decisions | Ready to run | Both runtimes, per-user isolation, account linking, `scripts/spike_two_users.py`, [threat-model.md](threat-model.md), [gemini-runtime.md](gemini-runtime.md) | Two enterprise accounts on the intended host; IT approval of data route |
| 03 | Source discovery and qualification | Template ready | [source-register.csv](source-register.csv) (synthetic rows), [source-coverage.md](source-coverage.md) | Mosaic Q&As, GSCM help / IT VOC, NERP, Smart Switch, share owners |
| 04 | Semantic contracts and reference answers | Draft | Typed contracts, knowledge notes (unsigned), synthetic goldens, [metric-contract.md](metric-contract.md) | Owner sign-off; corporate reference answers in a private location |
| 05 | Application foundation | Done (synthetic) | FastAPI + React, run manager, SSE, SQLite store, health/ready, fixture reset, real Gemini CLI loop with mock MCP tools (offline) | Live model needs Step 02 |
| 06 | Executive presentation slice | Done (synthetic) | B2B-style UI, timeline, charts/tables, evidence drawer, report page, Check my data, Show sources, accessibility basics | Owner walkthrough |
| 07 | Open tool loop and optional verification | Done (synthetic) | 15 read-only tools, Check my data, calculator, eval set + runner, eval log | Live evaluation runs |
| 08 | Identity, evidence storage, report access | Partly done | Fixture + trusted-header identity, per-user Gemini state, rights on search/run/reopen, audit, retention expiry | Corporate SSO, approved store, retention approval |
| 09 | ASAP navigation and one verified probe | Groundwork | Explorer UI (navigation states), Library REST client, parity test (BLOCKED), [asap-implementation.md](asap-implementation.md) | ASAP IT route, one approved report, signed reference |
| 10 | Remaining CEO source connections | Not started | Adapter pattern + contracts ready | Step 03 field matrix, source grants |
| 11 | Live executive report qualification | Not started | — | Steps 09–10, signed goldens |
| 12 | Planner analysis | Done (synthetic) | Story fixtures and transcript; screening only | Live feeds incl. stock age/returns |
| 13 | Conquest | Done (synthetic) | Observed counts with coverage; decision-to-investigate framing | Live Smart Switch aggregates, incremental economics |
| 14 | Repeatable source onboarding | Template ready | [source-onboarding.md](source-onboarding.md); contracts generate tools without code changes | First real intake |
| 15 | Harden, deploy, operations | Draft | [deployment.md](deployment.md), [operations.md](operations.md) | IT host decisions, named operator |
| 16 | Release stack and executive pilot | Not started | verify_all fail-closed gate | All of the above |
