# In a question, a GSCM report with a saved script is read only through it

**Date:** 12 November 2026 · **Owner:** the Wizard owner

**Context.** The owner's review of a question run (Q1) on the work PC: 23–28 minutes per answer, 76 steps for Q1,
and figures that cannot be trusted. The map named the report's saved script, and the run read the report through its
own steps instead. The review also asked that the script's "params missing" error (`The script needs <names>.`, no
values, no format) list each parameter with its example, so Wizard retries the script instead of abandoning it.
This is the second time the map's text alone has not held: on 4 November a question clicked through
DB4009's Configuration for twenty minutes while the map held its script
([decision](2026-11-04-runs-end-with-an-answer.md)). The prompt, the GSCM guide and `portal_run`'s "already mapped"
note already said to use the script.

**Options.** (1) More text in the prompt and the map. (2) Enforce it inside `portal_run` for GSCM, and make the
script's errors say how to send it again. (3) Enforce it for every portal.

**Decision.** Option 2 (owner: "Do 1. It's for GSCM only I believe", on the review's "hard enforcement in Wizard's
code").

- In a question (any run that is not a task or **Map** in Settings → Portals), `portal_run` refuses a call of
  Gemini's own steps on GSCM when they include an `evaluate` step and name a mapped report (its menu id or map id)
  whose saved script is kept on this PC or in the map. Nothing reaches the browser. The error (`use_saved_script`)
  names the script, each parameter with the value it was saved with, and the exact call:
  `portal_run(system="gscm", script="…", params=[{"name": "…", "value": "…"}])`, plus the report's proven request
  when it has one.
- Running the script itself is never refused, nor a `request` step (a proven request is a mapped route), nor
  `evaluate` steps that name no such report, nor a report without a saved script.
- A task run and a Map run may open and click through any report: that is mapping work. The tool context now carries
  the run's kind so a Map run is told apart from a question.
- Every portal: a script run with a parameter left out fails with `script_params_missing`, listing each missing
  parameter with its saved example, any name the script does not take, what the script reads and the call to send
  again. A script run that stops part-way says its parameters with their examples, so the next try fixes a value.

**Consequences.** This is the one place the code holds a route to an answer, against the agent-first rule's default
([decision](2026-10-02-agent-first.md)); AGENTS.md names it. A GSCM report whose saved script is broken cannot be read
by a question's own `evaluate` steps until a task or Map run fixes or replaces the script; the question says what the
script answered. A report opened by clicking its menu entry and then read by steps that never name it is not caught:
the check reads the call's own steps, as the "already mapped" note did.

**Evidence.** `tests/unit/test_precise_maps.py`
(`test_a_question_reads_a_gscm_report_with_a_saved_script_only_through_it`): the refusal comes before the browser,
names the call with the saved values, and lets through a report without a script, a request step, ASAP, a task run
and a Map run; the missing-parameters error and a stopped script's hint. `tests/integration/test_portal_browser.py`:
the missing-parameters error in a real Chromium run.
