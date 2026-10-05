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
| Optional: `DG_GITHUB_TOKEN` (the token the B2B / data-governance installers already use) | The repository is public, so setup works without it, but anonymous GitHub API calls are limited to 60 per hour per IP address, which an office network shares. Setup uses 2 or 3 per run (archives come from the public download links, not the API). | setup names a rate-limit refusal (HTTP 403) |
| Node.js and Gemini CLI, signed in with your enterprise Google account | Wizard's analyst runs through Gemini CLI; you also use Gemini CLI for the documentation tasks | `node --version`, `gemini --version` |
| Outbound HTTPS to `api.github.com`, `github.com` release downloads, `accounts.google.com`, `oauth2.googleapis.com`, `codeassist.google.com`, `cloudcode-pa.googleapis.com` | install, Google sign-in, Gemini | task 00 tests each one |

`GOOGLE_CLOUD_PROJECT`: if your Gemini CLI needs it (enterprise Code Assist), set it in your user environment before
the first setup and setup copies it into `.env`, or add it to `.env` yourself.

## First install

Only `setup.ps1` is needed, as with B2B. It creates everything else.

1. Create an empty folder, e.g. `C:\Wizard`.
2. In it, create `setup.ps1` with the contents of [`setup.ps1`](../setup.ps1) from `main`. Open
   <https://github.com/datap0nd/wizard/blob/main/setup.ps1>, use **Copy raw file**, paste it into Notepad, then
   **Save as** `setup.ps1` with *Save as type: All files*.
3. Optional token, recommended on an office network: if `DG_GITHUB_TOKEN` is not already an environment variable,
   create `.env` in the same folder with one line, `DG_GITHUB_TOKEN=<token>`.
4. In PowerShell, in that folder:

   ```powershell
   .\setup.ps1
   ```

   If the execution policy refuses it, use `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`.

It does not matter that the pasted copy gets old. Setup always installs the newest `main`, and if `main` has a newer
`setup.ps1` it continues with that one. It then replaces the folder's `setup.ps1` with the current copy.

Alternatively, download it instead of pasting, from inside the folder:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/datap0nd/wizard/main/setup.ps1 -OutFile setup.ps1 -UseBasicParsing
```

Unlike B2B, setup needs no Administrator rights and installs no Windows service. Wizard runs each question through
*your* Gemini CLI and protects your Google sign-in with your Windows account. A service account could use neither, so
Wizard runs in your session through `start.ps1`.

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
5. Creates `content\` (documentation template), `documents\quiz-questions\`, `documents\quiz-answers\`, `outbox\` and
   `data\`, and refreshes `tasks\`, `templates\` (the quiz page), `docs.ps1`, `GEMINI.md`, `.geminiignore`, the
   `/wizard:tasks` command and the Wizard-owned parts of `content\` (`schema\`, `.gemini\commands\`). Your notes,
   catalogs, registers and inbox are never touched.
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

1. Sign in as **your name (Owner (local test))**. It is always first and has rights to every platform. The other
   identities are SYNTHETIC test people with narrower rights, so you can see how permissions behave; no real Google
   account can be linked to them.
2. Open **Account → Sign in with Google**, sign in with *your* enterprise account and paste the code Google shows.
   The Owner takes its email from the Google account you link, so it does not matter whether `whoami /upn` found your
   email or shows a different domain. Wizard keeps this sign-in in its own isolated Gemini home under `data\`; it does
   not reuse your personal Gemini CLI sign-in.
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
| 20 | Collect your Outlook mail (folders and dates you choose) and files; convert them to text | `content\inbox\` | `outbox\20-collection.md` |
| 21 | One digest per source (best with Gemini 3.5 Flash) | `content\inbox\_digests\` | counts |
| 22 | Topic map and stakeholder list, for you to approve | `content\register\topic-map.md`, `stakeholders.md` | counts |
| 23 | The company documentation, written to the knowledge standard | `content\knowledge\<area>\*.md` | counts |
| 24 | Glossaries and the ambiguous terms Wizard should ask about | `content\knowledge\glossary\` | counts |
| 25 | Coverage: every valuable source cited or explained | `content\register\documentation-coverage.md` | `outbox\25-coverage.md` |
| 30 | One expert quiz per area and stakeholder (HTML page + email text you send) | `documents\quiz-questions\` | counts |
| 31 | Apply the answered quizzes to the notes | notes, `content\register\review-log.md` | counts |
| 90 | Feedback pack for the developer | — | `outbox\FEEDBACK-FOR-CLAUDE.md` |

**Company documentation (tasks 20-31).** Run `/wizard:tasks 20-25`, then `/wizard:tasks 30-31` once you have sent the
quizzes and the answers are back. Gemini CLI cannot open PowerPoint, Excel, Word or Outlook files itself, so
`.\docs.ps1` converts them through Office on this PC (pywin32, read-only, macros off; NASCA-protected files open
because Office opens them as you). `.\docs.ps1 help` lists everything the kit does; it never uses the network or AI.
Task 21 reads every source and is best run with `gemini -m gemini-3.5-flash`; the writing tasks with the strongest
model your plan offers. See [documentation-guide.md](documentation-guide.md).

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
| `Cannot read main of datap0nd/wizard (HTTP 403)` without a token | GitHub's anonymous hourly limit for your office IP was reached: add `DG_GITHUB_TOKEN` (environment or `.env`) or try again later. |
| `Cannot read main … (HTTP 401)` with a token | The token expired: replace it, or remove it (the repository is public). |
| `The portable runtime release … is unavailable` | Proxy or token; task 00 shows which host is blocked. |
| `WARN Gemini CLI …` during setup | Read the line: Node or Gemini CLI path not found, or the CLI version changed what it sends. Paste it to Claude. |
| `The new release failed its check` | The named `.env` setting is invalid; fix it and run `.\setup.ps1` again. The previous release is still active. |
| Port 8770 is taken | Set `WIZARD_PORT=8771` in `.env`. |
| `Wizard could not reach oauth2.googleapis.com …` when you paste the code, or `FAIL Wizard could not reach …` in the check | The message names the cause (untrusted certificate, proxy refused, timeout) and the route Wizard used. Wizard checks certificates against the Windows store and finds the proxy from `HTTPS_PROXY`, your own Gemini CLI `proxy` setting, or the Windows/PAC settings. If it still fails, put the proxy your browser uses in `.env` as `WIZARD_PROXY=http://host:port` and restart. |
| "Test CEO is a synthetic test identity…" | Sign out and choose yourself (Owner). Test identities cannot use a real Google account. |
