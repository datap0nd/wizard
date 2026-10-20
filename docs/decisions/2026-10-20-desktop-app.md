# 2026-10-20 — Wizard as an always-on desktop app; knowledge base in a private GitHub repository

**Owner:** project owner. **Status:** decided (20 October 2026).

**Context.** Wizard ran as a local web app that each person started with `start.ps1` and opened in a browser. The owner
wants an assistant that is always on: a button at the top of the screen that opens a small prompt box. The knowledge
base must live in a private enterprise GitHub repository that only the owner maintains and browses, while each person's
Wizard can read it. Each person uses their own Gemini sign-in. A read-only PostgreSQL account, and other company
settings, are stored in the app. The owner already shipped a desktop app this way (Scribble: C# .NET Framework 4.8,
WebView2, an Inno Setup installer for the current Windows account, CI on a Windows runner), and reports that installing
software on the work PCs is not restricted.

**Options.**
1. Keep the browser app and add a tray icon written in PowerShell or Python `ctypes`.
2. An Electron or Tauri app.
3. Scribble's recipe: a small C# app hosting Wizard's existing web UI in WebView2, plus Wizard's Python service, both
   installed by one Inno Setup `WizardSetup.exe`.

For the knowledge base, a read-only fine-grained token per company (in the app) or a GitHub App with a token broker
service.

**Decision.** Option 3, with a token in the app.
- **WizardBar** (`apps/desktop/WizardBar`) is the always-on part:
  - a tab at the top edge of the main screen that stays above other windows, never takes the focus, steps aside for
    full-screen apps and slide shows, and can be dragged along the edge;
  - a panel that shows Wizard's compact view (`/quick`) in WebView2;
  - a tray icon with the menu, the shortcut Ctrl+Alt+W, a notification when an answer arrives while the panel is hidden,
    and self-update.
  It starts `run.py --desktop` on the bundled portable Python and keeps it running: it restarts the service when the
  service asks (exit code 75, a new knowledge base), after a crash (with a back-off), and when it stops answering.
- **One installer.** `WizardSetup.exe` contains WizardBar, the app code, the embeddable Python and the locked libraries.
  The archives are the same ones `setup.ps1` installs, with the same SHA-256 checks. The installer runs for the current
  Windows account with no admin rights. CI builds and smoke-tests it on every push. Each push to `main` publishes it to
  the `desktop-continuous` release, and the tray menu installs it after checking its size, hash and version.
- **Knowledge base.** `WIZARD_KB_REPO` (and `_REF`, `_PATH`, `_TOKEN`) name the private repository and a fine-grained
  token with Contents: read-only on that repository alone. A sync works like this:
  - one conditional request for the commit (an unchanged repository costs no rate limit);
  - the zipball is downloaded only when the commit changed;
  - it is unpacked with path checks and validated with the `WIZARD_CONTENT_DIR` rules;
  - it becomes active only if valid, and the previous version is kept.

  Syncs run at start-up and every 30 minutes. The service restarts itself onto a new version after 10 quiet minutes, or
  immediately when someone chooses "Sync the knowledge base now". Users need no GitHub account and never see the
  repository, its history or its drafts.
- **Provisioning file, not a credential in the installer.** The installer and its release are public (this repository
  is public), so they carry no password or token. The owner makes `wizard.provision` with
  `scripts/make_provision.py` and hands it out with the installer. It holds the knowledge-base repository and token,
  the read-only PostgreSQL account, the Gemini project and any other `WIZARD_*` setting.
  - Setup copies the file to `%LOCALAPPDATA%\Wizard`.
  - On its next start, Wizard stores the secrets with DPAPI and the other settings in plain JSON, then deletes the
    plaintext file.
  - Provisioned values sit underneath the PC's own `.env` and environment.
- **Gemini** stays per person. The desktop install uses the code-assist runtime (no Node or Gemini CLI on the PC).
  `WIZARD_GOOGLE_DOMAINS` restricts linking to company Google accounts.
