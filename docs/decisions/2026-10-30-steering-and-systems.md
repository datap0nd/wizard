# 2026-10-30 — The person steers an answer while it runs, and chooses the systems a question may use

**Owner:** project owner. **Status:** decided (30 October 2026).

**Context.** The owner: "I want to be able to steer (for example I notice it's using a wrong table)" and "when making a
request, I should be able to select what systems I want it to access. I should be able to leave it on Auto as well."
Until now the only control during a run was Stop, which threw the work away; a follow-up carried only the earlier
question and answer, not the SQL or tables behind it; and Gemini was offered every tool on every question.

**Options.** Steering: a note that joins the running conversation; Stop and ask again; a note about one step (Not
this); a pause. Systems: a soft preference ("prefer these") or a strict choice ("only these"). The owner chose both
ways of steering (typed notes and Not this), corrections remembered per person, the knowledge base on by default when
systems are narrowed, and "only these" (strict).

**Decision.**
- **Notes while Wizard works.** While an answer runs, the question box takes a note. On the Code Assist connection
  (the desktop app's) Wizard runs the loop itself, so the note joins the conversation before Gemini's next step: after
  the tool results it was waiting for, a step's calls that had not run yet are skipped and Gemini decides again, and a
  note that arrives while Gemini writes its answer reopens the work. Nothing done so far is lost. On a connection that
  cannot take a note (Gemini CLI, which reads its prompt once; replay), the note stops the run and asks again with it.
  The page shows each note as waiting, then read by Wizard.
- **Not this, on a step.** Every step that read data (a query, a report, a search, a portal read) has Not this: wrong
  table, wrong filter, wrong period or something else, and optionally what to use instead. Gemini is told which step,
  with its SQL or report, and not to use or cite that step's evidence; an answer that cites it anyway carries a
  warning. After an answer, Not this asks again with the correction.
- **Follow-ups know what was read.** Each earlier answer in the prompt now carries what Wizard did for it (up to 15
  steps: the SQL, report or search, the result and evidence id, and the person's notes), and a stopped answer is part
  of the conversation.
- **Remembered notes, per person.** Remember under a note or a question keeps the person's own words (they can edit
  them first); Account → What Wizard remembers lists, edits and deletes them. They go into every question that person
  asks as their own instructions, never anyone else's. Up to 50.
- **The systems picker.** Next to the question box: Auto (as before) or only the systems ticked, from those the
  person may use (Metronome is not offered: it sends emails, it is not a source). The knowledge base comes on with the
  first system ticked; the person can untick it. Attaching a file switches Attached files on. The choice holds for the
  conversation's follow-ups, Check my data and Make recurring; a new conversation starts on Auto. The answer card says
  "Only: ...", and the systems stage dims the ones switched off.
- **Strict, inside the run.** Gemini is offered only the chosen systems' tools; the run refuses a call to a switched-off
  system (`system_off`), on both the in-process and the MCP path; the source list and the search across every catalog
  list only what is on, and Check my data does not re-run a switched-off source. Gemini can ask for a system with
  `wizard_ask_for_system`, which only shows the person a button ("Switch on GSCM and continue"). Changed during a run,
  the choice applies at once: a system switched on brings its tools at Gemini's next step, and one switched off keeps
  its tools in the list (earlier calls stay valid) but they refuse.

**Consequences.** This is the person choosing, not the application routing: Gemini still decides which of the systems
that are on to consult and how (agent-first). The tool catalog grows to 23 tools; `wizard_ask_for_system` writes
nothing. New events (`steer`, `steer_read`, `systems_changed`, `system_requested`) are in the run-event contract; a
report records the systems, the notes and the evidence marked Not this. `runs.systems` and the `memories` table are
added without a schema version change, so an older release still opens the database.

**Evidence.** `tests/unit/test_steering_and_systems.py`, `tests/integration/test_steering_api.py`,
`apps/web/src/components/Steering.test.tsx`, and the browser tests "the systems picker limits a question..." and "Not
this on a step of a finished answer...". Live notes were also seen in Chromium against a scripted runtime that takes
notes as Code Assist does; the real Code Assist route is first steered on a work PC.
