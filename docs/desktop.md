# The desktop app (WizardBar)

Wizard as an always-on assistant: a small **Ask Wizard** tab at the top of the screen, with the pixel wizard in it. A
click, or Ctrl+Alt+W from any app, opens a prompt panel; Esc hides it. A file dropped on the tab is attached to the
question. A question keeps running while the panel is hidden, and a notification says when the answer is ready. The decision behind it is
[2026-10-20-desktop-app.md](decisions/2026-10-20-desktop-app.md).

```
 GitHub (public)                         GitHub (your private enterprise repo)
 datap0nd/wizard ── CI ─▶ desktop-continuous release        acme/wizard-content (knowledge base)
                          WizardSetup.exe + manifest                 ▲  read-only token
                                   │ install / update                │  (from wizard.provision)
 ┌──────────────────────── user's PC ─────────────────────────────────┼──────────────────────────┐
 │ WizardBar.exe  ── tab at the top, panel (WebView2), tray, Ctrl+Alt+W, updates                 │
 │   └─ starts and watches ─▶ python run.py --desktop  (127.0.0.1:8771)                           │
 │                              ├─ knowledge base: sync ───────────────────────────────────────────┘
 │                              ├─ PostgreSQL: read-only account (from wizard.provision)
 │                              └─ Gemini: the person's own Google sign-in (code-assist)
 └────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## What gets installed where

| Folder | What | On update | On uninstall |
|---|---|---|---|
| `%LOCALAPPDATA%\Programs\Wizard\bar` | WizardBar.exe, WebView2 libraries | replaced | removed |
| `%LOCALAPPDATA%\Programs\Wizard\app` | Wizard's code, built web app, libraries | replaced | removed |
| `%LOCALAPPDATA%\Programs\Wizard\runtime\python` | Embeddable Python 3.13 | replaced | removed |
| `%LOCALAPPDATA%\Wizard` | `.env`, `data\` (conversations, Gemini sign-in, company file in `provision\`, Settings in `settings\`, knowledge base, the Wizard browser's own Chrome/Edge profile and saved portal scripts in `users\<id>\portal-browser\`), `logs\`, WebView2 profile, `bar.json`, `dropped\` (Outlook items dropped on the tab, kept a day) | kept | kept |

No admin rights are needed. Setup adds a Start-menu entry and, by default, a "start when I sign in" entry
(`HKCU\...\Run`). The tray menu can turn that off.

## One-time setup (owner)

The work PC's Gemini CLI does this with you: **task 50** (`/wizard:tasks 50` in `C:\Wizard`, after `.\update_app.ps1`).
It checks the notes, has you create the repository and two tokens in the browser, publishes, checks the users'
token and makes the provisioning file. You type the tokens into files yourself; Gemini never sees them. What it does:

### 1. The knowledge-base repository

A **private** repository in the company's GitHub organisation (for example `acme/wizard-content`), created **empty**.
Users never get a GitHub account or a link to it.

The repository is on the company's GitHub Enterprise Server, `https://github.sec.samsung.net`. Wizard calls its API
(`https://github.sec.samsung.net/api/v3`) for the sync, Test connection, `kb-publish` and `kb-check`. The server is
built in (`wizard_connectors/github.py`): no setting, provisioning file or `.env` value changes it, and Wizard never
calls `api.github.com` for company content. Only the app's own updates come from the public release on github.com.

