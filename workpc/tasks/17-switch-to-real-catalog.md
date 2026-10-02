# Task 17 — Switch Wizard to the real catalog

**Goal:** make Wizard show the real platforms and reports instead of its synthetic examples.
**Output:** `outbox\17-switch.md` · **Shareable:** yes, after redacting paths and emails.

Only do this task when task 15 ended with 0 errors **and** the user says yes. Explain first: with the real catalog,
Wizard's Gemini can find and explain real reports but cannot read their numbers yet (every report is navigation only),
and the synthetic demo questions will no longer have data.

## Steps

1. Ask the user for confirmation. Then add this line to `.env` in this folder (keep everything else unchanged):
   `WIZARD_CONTENT_DIR=content`. Make sure `.env` also has `WIZARD_AGENT_RUNTIME=gemini-cli` (replay cannot be used
   with real content).
2. Run the installation check (same command as task 00, step 3) and copy the output.
3. Tell the user to close the Wizard window and run `.\start.ps1`, then open the Sources tab to browse the catalog.
4. To go back to the synthetic examples, remove the `WIZARD_CONTENT_DIR` line and restart.

**Done when:** the check passes with `content` listed as the content folder, or the failure is recorded.