- **Only the person at the PC.** In desktop mode the identity list holds the local Owner only, and the page signs in
  without a picker. The synthetic test identities, the synthetic platforms and the demonstration questions disappear
  once a knowledge base is configured, even before its first sync.

**Why not the alternatives.**
- Option 1 can show a tray icon, but a smooth always-on-top button and an embedded panel need native windows.
  WebView2 is already proven on these PCs by Scribble.
- Option 2 adds a second web runtime and a larger download for no gain.
- A token broker gives per-user revocation, but it is a service to run. The owner chose a token in the app.

**Addendum (same day): settings in the app, model picker, publishing from the work PC.**
- The owner asked to edit the credentials in the app. A settings pane edits a second store, "this PC"
  (`data\settings`, same format and DPAPI as the company file). Precedence is company file < this PC < `.env` <
  environment.
  - Saving a key that `.env` had removes it from `.env`, so a password does not stay there in plain text.
  - Environment variables are shown but locked.
  - Secrets are write-only.
  - Each save is validated by loading the settings again, and rolled back on error.
  - The pane exists only for the local Owner on a person's own install: `run.py --home`, fixture auth.
- A model picker (the owner wants Gemini 3.1 Pro as well as 3.8 Flash) lists the models the person's own quota answer
  covers. It switches the runtime's model without a restart, and each run keeps the model it started with.
- An Update button in Settings asks WizardBar to install the newest release (the same checks as the tray). The
  installer's `BUILD.json` carries the version it is compared with.
- Task 50 and `.\docs.ps1 kb-publish` put the knowledge base in the repository from the work PC, which has no git.
  - Only `knowledge/` and `contracts/sources/` are published: every file in the repository reaches every PC.
  - The tool refuses a public repository and validates before writing.
  - Its settings (`WIZARD_KB_PUBLISH_*`, `WIZARD_KB_READ_TOKEN`) are names the app never reads. They cannot switch the
    work PC's own Wizard away from its `content\` folder, and they can never travel in a company file.

**Consequences and residual risk.**
- Anyone who uses a provisioned PC can recover the knowledge-base token, the synced notes and the PostgreSQL password:
  the app must read them, so they are on that PC. The owner accepted this.
  - What the design prevents: the repository is not browsable, the credentials are never published, and the token is
    read-only on one repository.
  - Rotating either credential means a new provisioning file for every PC.
- Everyone with the file shares one PostgreSQL identity. A person can connect with another SQL tool and bypass
  Wizard's read-only transaction, timeouts and row cap. The protection that remains is the account's grants, so the
  account must have SELECT only. The per-market `postgresql` right gives no protection with a shared account; the local
  Owner already holds it.
- AGENTS.md now permits company content in the owner's private enterprise repository. That repository is the approved
  private location for knowledge notes. This public repository still never holds company content or credentials.
  `scan_secrets.py` now also flags fine-grained GitHub tokens and `.provision` files, and `.gitignore` excludes them.
- `setup.ps1`, `start.ps1` and the Gemini CLI task kit remain the owner's work-PC install for documentation work. The
  desktop app uses port 8771 so both can run on one PC.

**Evidence.**
- `tests/unit/test_desktop.py` covers:
  - provisioning: import, the secrets kept apart, precedence, and refusals;
  - the knowledge-base sync against a fake GitHub: download, the conditional check, an invalid commit kept out,
    folder selection, unsafe archives, and refusals explained;
  - desktop start-up and the control API, including a real `run.py --desktop` process;
  - the domain rule;
  - the C#, installer, CI and Python pieces naming the same files and codes.
- The browser test "the compact desktop view…" covers `/quick` and its messages to the WebView2 host.
- `.github/workflows/desktop.yml`, on a Windows runner:
  - builds WizardBar;
  - assembles the payload and starts the packaged service;
  - checks `/quick` and the control API;
  - builds `WizardSetup.exe`;
  - installs it silently, runs `run.py --check` on the installed copy, and uninstalls it.
- Not yet run: WizardBar itself on a work PC (the window, the panel, the hotkey, the update). It compiles in CI and in
  development, but no automated test drives its windows.
