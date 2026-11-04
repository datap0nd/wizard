# 2026-11-04 — A run ends with an answer; a question reads a mapped report through its map

**Owner:** project owner. **Status:** decided (4 November 2026).

**Context.** After the DB4009 task, the owner asked a question on the work PC ("Samsung sell-out by operator, compared
with the previous day"): "The GSCM appears to be mapped correctly. upon first test this is what I got." The run read the
database four times, read the GSCM guide (one saved script), then opened DB4009 and clicked towards its Configuration:
it looked for the Configuration button, listed buttons (236 rows), inspected the search panel, failed twice on its own
scripts (`W.nexacro.datasets` given the form object answered "no component at [object Form]"; a Dataset read as
`undefined`), and listed the form's datasets. Each model step took about two minutes, so with four minutes kept back
the first refusal ("time nearly up", at 28:14) left room for one more step, and Gemini spent it on another call. The run
was cut off at 1,800 seconds with no answer.

Three causes, the first one Wizard's own:
1. The system prompt named DB4009's Configuration path (Configuration → Sales → Sales → ORG Sales) and said to open a
   report's Configuration when its views did not show a breakdown. A question followed it, instead of the map's script.
2. A refusal near the time limit is a tool error Gemini may ignore; nothing made the last step an answer, and the time
   kept back did not grow with slow steps.
3. The helpers took only a path, and read no Dataset a form keeps for itself (a search's input).

**Decision.**
- **The last step is the answer.** Before each step the Code Assist route asks Wizard whether the answer is due
  (`ToolBridge.answer_now`). It is due once a question has been told to stop gathering data (time nearly up, repeated
  calls, or it asked the person), and in any run when about one of its slowest steps is left. That step is sent with the
  tools declared but not callable (`toolConfig.functionCallingConfig.mode = NONE`) and a line saying why, so Gemini
  writes its answer; a call written anyway is answered "no more tools" and not run. A task or a mapping round may still
  save its map and notes after research closes; only its last step is held to its final message.
- **Time kept back grows with slow steps.** Each step's time, Google's waits included, is reported
  (`ToolBridge.step_took`). Research closes when less than two of the slowest steps and a margin are left (at least
  the old four minutes, at most a third of the run).
- **A question reads a mapped report through its map.** The prompt and the GSCM guide say: in a question, a report the
  map reads with a saved script or a proven request is read that way in one portal_run; clicking through screens or
  Configuration is mapping work. When the map holds no proven way to the breakdown a question needs, Gemini asks the
  person before a long live read. The map's index names each report's script. A portal_run whose own steps name such a
  report (by menu id) gets the script or the proven request back in its result, or in its error (not in a task, which
  may be mapping it).
- **Helpers.** `W.nexacro.datasets(form)` takes the form's path or the form itself and lists, after the bound Datasets,
  the form's own ones (`bound: false`); `W.nexacro.read(name)` finds a Dataset in the application, the report forms or
  an open pop-up, and says which name it could not find, or what it was given instead of a Dataset. A portal_run that
  stopped part-way shows why on its step.

**Addendum, the same day.** The owner: "system prompt is in the responses now sometimes". After a question to the person,
an answer began with lines of instructions Gemini wrote itself ("Explain what the options mean for the answer … Do not
apologize or thank them …"), carried on from the line Wizard had added to the turn it answered ("You asked the person a
question: write it now…"). Now: asking the person alone does not make the answer due (its tools already refuse
research, and Gemini ends its turn with its question, as before); and when the answer is due, why goes into that step's
system instruction, never into the turn Gemini answers.

**Consequences.**
- The Gemini CLI route runs Gemini's own loop: there, the refusals still steer it, and the run's time limit stays the
  backstop.
- Whether the DB4009 question is now one script call depends on the map holding the proven request and the script (the
  DB4009 task's steps 8 and 10). Its outcome is seen on the work PC.

**Evidence.** `tests/unit/test_code_assist.py` (a due answer sends tools off with the reason; a call written anyway is
not run); `tests/unit/test_run_bounds.py` (the window grows with slow steps; a question's answer is due after a refusal;
a task may still save until its last step); `tests/unit/test_precise_maps.py` (a mapped report's script or proven
request named back; nothing for an unproven report or in a task; the index names the script);
`tests/integration/test_portal_browser.py` (a form given as itself, its own Datasets read by name, clear errors).
