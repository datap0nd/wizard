# 2026-11-13 — Every setting in Settings; a run may take up to 10 hours

**Owner:** project owner. **Status:** decided (13 November 2026).

**Context.** The owner: "Wizard should have all its configuration settings in the settings pane. stuff like max time
total (Its 30m, should be able to go up to 10h)". Until now the run limits, Gemini's thinking, the attached-file limits,
the Brain page's news table and diagnostics could be changed only in `.env` or the environment, and a run's time limit
stopped at one hour (`WIZARD_RUN_TIMEOUT_S` at most 3,600).

**Decision.**
- **Settings has every setting Wizard reads**, except the install itself (folders, port, runtime, sign-in mode and the
  person's own email, set by the installer or setup), a shared server behind SSO (origin, cookies, identity header and
  proxies), the Google email check (a protection) and developers' tests. `test_every_setting_wizard_reads_is_in_the_pane`
  holds that list: a new setting is added to Settings or to the list, with why.
- **Runs** (new section): **Time limit per run** in minutes, 1 to 600 (10 hours; default 30), stored in seconds as
  `WIZARD_RUN_TIMEOUT_S`, which now accepts up to 36,000; **Tool calls per run**, 1 to 2,000 (default 150; up to 500
  before), since a run ends at whichever limit comes first; **Runs at the same time** (default 8); **Keep answer
  reports for** (days, default 30). They stay backstops, not budgets: Gemini is still told to wrap up and answer before
  the time limit. Each question, queued prompt and round of a task or portal map has its own limits; a task's or a map's
  round keeps its own smaller tool-call limit (100, 80).
- **Gemini:** Thinking (high, low, model default). **Company database:** the Brain page's news table and its database.
  **Attached files** (new section): the folders From this PC lists, the largest file, the time limit per file, and
  reading Office files with or without Office. **Diagnostics** (new section): diagnostics in the app, shown or hidden.
  The model and its fallback stay out (owner, 20 October 2026: Gemini 3.8 Flash for everyone).
- **The folders From this PC lists are this PC's own**: set in its Settings, never in a company file and never carried
  by **Export settings…** (`provisioning.PC_CHOSEN`). The run limits and the others travel with an export as before.
- A number is typed in the unit shown (minutes for a run's time limit) and checked against its bounds on Save; a value
  Wizard cannot load is refused and nothing is saved, as for every setting.
- **A long run keeps its Google sign-in:** the Code Assist route takes a fresh access token under the person's own sign-in
  before a step that would start with the old one nearly expired (Google's tokens last about an hour), and its step
  backstop grows with the tool-call limit (at least 200 steps, the tool calls plus 50).
- **The desktop does not undo a choice:** its start-up adds missing defaults to `.env` (diagnostics off); it no longer
  adds one the person set in Settings, which Save had taken out of `.env`.

**Evidence.** `tests/unit/test_settings_pane.py` (minutes up to 600, refused values, the reload, Save moving a value out
of `.env`, the export, attachment folders never in a company file or an export, the desktop default not put back, every
setting in the pane or on the list); `tests/unit/test_code_assist.py` (a run longer than the access token renews it once;
the step backstop); `apps/web/src/components/SettingsDialog.test.tsx` (the number field with its unit, choices in words).
