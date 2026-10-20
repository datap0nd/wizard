# 2026-10-20 — Recurring extractions as Metronome Flows owned by Metronome's Wizard user

**Owner:** project owner. **Status:** decided (20 October 2026).

**Context.** People want a table Wizard found for them (a live PostgreSQL query) emailed to them on a schedule.
Metronome (`datap0nd/data_governance`) already runs scheduled Flows and emails each run's file, with owners, failure
alerts, run history and a pause switch. AGENTS.md does not let Wizard send mail or write to company systems. The owner
creates a Metronome user named **Wizard**: every Flow Wizard sets up belongs to that user, never to the person who asked.
Only Wizard changes; Metronome is used as it is.

**Options.**
1. Wizard schedules and emails by itself. Rejected: Wizard runs on people's PCs, which sleep and shut down, and it
   would become a mail sender.
2. A Gemini tool that creates the Flow once the person says yes. Rejected: a model-driven write to another system.
   Source text could talk Gemini into scheduling data to someone.
3. Gemini prepares, the person confirms. A tool checks and test-runs the query and shows a card under the answer.
   The Flow is created only when the person presses **Create in Metronome**.

**Decision.** Option 3.
- **How it starts.** The person says it in a question ("send me this every Monday"), or picks a choice from **Make
  recurring** under an answer: every day, every Monday, the 1st of every month, or something else.
- **Few questions** (owner, 20 October 2026):
  - the file is always Excel;
  - it goes to the person's own address: the email they signed in with, without the `ax.` after the @
    (`name@ax.company.com` sends to `name@company.com`), unless they name other people;
  - it is sent at 08:00 Dubai time (Metronome's clock), unless they give a time.

  So Gemini asks only how often, and only when the person has not said or picked it. It rewrites fixed dates as dates
  relative to `CURRENT_DATE`, so each email covers the latest period. Then it calls `wizard_schedule_extraction`.
- **The tool** (`category: present`, like a chart: nothing outside Wizard changes):
  - checks the person's PostgreSQL right, the same right as `wizard_query_postgresql`;
  - checks the query is one statement;
  - checks the recipients: at most 20 (Metronome's limit), all in the company's domains (`WIZARD_GOOGLE_DOMAINS`,
    each also without its `ax.`, else the requester's own mailbox domain);
  - checks the schedule;
  - test-runs the query through Wizard's own read-only path, recorded as `LIVE` evidence;
  - stores a proposal (`R1`, `R2`, …) shown as a card.
- **The click** (`POST /api/v1/schedules/{id}/create`, same-origin, audited) is the only path to Metronome:
  1. `GET /api/me` with Wizard's client key must name the configured user (`WIZARD_METRONOME_USER`, default `Wizard`).
     A key signed in as anyone else, or as nobody, fails closed.
  2. `POST /api/flows/transform-script?target=python` uploads the extraction script Wizard generated.
  3. `POST /api/flows` creates an active Python-script Flow: "Produce a file" mode, an Excel file, the email step with
     the recipients, the schedule, and `owner_person_id` set to the Wizard user.
  Metronome has no SQL-query source, so a Python Flow carries the query. The proposal moves from `proposed` to
  `creating` before anything is sent. If Metronome may have received the request but did not confirm it, the proposal
  becomes `uncertain` and is never sent again by itself.
- **Who.** Metronome has no API tokens. It knows a caller by the client key in `X-Client-Key`, bound to a person in
  Users. Wizard holds one key (`WIZARD_METRONOME_CLIENT_KEY`, in the provisioning file, kept with DPAPI) signed in as
  Wizard. `scripts/metronome_link.py` binds a new key to the Wizard user once, on the Metronome host PC.
- **The generated script** runs on Metronome's worker with Metronome's own Python (psycopg2, openpyxl). It holds the
  query and its SHA-256, and refuses to run if either changed. It runs the query as a subquery in a READ ONLY session
  and transaction, rolled back, with statement and lock timeouts. It writes at most 100,000 rows. It connects with
  `WIZARD_EXTRACT_PG*` on the Metronome host when set, else Metronome's read-only `PG*` scanner account. It never uses
  `DG_UPLOAD_PG*`, the uploader.

**Consequences.**
- AGENTS.md lists a second exception to "no write or email tools". Wizard declares 21 tools.
- New settings: `WIZARD_METRONOME_URL`, `WIZARD_METRONOME_CLIENT_KEY`, `WIZARD_METRONOME_USER`. They are in the settings
  pane with **Test connection**, and in the provisioning file. Without them the tool says Metronome is not connected and
  the **Make recurring** button is hidden.
- The systems stage shows Metronome with Metronome's own logo while Gemini prepares a schedule.
- Metronome owns everything after the click: the Flow's runs, emails, failure alerts (sent to the Wizard user's email in
  Users), pausing and deleting. The Flow's name and its script's header say who asked and when.

**Residual risk.**
- Anyone holding the key can act as Wizard in Metronome. It is stored like the knowledge-base token and the database
  password.
- Metronome's sign-in also binds the linking PC's address to Wizard, for a browser there that has never chosen a user.
  A browser that has chosen keeps its own user.
- Recipients receive whatever the query returns at each run, whatever their own Wizard rights. The person who presses
  the button decides who receives it, as with the Email draft.
- The query was tested once, when it was proposed. A view that is later renamed, or that the Metronome account cannot
  read, fails the run, and Metronome alerts the Wizard user.

**Evidence.**
- `tests/unit/test_metronome.py`, against a fake Metronome over HTTP:
  - the client: the identity check, upload, create, and failure and uncertain outcomes;
  - the statement check;
  - the schedule rules;
  - the generated script, run with a fake database driver (the Excel file, the read-only session, the row cap, a changed
    query refused);
  - `scripts/metronome_link.py`.
- `tests/unit/test_schedule_tool.py`: the tool's rights, recipients, test run, evidence and proposal.
- `tests/integration/test_schedules_api.py`: the confirm and dismiss API end to end, and the **Make recurring** run.
- Web: the card, the button, the stage and the logos (`RunCard.test.tsx`, `stage.test.ts`).
