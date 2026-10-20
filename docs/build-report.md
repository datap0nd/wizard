# Build report

The single running record the plan asks for: what is implemented, actual test output, operating mode and open
decisions. Update it with every change that alters behaviour.

## 2026-10-20 (latest) — The pixel wizard everywhere, a bigger stage, an animated button, files dropped on it

The owner asked for:
- a bigger, more animated stage;
- a file dropped on the **Ask Wizard** button attached to the conversation;
- a button animated on hover and on a click, and a panel that opens with more animation;
- "the wizard pixel character we had recently" as the logo everywhere.

**What changed.**
- **The character** is commit `8eb22fc` (branch `claude/fervent-maxwell-wwwa07`), brought in whole: `scripts/wizard_art.py`,
  `brand/`, the sprite and the logos.
  - The web app: the hat mark in the sidebar, the panel header, the answer cards, Wizard's own module and the favicon.
    The logo and the resting wizard on sign-in. The waving wizard on the start screens, the panel's included, where he
    waves each time the panel opens.
  - Its own sticky strip on a running answer was dropped: the wizard now stands in the stage.
- **The desktop icon** (tray, taskbar, Start menu, setup) is drawn by the same script into `apps/desktop/assets/wizard.ico`:
  the hat at 16 px, his portrait at 32 and 64, the whole wizard from 48 up. The script also writes the bar's copy of the
  sheet and `SpriteSheet.g.cs`, and `--check` (a unit test) covers them.
- **The stage** (`SystemsStage.tsx`) is bigger:
  - The pixel wizard (3x on a wide card, 2x in the panel) stands in a magic circle with turning rune rings and a glowing
    floor. The systems sit around him in two arcs, an orbit, on 58 px tiles.
  - He acts out the step in progress, and keeps acting out a fast step while its system stays lit.
  - Beams bend like a vortex and carry pixel "data bits". A finished call floats its result up from the wizard
    ("+ 4 rows · as of 2026-10-01"). An active tile hops, glows and pings. Pixel stars twinkle while he works.
  - When the answer lands live he hops with pixel confetti in the colours of the systems used (fizzles on failure).
    The stage folds into the journey strip 2.4 s later.
  - While the view follows a long answer down, a slim bar pinned to the top shows him writing, the systems used, and
    the landing hop. It appears only while the stage is out of view and takes no room.
  - Reduced motion still stops all of it.
- **The button** (`TopButton.cs`) is a light tab with the wizard in it, drawn from the embedded sprite sheet at a whole
  scale (1x, 2x from 175 %):
  - At rest he twinkles his staff every 9 s.
  - On hover the tab eases down, glows blue, shows "Click, Ctrl+Alt+W, or drop a file", and he waves. A click makes him
    cast.
  - While a question runs he acts out what the page shows (the page sends `activity`), and a glint runs along the
    bottom edge.
  - He hops and a green dot pulses when an answer is ready; he fizzles when the service stopped.
  - It redraws only when the picture changes, at 16–250 ms depending on what moves.
- **The panel** slides down from under the tab (230 ms, ease-out). The page unrolls downwards on the host's `focus`
  message, with a glint along the header.