`.\docs.ps1 kb-publish` fills it from the work PC (no git needed: one commit through GitHub's API). It publishes only
what Wizard reads, `content\knowledge\**\*.md` and `content\contracts\sources\*.json`, plus a README the first time:
the inbox, digests, registers, quiz answers and stakeholder lists stay on the work PC, because every file in the
repository reaches every PC. Before writing it runs Wizard's validation, refuses a public repository, uploads only
changed files and deletes notes deleted locally. `--dry-run` shows the list first. Every sync on users' PCs runs the
same validation again: a commit with errors is not applied, and PCs keep the previous version.

### 2. Two fine-grained tokens

GitHub → Settings → Developer settings → **Fine-grained personal access tokens**, both with Resource owner = the
organisation and Repository access = **only** the knowledge-base repository:
- **Publishing**, kept on the work PC: Contents **Read and write**. In `C:\Wizard\.env` as
  `WIZARD_KB_PUBLISH_REPO=owner/name` and `WIZARD_KB_PUBLISH_TOKEN=...` (names only `docs.ps1` reads, so the work
  PC's own Wizard is unaffected).
- **Read-only**, for every user: Contents **Read-only**, nothing else. In `C:\Wizard\.env` as
  `WIZARD_KB_READ_TOKEN=...` for `.\docs.ps1 kb-check`, and in the provisioning file as `WIZARD_KB_TOKEN`.

Expiration: as long as the organisation allows; note the dates. When the read-only token expires, Wizard keeps its last
copy and shows the GitHub error (About Wizard, Settings → Test connection) until PCs get a new one. If the organisation
requires approval for fine-grained tokens, an organisation owner approves them (until then GitHub answers 403).

### 3. The provisioning file

Keep the company settings in a `KEY=value` file outside every Git repository: on the work PC,
`C:\Wizard\private\company.env` (Gemini CLI does not read `private\`; `company.env` and `*.provision` are git-ignored
here, and `scan_secrets.py` refuses `.provision` files and GitHub tokens):

```ini
WIZARD_KB_REPO=acme/wizard-content
WIZARD_KB_TOKEN=github_pat_...
WIZARD_KB_PATH=
WIZARD_PG_HOST=db.corp.example
WIZARD_PG_PORT=5432
WIZARD_PG_DATABASE=bi
WIZARD_PG_USER=wizard_ro
WIZARD_PG_PASSWORD=...
WIZARD_PG_SSLMODE=prefer
GOOGLE_CLOUD_PROJECT=your-gemini-project
WIZARD_GOOGLE_DOMAINS=company.com
WIZARD_GEMINI_MODEL=gemini-3.8-flash
WIZARD_METRONOME_URL=http://metronome-host:8000
WIZARD_METRONOME_CLIENT_KEY=wizard-...
```

```powershell
.\docs.ps1 provision private\company.env --name "ACME Wizard" --out private\wizard.provision
```

(From a development checkout: `uv run python scripts/make_provision.py company.env --name ... --out ...`.) Any
`WIZARD_*` setting can go in, except the ones each PC decides (data folder, port, identity, content folder) and the
publishing set-up. Names ending in `_PASSWORD`, `_TOKEN`, `_SECRET` or `_KEY` are stored with Windows DPAPI on the PC.

The PostgreSQL account must be **read-only by its grants** (SELECT on the views Wizard may use, nothing else). Everyone
who has the file can use it, also outside Wizard.

### 4. Metronome, for recurring briefs (optional)

People can have an analysis Wizard did emailed to them on a schedule, as a short newsletter: key numbers, charts, what
moved and tables, with an Excel file of every row attached. They press **Make recurring** under an answer, or ask for
it, check the email on the card Wizard shows and press **Create in Metronome**. It goes to their own address (their
sign-in email without the `ax.` after the @) at 08:00 Dubai time unless they say otherwise; Gemini asks at most how
often. Metronome then runs the queries and sends the email. Every Flow belongs to Metronome's **Wizard** user, never to
the person who asked ([decision](decisions/2026-10-20-metronome-recurring-extractions.md),
[briefs](decisions/2026-10-23-recurring-briefs.md)). The sidebar's **Recurring** tab lists each person's briefs with
Metronome's state; **Delete** there turns the Flow off in Metronome.

1. In Metronome, on the host PC, open **Users** and add a user named `Wizard` (role BI). Give it the email that should
   receive Metronome's failure alerts for these Flows.
2. On the Metronome host PC, run `python metronome_link.py` with Metronome's own Python (copy
   [scripts/metronome_link.py](../scripts/metronome_link.py) there; it needs only the standard library). It signs a new
   key in as `Wizard` and prints `WIZARD_METRONOME_CLIENT_KEY=...`. Metronome has no API tokens: it knows a caller by
   this key, so keep it like a password.
3. Put that key and Metronome's address on the office network in `company.env` (above) and make the provisioning file
   again, or set them on one PC in **Settings → Metronome** and press **Test connection**.

The query runs on Metronome's worker under Metronome's read-only `PG*` scanner account, or under a dedicated read-only
account if Metronome's `.env` sets `WIZARD_EXTRACT_PGHOST`, `WIZARD_EXTRACT_PGUSER`, `WIZARD_EXTRACT_PGPASSWORD` (and
`_PGPORT`, `_PGDATABASE`, `_PGSSLMODE`). Recipients must be in `WIZARD_GOOGLE_DOMAINS`. The email needs a Metronome
whose Email step accepts a script's own body (`METRONOME_FLOW_EMAIL_DIR`, October 2026) and matplotlib in the Python
Metronome's worker uses; without matplotlib the charts go in as tables, and an older Metronome sends its standard
message with the Excel file.

## The button and the panel

The tab hangs from the top edge of the main screen. Drag it sideways to move it; right-click it for the menu. It steps
aside for full-screen apps and slide shows.

| What you see | What it means |
|---|---|
| The wizard at rest, twinkling his staff now and then | Ready: click, or press Ctrl+Alt+W |
| The tab drops down and he waves; a second line appears | The pointer is on it ("Click, Ctrl+Alt+W, or drop a file") |
| He casts | You clicked: the panel slides down from under the tab and the page unrolls |
| "Wizard is working…", a glint running along the bottom, the wizard reading, searching, writing… | A question is running. He acts out the same step as the wizard on the page |
| "Wizard answered" with a green dot, and he hops | The answer is ready (a notification says so too) |
| "Starting Wizard…" (thinking) / "Wizard stopped" (fizzling) | The service is starting / stopped: click for the reason |
| "Drop to attach", a dashed outline, the wizard with his book open | A file is being dragged over the tab |

**Attaching a file by dropping it.**
- Drop up to five files on the tab, or on the open panel. The panel opens with them attached to the question being
  written; each shows "Reading…" and then what Wizard read (slides, sheets, parts).
- Accepted: PowerPoint, Excel, Word, email (`.msg`, `.eml`), CSV and text. Anything else, or a folder, shows the reason
  on the file.
- A file from Explorer is read where it is, from any folder, as **From this PC** does. Protected files open only from
  their original place, so this works for them too.
- An Outlook attachment or a whole message has no place on disk. WizardBar saves it under `dropped\` in the home folder
  first, and removes it a day later.
- How it is allowed: WizardBar tells the service, over the control API, which files were dropped. Each one may then be
  attached once, within ten minutes. The page cannot reach other files outside Downloads, Desktop and Documents.

The panel's answers show the systems stage: the pixel wizard in a magic circle with the systems around him. A system
lights up and streams pixels into the circle while Gemini reads from it, and he acts out the step. When the answer lands
he hops. While a long answer streams, a slim bar pinned to the top of the panel keeps him in view.

## Settings, model and updates in the app

The ⚙ button in the panel (or **Settings…** in the tray menu, or Settings in the full app's sidebar) opens the settings
of Wizard on this PC:

| Section | Settings | Test |
|---|---|---|
| Gemini | Google Cloud project, company Google domains | — |
| Knowledge base | Repository, read-only token, branch, folder, check interval | **Test connection**: can the token read the repository? |
| Company database | Name people see (default "AI Team Database"), server, port, database, read-only user, password, SSL | **Test connection**: connects read-only and reports the user |
| Portals | ASAP, GSCM and Big Data Portal addresses, browser (Chrome or Edge), other hosts the portals need | **Sign in to the portals** opens Wizard's own browser visibly, one tab per portal: sign in, then close it (or **Done**). **Check sign-in** opens each portal in the background and says whether it is signed in |
| Network | Proxy | — |
| Version and updates | The installed version | **Check for updates** / **Update to 1.0.N** |

- **Where a value comes from** is shown next to each field: the company file, this PC (set here), the `.env` file,
  or an environment variable (locked here). What you set here wins over the company file; "Use company value" clears
  it again. Saving a key that `.env` also had moves it out of `.env`, so no password stays there in plain text.
  Precedence: company file < this PC < `.env` < environment.
- **Secrets** (token, password) are write-only: the page only shows "Saved (hidden)" and **Change**.
- **Applying:** changes restart the service by itself (after the running question, if any); the page waits and
  reconnects.
- **The model** is Gemini 3.8 Flash for everyone (`gemini-3.8-flash`), with Gemini 3.1 Pro preview
  (`gemini-3.1-pro-preview`) as the **fallback model**, as in Gemini CLI. There is no model picker in the app: the owner
  removed it on 20 October 2026, and a model chosen with it before no longer applies. Only the company file, `.env` or
  the environment can set others (`WIZARD_GEMINI_MODEL`, `WIZARD_GEMINI_FALLBACK_MODEL`; `none` turns the fallback off).
- **When Gemini says no.** Wizard handles Google's refusal the way Gemini CLI does:
  - *No capacity for the model* (Google's side, not your quota): two quick tries (1 s, 3 s), then the other model takes
    the step and the answer continues on it: Flash hands over to Pro, and Pro hands back to Flash. As with Gemini
    CLI's default, this is silent: no message on the stage (the owner did not want "Google has no capacity" on every
    question), and the answer's report names the model that answered. Every new question starts on Flash. Only when
    both models refuse (or no fallback is set) does Wizard wait: 5 to 30 s, then one more try on each, for up to 10
    rounds (about 4 minutes). The wait is not shown either: the stage keeps the wizard at work, with no "Gemini is
    busy" (owner, 23 October). `logs\wizard.log` records each wait (`waiting 12 s for Gemini`), and if the answer
    fails, Error details says how often and how long Wizard waited. Only if every round fails does the answer stop,
    with Google's reason.
  - *Your quota for the model is used up* (often the daily quota): no waiting. The answer continues on the other
    model, and Wizard does not go back to the first one until Google's reset time.
  - *Per-minute limit* (Wizard asks Gemini once per step, so a long answer can reach it): the other model takes the
    step; if it refuses too, Wizard waits as long as Google asks, without a message, then continues.
  - `logs\wizard.log` also records each step's model and size (`run … step 12 on gemini-3.8-flash: 48210 prompt
    tokens, 3 tool call(s)`), so a slow answer shows whether the time went to waiting or to a growing conversation.
  - Gemini is asked to request independent lookups and queries together, in one step, since every step is a round trip
    that a busy Gemini can make wait.
  - A failure or a quota message quotes Google's own words (`Google said: "..."`), and `logs\wizard.log` records each
    refusal and each switch of model with Google's reason (lines from `wizard.gemini`).
  - *A turn with nothing in it* (no answer and no tool call; Gemini CLI calls it an invalid stream and asks again):
    Wizard asks the same model once more, then the other model twice, silently. Only if all of them come back empty
    does the answer stop, saying Google's finish reason (for example `MALFORMED_FUNCTION_CALL`, a tool call Gemini
    wrote that could not be read). If Gemini wrote a message earlier in the answer, that message is shown instead,
    with a warning.
- **Error details:** every answer that could not finish has an **Error details** button next to **Ask again**. It shows
  exactly why: Google's finish reason and message (or its refusal, or the HTTP error it answered with), what Gemini
  sent back (`text (0 characters) + thoughtSignature`), which models were tried and how often, the step and token
  counts, the last tool call and status line, how long the answer ran, the run id and the build. **Copy details** puts
  it on the clipboard with the question. Tokens are redacted; the prompt and Gemini's reasoning are never shown.
- **Staying signed in:** WizardBar keeps the page open for days. A session in use is renewed every hour; after a long
  sleep the page signs in again as you by itself and repeats what it was doing, as it does when Wizard starts. No
  reload is needed (the panel has no reload button).
- **Sleep:** while a question runs, Wizard keeps the PC from going to sleep when idle (as a download does), so a long
  answer is not stopped half-way. The screen still turns off; closing the lid or choosing Sleep still sleeps.
- **Update:** Check for updates reads the public release manifest; **Update to 1.0.N** has WizardBar download it, check
  size, SHA-256 and version, install it silently and start again. In a normal browser it offers the download instead.

The settings pane exists only on a person's own install (desktop app or work-PC install), for the person at that PC:
never on a server behind SSO.

## Giving Wizard to someone

1. Download `WizardSetup.exe` from the
   [desktop-continuous release](https://github.com/datap0nd/wizard/releases/tag/desktop-continuous) (or a CI run's
   `WizardSetup` artifact).
2. Put `WizardSetup.exe` and `wizard.provision` in one folder: a shared drive, or a zip sent internally.
3. They run `WizardSetup.exe`. SmartScreen may warn about an unsigned app ("More info → Run anyway"), as with Scribble.
   Setup copies `wizard.provision` along, and Wizard starts.
4. The tab appears at the top of the screen. The first click shows **"First, link your Gemini account"**. They sign in
   with their company Google account in the browser and paste the code.

Someone who already has Wizard can import a new file from the tray menu: **Import a settings file…**.

## Updating

- **Program:** every push to `main` builds a new `WizardSetup.exe` (version `1.0.<CI run>`) and publishes it to
  `desktop-continuous`. Wizard checks two minutes after start and every six hours. When a newer version exists, the tray
  shows "Install update…"; Settings → Version and updates has the same as a button. Wizard downloads it, checks its size, SHA-256 and version against the manifest, installs it
  silently and starts again. It never downgrades.
- **Knowledge:** `.\docs.ps1 kb-publish` from the work PC (task 50, step 10). PCs pick the change up within 30 minutes and switch to it after
  10 minutes without use, or at once with **Sync the knowledge base now**.
- **Settings or credentials:** make a new `wizard.provision` and have people import it (or run setup again next to
  it). It replaces the previous company file; what someone set in their own Settings still wins.

## The tray menu

| Item | What it does |
|---|---|
| Ask Wizard (Ctrl+Alt+W) | Opens the panel |
| Open Wizard in the browser | The full app (sidebar, history, sources) at `http://127.0.0.1:8771` |
| (in the browser) `/brain` | The Brain page: what Wizard knows as one picture, the systems and the live news, with a presenter tour (`http://127.0.0.1:8771/brain`; [decision](decisions/2026-10-28-brain-page.md)) |
| Sync the knowledge base now | Checks GitHub now and restarts the service on a new version |
| Show the button at the top of the screen | Hide the tab (Ctrl+Alt+W and the tray still work) |
| Start Wizard when I sign in | The `HKCU\...\Run` entry |
| Settings… | Opens the panel's settings: model, knowledge base, database, proxy, version and updates |
| Import a settings file… | A new `wizard.provision`; the service restarts and imports it |
| Check for updates… / Install update… | See Updating |
| Open the log folder | `%LOCALAPPDATA%\Wizard\logs`: `bar.log` (WizardBar), `wizard.log` (the service), `service-output.log` |
| Restart Wizard / About Wizard / Quit Wizard | About shows the version, the knowledge-base commit and the last sync problem |

## What people at a PC can and cannot do

- They cannot browse the knowledge-base repository, see its history or drafts, or change it.
- They can, with effort, read what the app reads: the synced notes are files under `data\knowledge`, and the token and
  database password can be decrypted under their own Windows account. Treat both credentials as shared with everyone who
  has the file. Keep the token read-only on one repository and the database account read-only by its grants.
- Their Gemini usage runs under their own Google account. With `WIZARD_GOOGLE_DOMAINS` set, only company accounts can
  link.

## Troubleshooting

| Symptom | Where to look |
|---|---|
| The tab says "Wizard stopped" | The panel shows the reason. `logs\wizard.log` names a settings problem (exit code 2); Restart Wizard tries again |
| "Starting Wizard…" for minutes | `logs\service-output.log`. Another program may use port 8771: set `WIZARD_PORT` in `%LOCALAPPDATA%\Wizard\.env` |
| Knowledge base not updating | About Wizard shows the last sync problem: 401 = token expired, 404 = token lacks access, 403 = SSO approval or rate limit |
| No tab, but the tray icon is there | The tab hides during full-screen apps and slide shows, or was turned off in the menu |
| Ctrl+Alt+W does nothing | Another program owns it (`bar.log` says "taken by another program"); use the tab or the tray icon |
| The panel is blank and mentions WebView2 | The Edge WebView2 runtime is missing; it ships with Windows 10/11 and Edge |
| "Google has no capacity for …" | Google had no capacity for Flash or for Pro, the fallback (not your quota). Wizard already waited about 4 minutes; try again a little later. The message quotes Google's reason, and `logs\wizard.log` has it for each refusal |
| "Wizard could not finish this answer" | **Error details** under the message says why: Google's finish reason and words, the models tried, the last tool call. **Copy details** to send it on. The same run id is in `logs\wizard.log` |
| A dropped file shows "Could not read" | Point at the file in the panel for the reason (type, size, a protected file Office would not open). `bar.log` has drop errors |

## Building it yourself

```bash
dotnet build apps/desktop/WizardBar/WizardBar.csproj -c Release -o artifacts/desktop/payload/bar   # also builds on Linux
python scripts/build_desktop_payload.py --out artifacts/desktop/payload                             # needs committed files
ISCC installer\Wizard.iss                                                                            # Windows, Inno Setup 6
```

For development without the installer, run WizardBar with `--install <folder with app\ and runtime\python\>` and
`--home <folder>`. `WizardBar.exe --snapshot <folder>` draws every look of the button to PNG files. CI does this on
Windows, uploads them, and prints the 100 % one at the end of its log. The icon, the button's sprite and setup's
pictures come from `scripts/wizard_art.py` ([brand/README.md](../brand/README.md)).
