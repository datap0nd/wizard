# 2026-10-23 — Recurring briefs: the analysis as a newsletter email, and a Recurring tab synced with Metronome

**Owner:** project owner. **Status:** decided (23 October 2026). Builds on
[2026-10-20 Recurring extractions](2026-10-20-metronome-recurring-extractions.md), whose rules stay.

**Context.** The owner tested a recurring Flow: creating it in Metronome worked, but "the file received sucked". People
should get the same analysis by email (charts, data and what the data says), well structured, "a little newsletter they
decided to receive on a topic on a weekly basis". They also want a **Recurring** section in the sidebar.

Three facts shaped the design:
- Wizard's charts are rows Gemini types into `wizard_render_visual`, not queries, so an answer cannot simply be re-run.
- Gemini runs under each person's own sign-in (AGENTS.md). At 08:00 on a Monday their PC may be off, and no shared
  login may stand in.
- Metronome's Flow email had a fixed body ("Flow file"), though its Outlook sender already sends inline images.

**Options for the words in each email.**
1. **The numbers fill in the words.** At setup Gemini chooses what is worth saying; each run, rules write the sentences
   from the new rows. No AI at send time.
2. **Gemini writes each issue.** Reads like an answer, but needs a Gemini identity on Metronome's host (a new exception
   to per-user sign-in), and guardrails that check every number it writes.

**Decision.** Option 1 for now (owner: "A for now"). matplotlib is installed on the Metronome host for the chart images
(owner: "already have"). The Recurring tab is synced with Metronome, and Delete turns the Flow off in Metronome rather
than deleting it (owner: "if you delete, that row gets put as inactive in metronome, no one can 'delete' stuff in
metronome without proper auth").

- **The brief.** `wizard_schedule_brief` replaces `wizard_schedule_extraction`. A brief is a title, an optional period
  query and up to eight sections in reading order, each with its own query whose dates move with `CURRENT_DATE`:
  - **numbers**: up to four key-number tiles from the query's first row, with the change against the previous period;
  - **chart**: a bar chart (categories, optionally this period against the last with each row's change) or a line chart
    (periods in order);
  - **table**: the first rows (up to 25); the Excel file has them all.

  "What moved" rules write sentences from each run's rows: `change`, `largest`, `smallest`, `biggest_rise`,
  `biggest_fall`, `rose`, `fell`, `above`, `below`, `record_high`, `record_low`. A rule with nothing to say (nothing
  fell) writes nothing. Rules marked `lead` open the email ("In short"). The rules say what moved, never why.
- **The tool** keeps every check of the 20 October decision (rights, one statement per query, recipients, schedule).
  It test-runs every query through Wizard's read-only path (each one `LIVE` evidence) and refuses a brief whose
  sections name columns their queries do not return. The card shows the email drawn from today's test run.
- **One renderer, two places.** `wizard_connectors/brief.py` builds the email: 600 px tables with inline styles for
  Outlook, Wizard's colours, and charts drawn once as shapes. Wizard saves the shapes as SVG for the preview. The
  generated script carries a verbatim copy of the file and saves them as PNG with matplotlib on Metronome. The file
  uses the standard library only (a test enforces it). Without matplotlib a chart goes in as its table.
- **The script** runs all the brief's queries in one READ ONLY session and transaction, rolled back, with the same
  timeouts, accounts and row cap as before. It refuses to run if the brief no longer matches its SHA-256. It writes the
  Excel file (one sheet per section). When Metronome gives it `METRONOME_FLOW_EMAIL_DIR`, it also writes `body.html` and
  `chart-N.png` there.
- **Metronome** (`datap0nd/data_governance`, Python Flows can write their own email body): with the Email step on, the
  last script row gets `METRONOME_FLOW_EMAIL_DIR`. The Email step sends `body.html` with its `cid:` images inline and
  the Excel file attached, and adds a footer naming the run, the Flow and its owner. A body that breaks a rule (size,
  image names, missing or linked files) falls back to the standard message, and the run's email detail says why. An
  older Metronome sets no variable, so the script writes only the Excel file, as before.
- **The Recurring tab** lists the person's briefs that reached Metronome, newest first. Each time it opens it asks
  Metronome for each Flow (`GET /api/flows/{id}`, `GET /api/flows/runs?flow_id=`): on or off, next and last run, and
  recent runs with their email outcome. A Flow turned off in Metronome shows **Off in Metronome**; one Metronome no
  longer has shows **Not in Metronome**. When Metronome cannot be reached the tab still lists what Wizard knows and
  says so. A brief stays listed after its conversation is deleted, because its Flow keeps running.
- **Delete** asks once, then calls `PATCH /api/flows/{id}/enabled` with `enabled: false`, after the same check that
  Wizard's key is signed in as the Wizard user. Metronome allows only a Flow's owner or the host PC to change it
  (`require_flow_edit`). Wizard never calls Metronome's delete; the Flow and its run history stay in Metronome. The
  brief leaves the tab and the answer's card says it was deleted. If Metronome refuses, the brief stays listed with
  the reason. Audit: `metronome:deactivate_flow`.

**Consequences.**
- AGENTS.md's second exception now names `wizard_schedule_brief` and keeps every rule. Wizard still declares 21 tools.
- New API: `GET /api/v1/schedules/{id}/preview`, `GET /api/v1/recurring`, `POST /api/v1/recurring/{id}/delete`.
- Proposals made before briefs still work: one query becomes a one-table brief. Flows created before briefs keep the
  script they were created with: an Excel file and Metronome's standard message.
- The list comes from Wizard's own store: it shows the briefs created from this Wizard (one PC for the desktop app).

**Residual risk.**
- As before, recipients receive whatever the queries return at each run, whatever their own Wizard rights.
- The sentences are only as good as the rules Gemini picked at setup; something no rule covers goes unmentioned.
- Anyone holding Wizard's key can turn Wizard's Flows off in Metronome, as they could create them.

**Evidence.**
- `tests/unit/test_brief.py`: number formats, every rule, chart geometry and SVG, HTML escaping, sheet names, the
  standard-library-only rule.
- `tests/unit/test_schedule_tool.py`: rights, refusals before any query, the test runs as evidence, missing columns,
  the proposal.
- `tests/unit/test_metronome.py`: the generated script run with fake psycopg2, openpyxl and matplotlib (every query
  read-only in one transaction, the Excel sheets, the email and its charts, no matplotlib, an older Metronome, the row
  cap, a changed brief refused, values only as literals); Flow status and turning a Flow off against the fake Metronome
  with its ownership rule.
- `tests/integration/test_schedules_api.py`: the preview, the Recurring tab following Metronome, Delete turning the
  Flow off only as Wizard.
- Web: `RecurringPanel.test.tsx`, `RunCard.test.tsx`.
- Metronome: `tests/test_flow_email_delivery.py`, `tests/test_flow_python.py` in `datap0nd/data_governance`.
