# 2026-10-02 — Agent-first design

**Owner:** project owner. **Status:** decided (plan revision of 2 October 2026).

**Context.** The earlier scaffold prescribed fixed intent parsing, deterministic rankings and model-written prose around a
precomputed result (the B2B pattern). The owner wants Gemini to behave as it does in the CLI: free to choose tools,
compare, revisit and ask follow-ups.

**Decision.** Gemini is the analyst and orchestrator. Wizard provides informative read-only tools, retrievable
definitions, identity, tool-level rights and bounds, evidence capture, streaming, an optional Check my data tool and
dated reports. No intent router, scripted tool order, mandatory verifier or hidden deterministic pipeline. Targeted
checks or rules are added only after a measured failure or an owner-signed metric requires them.

**Kept from the scaffold.** Credential handling, source entitlements, DLP rules, honest source labelling, fail-closed
verification.

**Consequences.** Answer quality is evaluated (eval set, owner review) rather than guaranteed by construction; the
system protects rights and records evidence so every claim can be reviewed; data mode and check status stay separate.