- **Dropping files:**
  - Up to five files on the tab, from Explorer, or Outlook attachments and messages (saved under `dropped\`, kept a day).
  - Or on the panel's page: WebView2 hands the host the paths. In a plain browser the page uploads them instead.
  - WizardBar grants exactly those paths through `POST /internal/v1/desktop/drop` (control token, loopback). The page
    then attaches each one once, within ten minutes, through From this PC, so protected files still open from their
    place.
  - A full-window "Drop to attach" target with the wizard reading shows while a file is dragged over the page.
  - See the [decision addendum](decisions/2026-10-20-desktop-app.md).
- **Setup's pages** show the pixel wizard too (`installer/wizard-large.bmp`, `wizard-small.bmp`, drawn by the script).
- **CI** draws every look of the button on Windows (`WizardBar.exe --snapshot`), fails if the sprite is missing,
  uploads the PNGs and prints the 100 % one at the end of the log.

**Tests.**
- Python: 299 passed, 5 skipped. A new desktop test drops a CSV from a folder outside the attachment folders, a PDF
  and a missing file: only WizardBar can grant, errors come back per file, and a grant allows one attach.
- Web unit tests: 26 passed. New: the wizard in the stage reads, draws a chart, writes, hops and folds; a stored run has
  no finale; the orbit keeps every module clear of the circle and of each other.
- Browser tests: 16 passed with the sandbox's Chromium. The compact test now also checks the `activity` message, a drop
  on the page going to the host with the file, and a refused file from the host showing on the composer.
- Also passing: the spec, contracts (`openapi.json` regenerated for the drop endpoint), secrets, lint and types.
  `wizard_art --check` passes and WizardBar builds with warnings as errors.
- Screenshots of a slowed replay show the orbit, the beams and data bits, the floating result, the pinned bar while
  writing, the landing confetti, the panel's waving start and the drop target.
- Not yet seen on a real desktop: the button's animation, the slide, and drops from Explorer and Outlook. CI draws the
  button's looks on Windows. Outlook's virtual files use the standard FileGroupDescriptorW/FileContents formats
  (stream, memory, or a structured storage saved as `.msg`) and are untested until a work PC.

## 2026-10-20 (later still) — The systems stage: a visual view of what Wizard pulls from each system

The owner asked for a more visual, interactive and gamified view of a run. Each system should have its own logo and
light up while Wizard checks data there, showing what it is searching. The PostgreSQL database should appear as
"AI Team Database", and the knowledge base should be a module of its own.

**What was added.**
- **The stage** (`SystemsStage.tsx`, `stage.ts`, `SystemLogo.tsx`) at the top of every answer:
  - The Wizard orb sits in the centre, with each system this person can use around it as a module with its own mark
    and colour. Bootstrap's new `systems` list provides them: the report platforms, the AI Team Database, the
    knowledge base, and attached files once used. A platform without a mark, such as BDP, gets a monogram.
  - While Gemini reads from a system, its module pulses and an SVG beam streams particles into the orb.
  - The caption names the system and the call, shows the actual SQL when there is one, then the result
    ("→ 4 rows · as of 2026-10-01").
  - Gemini's latest interim note shows below, and "Gemini is deciding the next step" shows between calls.
  - A module stays lit for 2.2 s after a call, because most tools finish in milliseconds. A long query stays lit while
    it runs. Stored runs never linger.
  - Interactive: clicking a module lists its calls with the arguments, results, durations and evidence links.
  - Counters (systems used, calls, rows, notes) count up.
  - Badges only state facts about the finished run: cross-checked N systems, data + definitions, a deep dive of
    1,000+ rows, checked.
  - When the answer is done, the stage folds into a strip of the systems used, with their counts and badges, and
    "Show the journey" opens it again.
  - Narrow cards place the modules in a row under the orb. Reduced motion stops the animations and the particles.
  - Only observed tool calls drive it (AGENTS.md: never invent steps). The step-by-step list stays below, folded.
- **AI Team Database:** `WIZARD_PG_NAME` (default "AI Team Database", also in Settings) names PostgreSQL in the app,
  the sources list and the evidence. Tool labels read "Queried the AI Team Database". SQL and attachment queries now
  have proper labels and row-count summaries.

**Tests.** Python suite 295 passed. Web unit tests: 20 passed, including the stage logic and a render of an active
module with its SQL. The browser tests (16, with the sandbox's Chromium) now also unfold the journey and open NERP's
calls. The spec, contracts, secrets, lint and types checks pass. Screenshots of a slowed replay show modules lighting
and streaming in the full app and in the 720 px desktop panel.

## 2026-10-20 (later) — Settings in the app, a model picker, an Update button, publishing the knowledge base

The owner asked for:
- the credentials editable in a settings pane;
- a model picker, to use Gemini 3.1 Pro as well as 3.8 Flash;
- an Update button that gets the latest release;
- a way for Gemini 3.8 Flash on the work PC to create the knowledge-base repository properly.

See the [decision addendum](decisions/2026-10-20-desktop-app.md) and the [owner guide](desktop.md).

**What was added.**
- **Settings pane** (`wizard_api/settings_pane.py`, `SettingsDialog.tsx`):
  - Fields: Gemini (model, project, company domains), the knowledge base (repository, read-only token, branch, folder,
    interval), the company database (server, port, database, read-only user, password, SSL) and the proxy.
  - Each field shows its source: company file, this PC, `.env`, environment (locked) or default.
  - Values go to a new "this PC" store (`data\settings`, DPAPI for secrets), between the company file and `.env`.
    Saving a key `.env` had moves it out of `.env`.
  - Secrets are write-only.
  - Every save is validated by loading the settings again, and rolled back on error.
  - **Test connection** for the knowledge base (one GitHub request with the proposed token) and the database (a
    read-only session reporting the user).
  - Changes other than the model restart the desktop service by itself, after a running question.
  - Only the local Owner on their own install sees it: ⚙ in the panel, Settings in the sidebar, **Settings…** in the
    tray.
- **Model picker:** a chip in the panel header and the full app's top bar.
  - The list is the models in the person's own Gemini quota answer (`/api/v1/models`). Any id can be typed in Settings.
  - The model switches without a restart. Code Assist keeps one model per run.
- **Update button:** Settings → Version and updates.
  - `/api/v1/updates` reads the public release manifest and compares it with the installer's `BUILD.json` version
    (CI now stamps it).
  - **Update to 1.0.N** asks WizardBar to download, verify and install the release, as from the tray.
  - In a browser it offers the download link.
- **Publishing the knowledge base** (`wizard_documents/kb.py`, `.\docs.ps1 kb-publish`, `kb-check`, `provision`; work-PC
  task 50):
  - One commit through GitHub's Git Data API, because the work PC has no git.
  - Only `knowledge/**/*.md`, `contracts/sources/*.json` and a README the first time are published.
  - It validates first, refuses a public repository, uploads only changed blobs (same git blob ids), deletes notes
    deleted locally, keeps other files, and offers a dry run.
  - Its settings (`WIZARD_KB_PUBLISH_REPO`, `WIZARD_KB_PUBLISH_TOKEN`, `WIZARD_KB_READ_TOKEN`) are names the app never
    reads, so they cannot break the work PC's own install, and provisioning refuses them.
  - Task 50 walks Gemini CLI and the user through the steps: check the notes for errors and for anything that must not
    reach every PC, create the repository and two tokens in the browser, dry run, publish after a yes, check the users'
    token, then the Settings pane or a provisioning file. Gemini never sees a token: `private\` is in `.geminiignore`.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres,gemini-cli` in a Linux sandbox:
- PASS: spec, secrets, contracts (four new endpoints), lint, types, python-tests (292 passed), evals-schema, web-types,
  web-unit (14), web-dist and web-build.
- BLOCKED: gemini-cli, postgres and live-parity.
- e2e: the layer FAILs here because the local configuration launches Microsoft Edge, which the sandbox lacks. With the
  sandbox's Chromium, all 16 browser tests pass.
- New: `tests/unit/test_settings_pane.py` (25 tests) and `tests/unit/test_kb_publish.py` (9 tests, against a fake GitHub
  that keeps a real tree).
- The settings pane and the model picker were also driven in a browser against a throwaway install. The update check
  read the real release manifest (1.0.4.0).
- WizardBar compiles with warnings as errors. Its new message handling runs on Windows only and is untested.

## 2026-10-20 — Desktop app: always-on button, knowledge base from a private GitHub repository

The owner wants Wizard always on: a button at the top of the screen that opens a prompt box. The knowledge base lives
in a private enterprise GitHub repository that only the owner sees, each person signs in to Gemini with their own
account, and a read-only PostgreSQL account and other company settings are stored in the app. The owner pointed to
Scribble's installer as the model. See the [decision](decisions/2026-10-20-desktop-app.md) and the
[owner guide](desktop.md).

**What was added.**
- **WizardBar** (`apps/desktop/WizardBar`, C# .NET Framework 4.8, WebView2 1.0.2903.40 as in Scribble):
  - a per-pixel-alpha tab hanging from the top edge of the main screen; it never takes the focus, steps aside for
    full-screen apps and slide shows, can be dragged, and shows starting, working, answered and stopped states;
  - a borderless, resizable panel with `/quick`; only Wizard's own local pages load inside, other links open in the
    browser, and Esc hides it;
  - the tray menu, Ctrl+Alt+W, and a balloon when an answer arrives while hidden;
  - supervision of `run.py --desktop`: restart on exit code 75, a back-off after crashes, a health watchdog, and
    leftover-process clean-up;
  - an updater from the `desktop-continuous` release that checks size, SHA-256 and version, and never downgrades.
- **Installer and CI.**
  - `installer/Wizard.iss` installs per user, with no admin rights, and picks up `wizard.provision` placed next to it.
  - `scripts/build_desktop_payload.py` assembles the app code, the embeddable Python and the vendored wheels, from the
    same SHA-256-locked archives `setup.ps1` uses.
  - `.github/workflows/desktop.yml` (Windows) builds the bar and the payload, starts the packaged service, checks
    `/quick` and the control API, builds `WizardSetup.exe`, installs it silently, runs `--check` and uninstalls it.
    On `main` it publishes to `desktop-continuous`, and never over a newer build.
- **Service.**
  - `run.py --desktop` (`wizard_api/desktop.py`):
    - adds missing `.env` defaults: code-assist, port 8771, diagnostics off;
    - imports the provisioning file and syncs the knowledge base before serving;
    - logs to `%LOCALAPPDATA%\Wizard\logs`, beside WizardBar's own log;
    - signs in the local Owner only.
  - `/internal/v1/desktop/{status,sync,stop}` need a per-launch token on loopback.
  - `wizard_api/knowledge_sync.py` handles the private repository: a conditional commit check, the zipball,
    path-checked unpacking, the same validation as `WIZARD_CONTENT_DIR`, an atomic switch, the previous version kept,
    and errors explained.
  - Background sync runs every 30 minutes, with a restart onto a new version after 10 idle minutes. With a knowledge
    base configured, the synthetic catalog and demonstration questions are never shown.
- **Provisioning** (`wizard_api/provisioning.py`, `scripts/make_provision.py`, `run.py --import-provision`):
  - company settings sit under the PC's `.env`;
  - `_PASSWORD`, `_TOKEN`, `_SECRET` and `_KEY` values go to the SecretBox (DPAPI on Windows);
  - per-PC keys are refused;
  - the plaintext file is deleted after the import.
- `WIZARD_GOOGLE_DOMAINS` refuses a Gemini link from a non-company Google account.
- **Web.**
  - `/quick` is the compact view: header, conversation, composer, and the account prompt first.
  - Messages go to the WebView2 host (busy, finished, hide), and the composer focuses when the panel opens.
  - "Open in a full window" links to `/?c=<conversation>`.
  - A single local Owner identity signs in without the picker.
- **Guards.**
  - `scan_secrets.py` flags fine-grained GitHub tokens and refuses `.provision` files.
  - The content validator flags GitHub tokens.
  - `.gitignore` excludes `*.provision` and `company.env`.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres,gemini-cli` in a Linux sandbox:
- PASS: spec, secrets, contracts, lint, types, python-tests (258 passed), evals-schema, web-types, web-unit (14),
  web-dist and web-build.
- BLOCKED: gemini-cli and postgres (not installed in the sandbox), and live-parity.
- e2e: the layer FAILs in the sandbox because Playwright 1.63 wants Chromium 1243 and the sandbox has 1194. Run with
  the sandbox's Chromium (`launchOptions.executablePath`), all 16 browser tests pass, including the new compact-view
  test on both viewports.
- New: `tests/unit/test_desktop.py` (27 tests) covers provisioning, the sync against a fake GitHub, desktop start-up, a
  real `run.py --desktop` process stopped through the control API, the domain rule, and the C#, installer, CI and
  Python pieces naming the same files and codes.
- WizardBar compiles with warnings as errors (`dotnet build`, .NET SDK 8 on Linux against the .NET Framework 4.8
  reference assemblies).
- The `desktop` workflow on `windows-latest` passed every functional step on its first run:
  - built WizardBar (version 1.0.1.0);
  - assembled the payload from the locked archives;
  - started the packaged service from the embeddable Python, served `/quick`, answered the control API and stopped
    when asked;
  - built `WizardSetup.exe`, installed it silently, passed `run.py --check` on the installed copy, and uninstalled it.
  - The last step failed on a version-text comparison: Inno writes "1.0.1", the numeric version is 1.0.1.0. It now
    compares numbers, as the updater does. The next run (2) passed every step and produced a 21 MB `WizardSetup.exe`.
- WizardBar's windows (the tab, the panel, the hotkey, the tray, the update) have not run on a desktop yet. The first
  run is on a work PC.

## 2026-10-12 — Big Data Portal: discovery task and `bdp-check`

The owner wants the Big Data Portal (BDP) as another platform. BDP is not a report platform: people request access to
tables and query them with SQL in Superset. The owner decided Wizard will query it through Superset under each
person's own company sign-in (the same SSO as ASAP and GSCM), never a shared account or browser cookies
([decision](decisions/2026-10-12-bdp-superset.md)). Nobody knows yet which engines sit behind Superset or how its API
signs people in, so this change is discovery only. Wizard has no BDP tool yet.

**What was added.**
- `wizard_documents/bdp.py` and `.\docs.ps1 bdp-check --url <address>`, anonymous GET requests only:
  - Superset's health check and version;
  - the sign-in route read from the login page's redirects and bootstrap data: protocol, identity provider, a gateway
    in front of Superset, Windows integrated sign-in;
  - what the REST API and its description answer.
  - Redirects that leave Superset's host are recorded, not followed. Only parameter names are kept, never values.
  - The result goes to `content\inbox\bdp\superset-check.md`. A database list the user saved from their signed-in
    browser (`superset-databases.json`) is summarised: engine, DML allowed, background queries, SQL Lab.
- Work-PC task 40 (`/wizard:tasks 40`, meant for Gemini 3.8 Flash):
  - search the documents for BDP;
  - run the check;
  - guide the user through two saved pages and two questions;
  - write `outbox\40-bdp-discovery.md` (internal, with the questions for the BDP team) and
    `outbox\40-bdp-shareable.md`.
- The docs kit launcher adds `services/agent` to its path, so `bdp-check` uses Wizard's own proxy resolution and
  certificate store (`wizard_agent.outbound`).

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres` in a Linux sandbox:
- PASS: spec, secrets, contracts, lint, types, python-tests (231 passed), evals-schema, web-types, web-unit, web-dist
  and web-build.
- BLOCKED: gemini-cli (the CLI is not installed in the sandbox), postgres and live-parity.
- FAIL: e2e. Playwright 1.63 could not launch: the sandbox has Chromium build 1194, not the 1243 it needs. This change
  touches no web code.
- New: `tests/unit/test_bdp_check.py` (13 tests) runs against simulated Superset servers (OAuth through Entra ID, a
  SAML gateway, a password page with Windows sign-in, an unreachable host). It checks that only anonymous GETs to
  Superset's own host are sent and that no parameter value is written.
- The real Superset is first checked on the work PC.

## 2026-10-09 — Wizard's logo and character

The owner's ask: Wizard is being productised and gamified. It needs a sprite, a logo, and the wizard as a character that
animates while the work is done, in Samsung colours (Samsung Blue `#1428A0`, white, black; colours only, no Samsung logo).

**What changed.**
- **`scripts/wizard_art.py`** (standard library only) draws the wizard and the logo from text grids. It writes:
  - `brand/`: logo, mark, app icon (SVG and PNG), the sprite sheet (48 x 48 frames, 11 animations), its JSON atlas
    and animated previews;
  - the web app's copies, and the favicon in `apps/web/index.html`.
  - `--check` fails on a stale file. `tests/unit/test_wizard_art.py` runs it, so CI catches art that was not redrawn.
  - Full guide: [brand/README.md](../brand/README.md).
- **Web app.**
  - The sidebar, the answer cards and the favicon carry the hat mark. Sign-in shows the logo and the resting wizard.
  - The start screen's wizard waves, then rests.
  - A running answer has a sticky stage: the wizard acts out the step in progress, with what it is and the step's own
    label. Search tools search, read tools read, `wizard_calculate` casts, `wizard_render_visual` draws a chart, Check
    my data checks. Streaming text writes; otherwise he thinks.
  - When the answer lands live he hops, or fizzles on a failure. A reopened run has no stage.
  - The animation comes from observed run events only (`apps/web/src/wizard.ts`). Nothing is acted out that Wizard did
    not do.
  - Reduced motion holds the first frame.

**Tests.** All passing:
- spec, secrets, contracts, lint, types;
- python-tests (with the 3 new art tests);
- web-types, web-unit (19, with the new mapping and stage tests), web-dist;
- e2e: 14 passed, desktop and narrow. Run against this container's Chromium build, since Playwright 1.63's own build
  could not be downloaded here.

Replay mode runs its tools instantly, so there the stage mostly shows thinking, writing and the hop at the end. With
live Gemini, each tool step lasts seconds and gets its own animation.

## 2026-10-07 (later) — Metric notes say where the data is

A structure review of the work PC's knowledge folder after the first live sell-in run:
- The 39 dataset notes from task 18 follow the standard well.
- The layer above them was missing. `metrics/sell-in-sell-out.md` defines sell-in but names no object, filter or week
  column. The dataset notes carry the business word only in tags, and their example questions are about plans.
- So Gemini found by trial which rows are weekly actual sell-in. Tasks 20-25, which write metric and glossary notes
  from documents, have not run there yet, and as written they never read the dataset notes either.

**What changed (documentation only).**
- **Knowledge standard, section 11 (new):** every metric note ends with `## Where to get it`, one block per object:
  - dataset note id and exact name;
  - measure column and unit;
  - filters with exact values;
  - period and market columns;
  - one example query, every name and value checked against the dataset notes.
  - The dataset notes point back: the metric's id goes in `related`, and its name and aliases in `aliases` or `tags`
    and in "Questions this note answers".
  - Guidance Gemini may follow or adapt, not a rule for building answers.
- **Section 10:**
  - dataset notes gain `## Example query`, using exactly quoted column names and the filters from Pitfalls;
  - `aliases` gain the business words;
  - "Questions this note answers" uses executives' words.
- **Tasks:**
  - 22 always plans a priority 1 metric note for each measure a dataset holds;
  - 23 reads the dataset notes when writing a metric note, then updates their links and aliases;
  - 24 points ambiguous measures at their metric notes;
  - 18 adds the new sections on its next pass.
- Not done: the catalog export covers materialized views only, so mapping tables such as a country map or date
  dimension cannot be documented from the export yet.

**Tests.** Documentation only. Run in a clean worktree, all passing: spec, secrets, contracts, lint and python-tests
(223 passed, on top of the long-runs change). The web layers were not re-run because nothing in `apps/web` changed.

## 2026-10-07 — Long runs end with an answer: higher limits, a loop check, a wrap-up window

Prompted by a live run on the work PC ("tell me market share by market in august 2026": 27 steps, 20 sources, killed
at 600 s with an empty result). Before this change, the time limit was a hard kill: everything Gemini had gathered was
thrown away. The owner's direction: Gemini 3.8 Flash may take 15-20 minutes when it needs to; stop loops, not thoroughness.

**What changed.**
- **Backstops, not budgets** (`config.py`, `.env.example`): run time limit 600 s → 1,800 s, tool calls 40 → 150 (allowed up
  to 500), concurrent runs 4 → 8. The code-assist runtime's hidden 24-turn cap is now 200 (`code_assist.MAX_STEPS`).
- **Loop check** (`RunManager._bound`): tools are read-only, so an identical call (same tool and arguments; whitespace
  inside strings ignored) returns what it did before.
  - The second try runs, since a view being refreshed can time out once. The third is refused (`repeated_call`) and
    logged on the server, naming the tool, because a loop usually means a tool's answer was unclear.
  - After three refusals, the data and knowledge tools refuse further calls (`loop_stopped`): answer with what you have.
- **Wrap-up window**: in the last fifth of the time limit (at most 4 minutes), the data and knowledge tools refuse
  calls (`time_nearly_up`) and Gemini writes its answer with what it has. Calculate, visual and Check my data stay open,
  so the answer can still have its chart.
- None of this picks a route: every refusal is a tool error Gemini reads, and the run goes on.
- **Where the time went**: each step in "What Wizard did" shows when it started in the run and how long its tool took
  (`2:35 · 58.1 s`). The gap between steps is Gemini deciding. A running answer shows a live timer. Durations of a minute
  or more read "10 min 6 s".

**Tests.**
- New: `tests/unit/test_run_bounds.py` (6), `RunCard.test.tsx` (live timer and step timing), and run-state and format cases.
- Python suite: 238 tests, 227 passed, 11 skipped (postgres, live and gemini_cli layers need their servers or sign-in).
- Also passed: ruff, mypy, web typecheck, web unit (14), `verify_spec.py`, contracts (unchanged), web dist rebuilt and verified.
- Checked in the browser with the replay runtime: step timings render beside each step.
- Not verified: a real 20-minute run. The work PC is the first place a long live run happens.

## 2026-10-07 — Email an answer; a calendar in every request

Prompted by the first live SIBP run on the work PC ("Sell in by market for last week": 41 steps, 26 evidence items, 283 s).
Gemini spent a knowledge lookup and a query establishing which week was "last week" before it could start.

**What changed.**
- **Email button** on a finished answer (`apps/web/src/email.tsx`, `wizard_api/outlook.py`). It opens an unsent Outlook
  draft. The draft holds:
  - the question;
  - the answer, with tables kept and charts as their data tables;
  - how long the answer took, its data mode and check status;
  - the sources the answer cites or charts, one line per table or report. Table names are read from the SQL; CTEs and
    set-returning functions are left out.
  - The page builds the message. `POST /api/v1/runs/{id}/email` hands it to Outlook through the new
    `wizard_docs.py outlook-draft` command, in a subprocess with a 60 s limit.
  - `Display()` runs first, so the user's signature is kept, and Outlook is never quit.
  - Only when the browser and Wizard share the PC (fixture sign-in, loopback client). Behind an SSO proxy, or when
    Outlook cannot open, the page downloads the same message as an `.eml` file (`X-Unsent: 1`).
  - Wizard never sends mail. This is a button for the user, not a Gemini tool; AGENTS.md's no-email-tool rule is
    unchanged.
- **Calendar block** at the top of every request (`prompting.calendar_block`):
  - today's date, local to the server: on the work PC (Gulf time, UTC+4) the previous UTC date was still yesterday
    until 04:00, so "this week" was wrong early on Mondays;
  - this and last ISO week with week numbers and dates, the last 4 complete weeks;
  - this and last month and quarter, year to date.
  - A dataset's own week or fiscal calendar wins where its notes define one. Context, not a rule.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres` on a second development PC (x64, Windows 11):
- PASS: spec, secrets, contracts, lint, types, python-tests (217 passed), gemini-cli, evals-schema, web-types,
  web-unit (11), web-dist, web-build and e2e (14, Chrome channel).
- BLOCKED as allowed: postgres (no test server here; CI runs PostgreSQL 16) and live-parity.
- New tests:
  - the calendar, including ISO week 53;
  - the Outlook draft, against fake Outlook objects: shown, never sent, signature kept, Outlook left running;
  - the email endpoint: opens, 404, Outlook unavailable (503), behind a proxy (409);
  - table names from SQL and the final-sources list;
  - the e2e Email flow with the request intercepted, and the `.eml` fallback.
- Not verified: real Outlook. It first runs on the work PC.
- Environment notes for this PC:
  - uv is installed as a Python module, not on PATH, so verify_all ran with `.venv\Scripts` on PATH.
  - Edge's `msedge.exe` is missing, so e2e ran with `WIZARD_E2E_CHANNEL=chrome`.
  - `uv sync` rewrote `uv.lock`: the committed lock lacks pg8000's dependencies. That change is not included here.

## 2026-10-06 (evening) — Gemini writes its own SQL on PostgreSQL; the report-entry connector is withdrawn

Decision: [2026-10-06 live PostgreSQL](decisions/2026-10-06-live-postgresql.md). The owner withdrew the connector
below the same day. It constrained Gemini before any failure had been seen: report entries, aggregation rules, a
review task and a parity sign-off. The owner had already found Gemini 3.8 Flash excellent on this data.

**What changed.**
- **New tool `wizard_query_postgresql(sql, database?, max_rows?)`** (`wizard_connectors/postgres_query.py`). It reads
  whatever the read-only account's grants allow, guided by the task 18 dataset notes, and `wizard_list_sources` lists
  PostgreSQL when it is connected.
- **Protections:**
  - one statement through the extended protocol, with pg8000's placeholder parsing bypassed. pg8000's simple protocol
    would have accepted chained statements;
  - wrapped as a subquery;
  - START TRANSACTION READ ONLY, always rolled back;
  - a fresh connection per call, closed afterwards;
  - 60 s statement and 2 s lock timeouts;
  - at most 500 rows.
- **Labels and evidence.**
  - Data mode `LIVE` ("Live"), connector status `READ_ONLY_SQL`.
  - The sources drawer shows the SQL and the database.
  - Check my data runs the same SQL again and reports UNCHANGED or CHANGED.
- **Rights.** The tool needs the `postgresql` right for every market. The local Owner has it whenever a connection is
  set.
- **Removed:**
  - `postgres_source.py`, `postgres_contract.py`, task 19, and `.\docs.ps1 postgres-contract` / `postgres-sample`;
  - `relation`, `parity` and `column` in report entries;
  - `LIVE_UNVERIFIED`, `ROWS_UNVERIFIED`, and the system-prompt line about unchecked figures.
  - Catalog, validator and contract schema are back to `7ba5025`.
- **Kept:** the attachment tables and `wizard_query_attachment`, the shared `pg.py`, the PostgreSQL settings, and the
  start-up check (now always shown: reachable and read-only, or not configured).
- **Docs.** The knowledge standard asks dataset notes to name the database and say in `## Pitfalls` what a correct query
  must know. AGENTS.md allows this one SQL tool as an owner exception. Wizard declares 20 tools.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres` on the development PC: spec, secrets,
contracts, lint, types, python-tests (214 passed), gemini-cli (4 passed; the real CLI accepts all 20 tool schemas),
evals-schema, web-types, web-unit (6 passed, including the drawer showing the SQL), web-dist, web-build and e2e (12
passed) PASS. postgres and live-parity are BLOCKED here.
- `tests/unit/test_postgres_query.py` covers:
  - the SQL sent as written, inside a read-only transaction that is rolled back;
  - caps, types and error hints;
  - rights, evidence and Check my data;
  - the local Owner's access.
- `tests/integration/test_postgres_query_real.py` (CI's PostgreSQL 16, under an account allowed to write):
  - real analysis with a CTE, a join and window functions;
  - six write attempts, each refused and leaving the data unchanged;
  - a setting changed by one query does not outlive it.

## 2026-10-06 (later) — Live PostgreSQL reports and totals over attached spreadsheets

Withdrawn the same evening (entry above), except the attachment tables.

Decision: [2026-10-06 live PostgreSQL](decisions/2026-10-06-live-postgresql.md). Gemini CLI had told the owner that
Wizard could not give a GSCM or SIBP number: every real report was navigation-only.

**What was added.**
- **Live connector.**
  - `wizard_connectors/postgres_source.py` runs a catalogued PostgreSQL report through the same contract as the
    fixtures (`filters`, `group_by`, `measures`, `sort`, `limit`). The SQL is built from the entry's columns, with
    quoted identifiers, bound values, LIMIT 500 and market rights in the WHERE clause.
  - Aggregation rules run in SQL: `sum`; `sum_same_currency` (a total only within one currency); `last` (latest
    period per group); `none` (a value only for one row). Text columns holding numbers are cast safely.
  - Freshness comes from commit timestamps when the server tracks them.
  - Connection code shared with the export moved to `wizard_connectors/pg.py`.
- **Labels.**
  - New data mode `LIVE_UNVERIFIED` ("Live · not yet checked") and connector status `ROWS_UNVERIFIED`.
  - A report's signed `parity` (date, who, reference) makes its rows `LIVE_VERIFIED`.
  - The run result tells Gemini the figures are not yet checked, and the system prompt asks it to say so once.
  - The web badge, source explorer and API catalog show both states.
- **Contract.** `relation` (database, schema, view), `parity`, and `column` on dimensions, measures and attributes.
  The validator allows row reports only for PostgreSQL and checks:
  - the `last` and currency rules;
  - the parity date;
  - that parity is set only on live reports.
- **Kit.**
  - `.\docs.ps1 postgres-contract --view schema.view` drafts entries from the export and dataset notes, marking every
    guess `UNCERTAIN:`.
  - `.\docs.ps1 postgres-sample --report <id>` runs Wizard's own query for a parity check.
  - Task 19 walks Gemini CLI and the owner through choosing (SIBP first), reviewing and signing.
- **Start-up.** `run.py --check` reports whether PostgreSQL is reachable and the session read-only, whenever the catalog
  has PostgreSQL reports.
- **Attached spreadsheets.**
  - Each sheet or CSV is also saved as a full typed table (`converted/tables.json` plus CSV, up to 300,000 rows and 60
    columns).
  - The new tool `wizard_query_attachment` filters, groups and totals every row (sum, avg, min, max, count). It warns
    about rate columns and non-numeric cells.
  - Evidence stays `USER_PROVIDED`. Wizard now declares 19 tools.

**Tests.** `scripts/verify_all.sh --allow-blocked=live-parity,postgres` on the development PC: spec, secrets,
contracts, lint, types, python-tests (207 passed), gemini-cli (4 passed; the real CLI accepts all 19 tool schemas),
evals-schema, web-types, web-unit, web-dist, web-build and e2e (12 passed) PASS. postgres and live-parity are BLOCKED
(no PostgreSQL or live source here).
- New unit tests:
  - the generated SQL: quoted, bound, with rights applied;
  - each validator rule;
  - LIVE_UNVERIFIED before parity and LIVE_VERIFIED after it;
  - the draft and sample commands;
  - the attachment query engine and its evidence.
- `tests/integration/test_postgres_source_real.py` compares every aggregation rule with independently computed values on
  CI's PostgreSQL 16.
- The corporate views are first read on the work PC, in task 19.

## 2026-10-06 — PostgreSQL materialized views documented from the server's catalog

The owner chose to document the PostgreSQL server first, and only its materialized views, with the server as the
source of truth and a light profile of the data.

**What was added.**
- `wizard_documents/postgres.py` exports, over a read-only session (60 s statement timeout, 2 s lock timeout, SELECT
  only):
  - every visible materialized view: columns, types, comments, owner role, indexes, the SQL definition;
  - lineage both ways (through `pg_rewrite`/`pg_depend`);
  - the pg_cron job that refreshes it, statistics, and freshness from commit timestamps when tracked;
  - a light profile: exact row count, null rates and distinct counts (TABLESAMPLE above 200,000 rows), date and
    period ranges, and the values of code columns with at most 25 values.
  - No sums or numeric ranges are read, and columns that name people are never listed.
- `.\docs.ps1 postgres-check` and `postgres-catalog`.
- Settings: `WIZARD_PG_*` in `.env`, else the scanner account's `PG*` variables. The password is never printed or
  written.
- pg8000 (pure Python; psycopg2's DLL was blocked by Application Control on a development PC) is in the portable
  runtime: release `portable-cp313-win_amd64-ebab720ef8aa0947cf47`. It was verified to import and connect from the x64
  embeddable Python with `site` off.
- Task 18 writes `platforms/postgresql.md` and one `datasets/` note per view. The knowledge standard gains the
  `dataset` type and section 10: the export wins over documents.

**Tests.**
- Unit tests against a fake catalog assert that only SELECTs are sent, plus sampling, ranges, value lists, person
  columns, lock timeouts and output files.
- `tests/integration/test_postgres_real.py` runs on a PostgreSQL 16 service in CI. It builds a staging table, a
  materialized view, a view on top and a SELECT-only role, checks the export, and proves the session refuses a write.
  It is BLOCKED locally (no PostgreSQL here).
- The corporate server is first read on the work PC.

## 2026-10-05 (late) — Company documentation kit, expert quizzes and attached files

Decision: [2026-10-05 company documentation](decisions/2026-10-05-company-documentation.md).

**Knowledge retrieval.**
- `wizard_lookup_definitions` now ranks `##` sections (glossary entries one by one) with BM25 and stopwords, and
  boosts title, aliases, tags and summary.
- A long note returns its lead plus the matching sections and the headings it left out.
- New tools `wizard_browse_knowledge` (index with summaries) and `wizard_read_knowledge` (by id); 18 tools in all.
- Notes gain `type`, `summary`, `aliases`, `related`, `sources`, `updated`, `reviewed`, `reviewed_by`, under
  [the knowledge standard](../templates/content/schema/knowledge-standard.md).
- The content validator enforces the standard: flat front matter, unique kebab-case ids, known types, ISO dates, no
  email addresses. It warns about missing summaries, oversized notes and dangling `related` ids.
- A content folder with notes but no report catalogs is accepted.

**Document converter (`services/documents`, `scripts/wizard_docs.py`, `docs.ps1`).**
- Office through pywin32, following data_governance's rules: borrow a running application, open read-only in place,
  macros off, no SaveAs, restore settings, quit only what it started.
  - PowerPoint: text, tables, SmartArt, chart values, speaker notes, pictures of mostly-visual slides.
  - Excel: column profiles with formulas, pivot tables, charts, named ranges.
  - Word: headings and tables.
  - Outlook: display names, body, attachments.
- Standard-library fallback for plain .docx/.pptx/.xlsx, plus .eml, text, CSV and HTML. Office parts that declare a
  DOCTYPE are refused.
- Bulk inbox:
  - stable source ids (`S-` + SHA-256 prefix), with duplicates recognised;
  - email attachments followed and linked to their email;
  - email addresses and phone numbers masked;
  - folders listed in `inbox/_sources.txt` read in place (for NASCA files);
  - incremental re-runs.
- Outlook export of chosen folders and dates; private and confidential items skipped.
- Kit commands: progress, next sources, topics, coverage, quiz check, quiz answers.
- `run.py --check` reports whether pywin32 loads.
- pywin32 312 is added to the portable runtime (release `portable-cp313-win_amd64-19ef1695a72713055a2f`). It was
  verified to load from a vendor folder in the x64 embeddable Python with `site` off.

**Gemini CLI tasks 20-25 and 30-31.**
- Collect, digest (Gemini 3.5 Flash), topic map, write, glossary and ambiguous terms, coverage.
- One HTML quiz per area and stakeholder (`workpc/templates/quiz-template.html`: offline, autosave, "Save my answers"
  produces a filled copy to attach, "Copy my answers" gives a base64 block safe in quoted replies).
- Applying answers as cited sources (`A-<quiz>-<question>`).
- `setup.ps1` installs `docs.ps1`, `templates\` and `documents\quiz-*`, and refreshes `content\schema\` and
  `content\.gemini\commands\`.

**Attached files.**
- Upload or "From this PC" (`WIZARD_ATTACHMENT_FOLDERS`; off behind SSO).
- Conversion in a time-limited child process, one at a time.
- Files bound to the run as F1, F2…, listed in Gemini's prompt and read with `wizard_read_attachment`.
- Evidence uses the new data mode `USER_PROVIDED` (above SYNTHETIC, below approved sources). The drawer shows the text
  read.

**Tests.**
- `verify_all.sh --allow-blocked=live-parity`: every required layer PASS.
  - 189 Python tests, including new converter tests with fake COM objects, kit, knowledge, attachment and validator
    tests.
  - The real Gemini CLI accepts all 18 tool schemas.
  - 12 Playwright tests, including attaching a file.
  - live-parity is BLOCKED (no corporate access).
- The quiz page was exercised in a browser: answer, copy, reopen the saved answers, phone width.

**Not verified here.**
- Office and Outlook automation: this development session cannot start Office COM servers (`CO_E_SERVER_EXEC_FAILURE`).
  The first real run is task 20 on the work PC, which reports every file it could not read.
- `uv.exe` is now blocked by Application Control on the development PC, so `uv.lock` was not refreshed for pywin32.
  CI re-locks on Linux, where pywin32 is skipped. `WIZARD_E2E_PYTHON` lets Playwright start the E2E server without
  uv.

## 2026-10-05 (night) — Tool schemas checked against Gemini's rules (fixes 400 on every question)

**Work PC.** Every question failed with
`400 INVALID_ARGUMENT: schema at top-level requires unspecified property 'title'`.

**Cause.**
- `flatten_schema` dropped every `"title"` key to remove pydantic's metadata titles.
- That also deleted `wizard_render_visual`'s real `title` parameter from `properties`, while it stayed in `required`.
- All 15 tools are declared on every request, so Google rejected every request before the model ran.
- The offline fake-response tests never send schemas to Google, so they could not see it.

**Fixes.**
- Only metadata titles are dropped; property names are kept.
- Tool schemas now carry only the keywords Gemini documents
  ([structured output](https://ai.google.dev/gemini-api/docs/structured-output),
  [`FunctionDeclaration`/`Schema`](https://ai.google.dev/api/generate-content)), plus `anyOf`.
- `pattern`, `minLength`, `maxLength`, `const` and `default` are folded into the description. The registry still
  enforces them through the closed pydantic models.

**New guard: `wizard_connectors/gemini_rules.py`.** It checks:
- every `required` name exists in `properties`;
- only documented keywords, and no `$ref`/`$defs`/`oneOf`/`allOf`;
- single `type` values, and no `anyOf` with null;
- arrays declare `items`, and enums are strings;
- parameter names match `[A-Za-z_][A-Za-z0-9_]{0,63}`;
- function names follow Gemini CLI 0.62's `generateValidName` limits.

**Where it runs.**
- Contract tests on every tool, in both forms: as the CLI declares it (`mcp_<tool>`, `parametersJsonSchema`) and as
  the Code Assist runtime converts it (`parameters`).
- The real-CLI integration test, on the exact request body the CLI sends to Google.
- `run.py --check` on the work PC. That one FAILs with "Gemini would reject this request (400)" instead of letting a
  question fail.

**Also fixed.** `mypy` found that a local `onboard` variable shadowed `resolve_project`'s new `onboard` parameter.

**Still unverified.** A live call to Google cannot run on the dev laptop. These checks enforce Google's documented
rules.

## 2026-10-05 (evening) — Gemini quota ring

- **What it shows.** A small ring next to the account at the bottom left shows how much of the person's quota for the
  configured model (`gemini-3.8-flash`) is used. The hover text gives the % left (or N of M left) and the reset time.
- **Where the number comes from.** `GET /api/v1/account/gemini/quota` calls the Code Assist `retrieveUserQuota` method,
  the call Gemini CLI 0.62 makes. It uses the person's own linked sign-in and their project. The lookup:
  - never onboards an account;
  - is cached for a minute;
  - refreshes after each answer and every 5 minutes.

  The ring is hidden when quota is unavailable, and the reason goes to the server log.
- **Selection.** `summarize_quota` picks the configured model's most constraining bucket; a `-preview` variant also
  matches.
- **Not verified live.** Real bucket names for the enterprise licence are still to be confirmed on the work PC.

## 2026-10-05 (latest) — HTML reports folder setting

**Decision.** Power BI is dropped; standalone HTML reports (local files for now, fed from PostgreSQL) are the
reporting path.

**Setting.** `WIZARD_HTML_REPORTS_DIR` names the folder of HTML reports (subfolders allowed; relative paths resolve
against the install folder). It is configuration only: no tool reads the folder yet.
- A path that is not a folder stops start-up with a clear message.
- `run.py --check` prints the folder and how many `.html`/`.htm` files it holds.
- `setup.ps1` adds a commented `# WIZARD_HTML_REPORTS_DIR=` line to `.env` once, for you to fill in.

**Tests.** `uv run python -m pytest tests`: 130 passed, 1 skipped. `verify_spec.py` passed.

## 2026-10-05 (later) — Dev diagnostics in the UI, minimal chrome

**Feedback.** "Hey" failed after 59 s with "Gemini stopped with an error". Gemini CLI was named in three places.

**Diagnostics** (`WIZARD_DIAGNOSTICS`, on by default while in dev):
- Every Gemini CLI run attaches a diagnostic, shown under the answer and opened automatically on failure:
  - the CLI's full stderr and any non-JSON stdout;
  - the CLI's own error report (message and stack);
  - exit code and elapsed time;
  - the setup it ran with: CLI version, node, model, proxy, certificates, project.
- Unexpected failures attach their traceback.
- A **Log** button in the sidebar shows the server's recent log.
- Secrets are redacted.

**Bug found.** An earlier shell edit had turned the classifier's `\b` word boundaries into backspace characters, so
401, 403 and 429 never matched and fell through to the generic message. Fixed, and two guards added:
- a regression test for the classifier;
- a test that rejects control characters in source files.

New codes: `project_required`, `model_not_found`, `model_unavailable`, `model_rejected_request`, plus broader network
patterns.

**Project.** `GOOGLE_CLOUD_PROJECT` now falls back to the person's own Gemini CLI `.env` (`~/.gemini/.env`,
`~/.env`), which Wizard's isolated CLI home cannot see. `run.py --check` prints the project and where it came from.

**UI.** Gemini is named only in the account status at the bottom of the sidebar. Replay stays labelled. Dated reports
keep their runtime badge as provenance.

**Local build note.** Smart App Control blocks Tailwind's arm64 native module. Building with
`@tailwindcss/oxide-wasm32-wasi` installed via `--no-save` works and leaves `package.json` unchanged.

## 2026-10-05 — Work-PC Gemini sign-in fixes (first feedback from the work PC)

**Feedback.** The user saw only the synthetic test identities, none with their email. Pasting the Google code gave
"Wizard hit an internal error".

**Causes and fixes:**
- **No Owner identity.** The Owner was only added when `whoami /upn` produced an email, which often fails or returns a
  directory domain that differs from Google. An install now always lists the Owner first, and the Owner takes its email
  from the Google account it links (kept across restarts). Test identities explain that no real account can be linked
  to them, and point to the Owner.
- **The "internal error".** Wizard's Python called Google with certifi and no proxy. On a corporate PC, TLS inspection
  and proxy/PAC routing break that, as the data-governance app found on the same PCs. All Google calls now verify
  against the Windows certificate store (`truststore`) and use the resolved proxy, in this order:
  1. `WIZARD_PROXY`
  2. `HTTPS_PROXY`
  3. the user's own Gemini CLI `proxy` setting
  4. the Windows/PAC settings
  5. direct

  The Gemini CLI that Wizard starts receives that proxy and `NODE_USE_SYSTEM_CA=1`.
- **Error messages.** A network failure is now a 502 that names the host, the cause and the route, with the
  `WIZARD_PROXY` fix. `run.py --check` now tests both Google hosts.

**Portable runtime.** Republished as `portable-cp313-win_amd64-6bfe2f91b55233a53dd8`, which adds `truststore` 0.10.4
and leaves every other pin unchanged.

**Verification.**
- Smart App Control now blocks `uv` and the arm64 `pydantic_core` on this laptop (see
  [decisions/2026-10-02-dependencies.md](decisions/2026-10-02-dependencies.md)).
- Tests ran on the portable amd64 runtime: 122 passed. 2 failed, both contract tests that start the shim with `-m`
  from a working directory; the embeddable Python ignores the working directory by design, so they run in CI.
- `ruff`, `verify_spec` and the secret scan are clean. `mypy` and the full `verify_all` run in CI.
- New tests cover:
  - an Owner without an email, and one whose `whoami /upn` differs from the Google email;
  - a test identity being refused with a pointer to the Owner;
  - TLS and timeout failures returning 502 with an explanation;
  - the proxy resolution order and the CLI environment.

## 2026-10-02 (evening) — Work-PC install, update loop and Gemini CLI task kit

- **Install like B2B:** `setup.ps1` / `start.ps1` / `update_app.ps1` at the repository root, guide in
  [workpc-setup.md](workpc-setup.md), decision in [decisions/2026-10-02-workpc-install.md](decisions/2026-10-02-workpc-install.md).
  Portable CPython 3.13.15 plus 17 locked wheels, published as release
  `portable-cp313-win_amd64-f77a70401bd85a63d2e5` by `scripts/lock_portable.py --publish`. The web app is committed
  prebuilt (`apps/web/dist`, fingerprint checked by the new `web-dist` layer).
- **Install-folder mode:**
  - `run.py --home <folder>` reads `.env` and keeps `data\` in the install folder.
  - `run.py --check` gates every new release: does the app start, does content validate, and an offline Gemini CLI
    probe. The probe confirms exactly Wizard's 15 tools, Wizard's prompt, thinking HIGH, and no `GEMINI.md` leaking in
    from a parent folder.
  - `WIZARD_LOCAL_USER_EMAIL` adds an Owner identity with the real work email.
- **Fix found by the probe:** Gemini CLI loaded `GEMINI.md` from parent folders into the analyst's context. Wizard's
  per-user CLI settings now point `context.fileName` at a name that never exists.
- **Gemini CLI task kit** (`workpc/`):
  - `/wizard:tasks` and tasks 00–17, 90 (environment report, inventory, platform guides, report catalogs,
    definitions, question coverage, validation, owner questions, switch to real catalog, feedback pack).
  - `GEMINI.md` and `.geminiignore` keep `data\` and `.env` out of reach.
- **Verification:**
  - New `tests/unit/test_workpc.py`, which parses all four PowerShell scripts with the PowerShell parser.
  - The real-CLI probe test.
  - Local `verify_all.sh --allow-blocked=live-parity`: every layer PASS, only live parity BLOCKED.
- **End-to-end install from GitHub** (dev PC, empty folder, token from `gh auth token`, exactly the documented
  bootstrap):
  - **First install** of `f483db8`: 18 archives downloaded and verified, portable Python started under x64
    emulation, the check passed. It warned "Gemini CLI not found" because this PC has no global CLI, and
    `whoami /upn` is empty because the PC is not domain-joined.
  - **`update_app.ps1 -NoStart`** after setting `WIZARD_GEMINI_CLI_JS` and `WIZARD_LOCAL_USER_EMAIL` in `.env`:
    archives reused, every check PASS, including the real-CLI compatibility probe on the portable Python.
  - **`start.ps1`**: health/ready OK, Owner identity listed first, chat UI and the "Link your Gemini account" dialog
    working.
  - **`/wizard:tasks 00`** (Gemini CLI 0.62 in the install folder, offline): the command expands with its argument and
    the folder's `GEMINI.md` loads, but **only in a trusted folder**. CLI 0.62 refuses untrusted folders headless and
    asks interactively, so the guide and setup now say to trust the folder.
- **Not testable here:** linking a real enterprise Google account and a live answer. Those are the first things to try
  on the work PC.

## 2026-10-02 (later) — Real-content loader, documentation kit, CI type fixes

- **Content folder:** `WIZARD_CONTENT_DIR` loads an internal wizard-content repository instead of the synthetic examples.
  It is validated at start-up (`wizard_connectors/content.py`, also `scripts/validate_content.py`). Real reports must be
  NAVIGATION_ONLY with no data file; secrets, stray data files, bad front matter, wrong ids and summed percentages
  stop the service. Not allowed with the replay runtime. Navigation-only platforms make no data-mode claim in the UI.
- **Documentation kit:** `templates/content/` (layout, authoring rules, Gemini CLI commands `/wizard:platform-guide` and
  `/wizard:report-catalog`, schema copy kept in sync by `verify_spec.py`); [documentation-guide.md](documentation-guide.md),
  [how-it-works.md](how-it-works.md). The ASAP importer now emits strictly valid drafts.
- **CI:** the first CI run failed only on mypy (18 typing findings; mypy had never run, as it was blocked on the dev PC).
  All fixed, plus 3 more found once a source-built mypy ran locally. Local `verify_all.sh --allow-blocked=live-parity`:
  every layer PASS (101 Python tests, 3 real-CLI tests, 10 E2E, types clean); only live parity BLOCKED.

## 2026-10-02 — Release A foundation (SYNTHETIC)

**Mode of operation:** SYNTHETIC data only. Runtimes available: `replay` (default; recorded transcripts),
`gemini-cli` and `code-assist` (live routes, implemented; **no real enterprise account has been used yet**).
No corporate system, credential or data has been touched. Nothing here is LIVE_VERIFIED.

**Built on:** Windows 11 ARM64 development PC, Python 3.13.15 (uv 0.12.5), Node v24.19.0, Gemini CLI 0.62.0 (pinned in
`.tools/`, offline fake responses only).

### What was implemented

| Plan step | Delivered |
|---|---|
| 00 | New repository; agent-first AGENTS.md/GEMINI.md; [repo-references.md](repo-references.md) (B2B design system reused, Scribble's working Gemini sign-in located at `41ab532` and ported, Metronome policy/MCP patterns); spec and fail-closed verification gates |
| 01, 03, 04 | Drafts: product requirements, coverage matrix, source register, typed source contracts, unsigned knowledge notes, synthetic goldens |
| 02 | Two runtime routes behind one interface; per-user isolation verified against the real CLI (forced file credential storage, `tools.core=[]`, policy file, system-prompt override); in-app per-user Google linking with email match; two-user spike script (offline check passes); threat model |
| 05–07 | FastAPI run manager with SSE, SQLite store, 15 read-only tools, MCP stdio shim, Check my data, calculator, B2B-style web app (timeline, evidence drawer, charts/tables, source explorer, dated reports), 30 draft eval cases + runner |
| 08 | Fixture and trusted-header identity, rights on search/run/reopen, audit log, retention expiry |
| 09, 14 | ASAP navigation states in the explorer, Library REST client groundwork, metadata-only catalog importer, BLOCKED parity test; per-platform guides ([platforms.md](platforms.md)) |
| 12–13 | Planner and conquest stories over synthetic data (screening and observed-count framing) |

### Verification output (`scripts/verify_all.sh --allow-blocked=live-parity,types`)

```
spec             PASS   verify_spec passed: fixtures, contracts, goldens, transcripts, knowledge and links are consistent.
secrets          PASS   Secret scan clean.
contracts        PASS   Published contracts match the code.
lint             PASS   ruff: All checks passed!
types            BLOCKED  mypy: DLL load failed while importing ast_serialize: An Application Control policy has blocked this file.
python-tests     PASS   88 passed, 4 deselected
gemini-cli       PASS   3 passed (real Gemini CLI 0.62.0, offline fake model replies)
evals-schema     PASS   1 passed
web-types        PASS   tsc --noEmit
web-unit         PASS   4 passed
web-build        PASS   vite build
e2e              PASS   10 passed (Playwright, Edge, desktop 1440x900 + narrow 1024x768)
live-parity      BLOCKED  live ASAP parity not configured (WIZARD_PARITY_* unset)
verify_all: all required layers passed.
```

`types` runs in CI on Linux; it is blocked only on this PC. `live-parity` stays BLOCKED until Step 09 has an approved
route, report and signed reference.

### Problems found and fixed while building

- Gemini CLI headless mode silently dropped every MCP tool (policy engine turns "ask user" into deny) → per-home policy
  file passed with `--policy`.
- Gemini CLI keychain token storage is shared across `GEMINI_CLI_HOME`s → `GEMINI_FORCE_FILE_STORAGE=true` everywhere.
- The CLI blocks `PYTHONPATH` for MCP servers → shim started with `cwd`.
- Error classification matched digits inside ids as HTTP codes → word-boundary patterns, most specific first.
- A denied market was also reported as "no data in source" → denied values excluded from missing-data warnings.
- E2E projects collided on one user's single active run → one worker.

### Open decisions (owner / IT), defaults in force

See plan section 7 and [issue-board.md](issue-board.md). Highlights: which runtime route is approved (default: none for
executives; local synthetic only); fiscal calendar and markets (synthetic Q3 2026 only); which reports cover spend,
sell-through, share and switching (three mock adapters); ASAP Library REST access (navigation only); pilot host, TLS,
backups and operator (local development only); retention and sharing (creator only, 30 days).
