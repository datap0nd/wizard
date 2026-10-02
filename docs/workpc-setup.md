# Work-PC setup, tasks and feedback loop

Wizard installs on a work PC the same way the B2B tools do: three PowerShell scripts in one folder, no admin rights, no
git, no pip and no Node build. The PC only ever **pulls** `main` from GitHub; nothing is pushed from it.

```
 developer (Claude)            GitHub datap0nd/wizard               work PC  (e.g. C:\Wizard)
 ────────────────────          ───────────────────────────          ─────────────────────────────────────────────
 fix + push main      ───────▶ main  +  release portable-…  ──────▶ .\update_app.ps1   (stop, install, start)
                                                                     .\start.ps1        (open Wizard, give it a go)
 reads feedback       ◀─────── (you paste the file)         ◀────── gemini → /wizard:tasks → outbox\FEEDBACK-FOR-CLAUDE.md
```

## Prerequisites (once)

| Need | Why | Check |
|---|---|---|
| `DG_GITHUB_TOKEN` (the token the B2B / data-governance installers already use) with **Contents: read** on `datap0nd/wizard` | setup downloads the private repository and its portable runtime release | setup explains a 404 if the repository is not added to the token |
| Node.js and Gemini CLI, signed in with your enterprise Google account | Wizard's analyst runs through Gemini CLI; you also use Gemini CLI for the documentation tasks | `node --version`, `gemini --version` |
| Outbound HTTPS to `api.github.com`, `github.com` release downloads, `accounts.google.com`, `oauth2.googleapis.com`, `codeassist.google.com`, `cloudcode-pa.googleapis.com` | install, Google sign-in, Gemini | task 00 tests each one |

`GOOGLE_CLOUD_PROJECT`: if your Gemini CLI needs it (enterprise Code Assist), set it in your user environment before
the first setup and setup copies it into `.env`, or add it to `.env` yourself.

## First install

In a new PowerShell window:

