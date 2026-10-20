# The desktop app (WizardBar)

Wizard as an always-on assistant: a small **Ask Wizard** tab at the top of the screen. A click, or Ctrl+Alt+W from any
app, opens a prompt panel; Esc hides it. A question keeps running while the panel is hidden, and a notification says
when the answer is ready. The decision behind it is
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
| `%LOCALAPPDATA%\Wizard` | `.env`, `data\` (conversations, Gemini sign-in, provisioning, knowledge base), `logs\`, WebView2 profile, `bar.json` | kept | kept |

No admin rights are needed. Setup adds a Start-menu entry and, by default, a "start when I sign in" entry
(`HKCU\...\Run`). The tray menu can turn that off.

## One-time setup (owner)

### 1. The knowledge-base repository

Create a **private** repository in the company's GitHub organisation (for example `acme/wizard-content`) from
[`templates/content`](../templates/content/README.md). Use the same layout as `WIZARD_CONTENT_DIR`:
`knowledge/<area>/<note>.md`, optionally `contracts/sources/<platform>.json`. Only you need access. Users never get a
GitHub account or a link to it.

Every sync runs `scripts/validate_content.py`'s rules. A commit with errors (a note without front matter, something
that looks like a credential) is not applied, and PCs keep the previous version. Validate before pushing:

```bash
uv run python scripts/validate_content.py ../wizard-content
```

### 2. A read-only token

GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → Generate:
- Resource owner: the organisation; Repository access: **only** `acme/wizard-content`.
- Permissions: Repository → **Contents: Read-only** (Metadata read-only is added automatically). Nothing else.
- Expiration: as long as the organisation allows. Note the date: when it expires, Wizard keeps its last copy and
  "About Wizard" shows the GitHub error until PCs import a new file.

If the organisation requires approval for fine-grained tokens, approve it under the organisation's settings.

### 3. The provisioning file

Keep the company settings in a `KEY=value` file outside every Git repository (`company.env` and `*.provision` are
git-ignored here, and `scan_secrets.py` refuses `.provision` files and GitHub tokens):

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
```

```bash
uv run python scripts/make_provision.py company.env --name "ACME pilot" --out wizard.provision
```

Any `WIZARD_*` setting can go in, except the ones each PC decides (data folder, port, identity, content folder). Names
ending in `_PASSWORD`, `_TOKEN`, `_SECRET` or `_KEY` are stored with Windows DPAPI on the PC.

The PostgreSQL account must be **read-only by its grants** (SELECT on the views Wizard may use, nothing else). Everyone
who has the file can use it, also outside Wizard.

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
  shows "Install update…". Wizard downloads it, checks its size, SHA-256 and version against the manifest, installs it
  silently and starts again. It never downgrades.
- **Knowledge:** push to the knowledge-base repository. PCs pick the change up within 30 minutes and switch to it after
  10 minutes without use, or at once with **Sync the knowledge base now**.
- **Settings or credentials:** make a new `wizard.provision` and have people import it (or run setup again next to
  it). It replaces the previous one.

## The tray menu

| Item | What it does |
|---|---|
| Ask Wizard (Ctrl+Alt+W) | Opens the panel |
| Open Wizard in the browser | The full app (sidebar, history, sources) at `http://127.0.0.1:8771` |
| Sync the knowledge base now | Checks GitHub now and restarts the service on a new version |
| Show the button at the top of the screen | Hide the tab (Ctrl+Alt+W and the tray still work) |
| Start Wizard when I sign in | The `HKCU\...\Run` entry |
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

## Building it yourself

```bash
dotnet build apps/desktop/WizardBar/WizardBar.csproj -c Release -o artifacts/desktop/payload/bar   # also builds on Linux
python scripts/build_desktop_payload.py --out artifacts/desktop/payload                             # needs committed files
ISCC installer\Wizard.iss                                                                            # Windows, Inno Setup 6
```

For development without the installer, run WizardBar with `--install <folder with app\ and runtime\python\>` and
`--home <folder>`.
