---
id: reporting-conventions
title: How Wizard answers are read (evidence, data modes, checks)
status: DRAFT_UNSIGNED
owner: TBD - project owner
tags: [citation, evidence, data mode, synthetic, live, verified, check, uncertainty, report]
---
- Cite evidence ids such as [E2] beside numbers taken from a tool result; derived numbers cite their inputs.
- Data modes describe where data came from, not whether a conclusion is right: SYNTHETIC (invented test data),
  DATED_APPROVED_SNAPSHOT (an approved, dated copy), LIVE_VERIFIED (retrieval parity-checked against the source).
- A check (Check my data) is separate: CHECKED, NOT_CHECKED or DISCREPANCY. An unchecked figure is not wrong; it is
  simply not independently recomputed.
- When periods, markets, currencies or definitions do not line up, show the uncertainty instead of a single number.