```powershell
mkdir C:\Wizard; cd C:\Wizard
$h = @{ Authorization = "Bearer $env:DG_GITHUB_TOKEN"; Accept = 'application/vnd.github.raw' }
Invoke-WebRequest https://api.github.com/repos/datap0nd/wizard/contents/setup.ps1 -Headers $h -OutFile setup.ps1 -UseBasicParsing
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Setup does, in order:

1. Resolves the newest `main` commit and downloads exactly that commit (if the downloaded `setup.ps1` is newer than the
   one running, it continues with the new one).
2. Copies it to `releases\<commit>-<time>\`.
3. Downloads portable Python 3.13 and the locked libraries from the `portable-…` GitHub release, verifies every
   SHA-256, unpacks them once into `runtime\` and `dependencies\` and reuses them on later updates.
4. Creates `.env` with first-run defaults; it only adds missing keys and never changes yours:
   - `WIZARD_AGENT_RUNTIME=gemini-cli`, `WIZARD_GEMINI_MODEL=gemini-3.8-flash`, `WIZARD_DATA_DIR=data`.
   - `WIZARD_LOCAL_USER_EMAIL` from `whoami /upn`.
   - The Gemini CLI and Node paths it found.
5. Creates `content\` (documentation template), `outbox\` and `data\`, and refreshes `tasks\`, `GEMINI.md`,
   `.geminiignore` and the `/wizard:tasks` command.
6. **Checks the new release** with `run.py --check`:

   | Check | What it confirms |
   |---|---|
   | Application | Starts with your `.env` |
   | Content | Validates, when it is enabled |
   | Gemini CLI | Launches offline (fake model replies, no sign-in used) and offers Wizard's 15 read-only tools, Wizard's system prompt and nothing from the folder's `GEMINI.md` |

   A release that fails to start is never selected; the previous one stays active. A Gemini CLI problem is a warning
   only, so replay mode still works.
7. Selects the release (`current.json`, `previous.json`), copies the three scripts to the folder and keeps the three
   newest releases.

## Start and give it a go

```powershell
.\start.ps1
```

This opens <http://127.0.0.1:8770>, and the window shows Wizard's log.

1. Sign in as **your name (Owner (local test))**. This identity uses your real work email and has rights to every
   platform. The other identities are SYNTHETIC test people with narrower rights, so you can see how permissions behave.
2. Open **Account → Sign in with Google**, sign in with *your* enterprise account and paste the code Google shows.
   Wizard keeps this sign-in in its own isolated Gemini home under `data\`; it does not reuse your personal Gemini CLI
   sign-in.
3. Ask one of the three demonstration questions. Until real content is enabled, the data is SYNTHETIC, labelled so on
   every answer.

No Gemini yet? Set `WIZARD_AGENT_RUNTIME=replay` in `.env` and restart: the recorded answers stream through the same UI.

## Gemini CLI tasks (documentation and checks)

```powershell
cd C:\Wizard
gemini -m gemini-3.8-flash
```

The first time, Gemini CLI asks whether you trust this folder: choose **Trust folder**. Project commands and
`GEMINI.md` load only in a trusted folder, so without this `/wizard:tasks` is unknown.

Then type `/wizard:tasks`, or `/wizard:tasks 10-12` to limit the range. Gemini reads `tasks\START_HERE.md`, works
through the numbered tasks in order, and asks you whenever a task needs a decision. It tracks progress in
`outbox\STATUS.md`, so you can stop at any time and run `/wizard:tasks` again later to resume.

| Task | What Gemini does | Internal output | Shareable output |
|---|---|---|---|
| 00 | Environment report: versions, settings present, installation check, network reachability | — | `outbox\00-environment.md` |
| 10 | Inventory of the documents you dropped in `content\inbox\<platform>\` | `outbox\10-inventory.md` | its counts table |
| 11 | One guide per platform (how to navigate it, what its reports are for) | `content\knowledge\platforms\*.md` | — |
| 12 | Report catalogs (one JSON per platform, every report navigation-only) and the source register | `content\contracts\sources\*.json`, `content\register\source-register.csv` | — |
| 13 | Business definitions (sell-in, sell-out, switchers, …) | notes under `content\knowledge\` | note ids and status |
| 14 | Can the catalog answer the three demonstration questions? | `content\register\coverage.md` | `outbox\14-coverage-summary.md` |
| 15 | Runs Wizard's content validator until it reports 0 errors | — | `outbox\15-validation.md` |
| 16 | Closed questions for each data owner | `content\register\open-questions.md` | counts |
| 17 | Switch Wizard to the real catalog (only after your yes) | `.env` | `outbox\17-switch.md` |
| 90 | Feedback pack for the developer | — | `outbox\FEEDBACK-FOR-CLAUDE.md` |

`content\` is internal: it never leaves the PC through Wizard. Make it its own internal Git repository when you are
ready (see [documentation-guide.md](documentation-guide.md)). Each task states what is shareable; the shareable files
in `outbox\` are written without internal names, and you read each one before you share it.

## The loop

1. You run `.\start.ps1`, try Wizard and run the tasks.
2. You run task 90, read `outbox\FEEDBACK-FOR-CLAUDE.md`, and paste it (plus anything else you noticed) to Claude.
3. Claude fixes the issues and pushes `main`.
4. You run `.\update_app.ps1`. It stops Wizard, installs the new `main`, checks it and starts it again in a new window.
   `.env`, `data\`, `content\` and `outbox\` are kept.
5. Repeat.

To roll back by hand, copy `previous.json` over `current.json` and run `.\start.ps1`.

## Folder layout

| Path | Owner | Kept across updates |
|---|---|---|
| `setup.ps1`, `start.ps1`, `update_app.ps1` | Wizard | replaced |
| `releases\`, `runtime\`, `dependencies\`, `.downloads\`, `current.json`, `previous.json` | Wizard | managed |
| `tasks\`, `GEMINI.md`, `.geminiignore`, `.gemini\commands\wizard\` | Wizard | replaced |
| `.env` | you | yes (only missing keys are added) |
| `data\` | Wizard (database, each user's Gemini sign-in) | yes; never share it |
| `content\` | you | yes |
| `outbox\` | you | yes |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot read main of datap0nd/wizard (HTTP 404)` | Add `datap0nd/wizard` to the token's repository access (Contents: read). |
| `The portable runtime release … is unavailable` | Proxy or token; task 00 shows which host is blocked. |
| `WARN Gemini CLI …` during setup | Read the line: Node or Gemini CLI path not found, or the CLI version changed what it sends. Paste it to Claude. |
| `The new release failed its check` | The named `.env` setting is invalid; fix it and run `.\setup.ps1` again. The previous release is still active. |
| Port 8770 is taken | Set `WIZARD_PORT=8771` in `.env`. |
