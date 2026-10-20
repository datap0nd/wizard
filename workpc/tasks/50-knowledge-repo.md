# Task 50 — Put the knowledge base in a private GitHub repository

**Goal:** the company notes in `content\` become a private repository in the company's GitHub organisation. Every
user's Wizard desktop app reads it with a read-only token, and you (the owner) publish updates from this PC with
`.\docs.ps1 kb-publish`. This PC has no git; the publish command writes one commit through GitHub's API.
**Output:** the repository; `outbox\50-knowledge-repo.md` (internal) and `outbox\50-shareable.md` ·
**Shareable:** `outbox\50-shareable.md` only (counts and PASS/FAIL lines; no repository, organisation or people
names).
**Model:** `gemini-3.8-flash` is enough for the steps. If step 1 finds many notes to fix, `gemini-3.1-pro` (or the
strongest model your plan lists under `/model`) writes better fixes.

All `.\docs.ps1` commands run in PowerShell in this folder. If your shell is cmd, use
`powershell -NoProfile -ExecutionPolicy Bypass -File docs.ps1 <command>` instead.

## Rules for this task

- **You never see a token or a password.** The user makes tokens on github.com and types them into files with Notepad
  themselves. Never open `.env`, `private\` or a `.provision` file, and never ask for a token in the chat. If the user
  pastes one anyway, tell them to delete that token on GitHub and make a new one, and do not repeat it anywhere.
- **Only notes and catalogs leave this PC.** `kb-publish` sends `content\knowledge\**\*.md` and
  `content\contracts\sources\*.json`, nothing else. Never copy raw documents, digests, registers, quiz answers or
  stakeholder lists into `content\knowledge\` to get them published. Every file in the repository reaches every PC
  that uses Wizard.
- **The user says yes before anything is written to GitHub.** Show the dry run first (step 6), then publish only after
  a clear yes. `kb-publish` is the only command in this kit that writes outside this PC.
- The repository must be **private** and belong to the **company organisation**, not a personal account.
  `kb-publish` refuses a public repository.

## Steps

1. **Check the notes.** Run `.\docs.ps1 validate`. Fix every ERROR in the notes it names, following
   `content\schema\knowledge-standard.md`, and run it again until there are no errors. Then read the warnings and fix
   the ones about email addresses or phone numbers inside notes. Run `.\docs.ps1 status` and note the counts.
2. **Nothing that must not reach every PC.** Read through `content\knowledge\` once and list anything that should not
   be on every user's PC: personal phone numbers or private addresses, salaries or other HR details, customers'
   personal data, passwords or keys, anything marked confidential for a smaller group. Show the list to the user and
   ask what to do: remove it, reword it, or keep it. Wait for the answer, make the changes, and run
   `.\docs.ps1 validate` again.
3. **Create the repository (the user, in the browser).** Give these steps and wait:
   1. On the company's GitHub (https://github.com, or the company's GitHub Enterprise Server address) click **+**
      (top right) → **New repository**, and choose the company organisation as the **Owner**. If the organisation is
      not offered, an organisation owner must create the repository and give the user write access.
   2. Name: `wizard-content` (or a name the user prefers). Visibility: **Private**. Leave "Add a README", .gitignore
      and licence **off**: the repository must start empty.
   3. Ask the user for the result as `owner/name`, for example `acme/wizard-content`, and for the GitHub address they
      used. When it is not github.com, Wizard needs that server's API address: `https://<that host>/api/v3`.
4. **Two tokens (the user, in the browser).** At `<the GitHub address>/settings/personal-access-tokens/new`
   (fine-grained tokens; on github.com https://github.com/settings/personal-access-tokens/new), make two, one at a
   time:
   1. **Publishing (stays on this PC):** name `Wizard publish (work PC)`; Resource owner: the company organisation;
      Repository access: **Only select repositories** → the new repository; Permissions → Repository permissions →
      **Contents: Read and write**. Expiration: the longest the organisation allows.
   2. **Read-only (for every user's Wizard):** name `Wizard read-only (users)`; same owner and repository;
      **Contents: Read-only** and nothing else.
   If GitHub shows the token as "pending" approval, an organisation owner must approve it first (until then GitHub
   answers 403). Ask the user for both **expiry dates** (not the tokens) for the output file.
5. **Store them on this PC (the user, in Notepad).** Ask the user to open `.env` in this folder with Notepad, add
   these three lines at the end, save and close it (you do not open it):
   ```
   WIZARD_KB_PUBLISH_REPO=<owner/name>
   WIZARD_KB_PUBLISH_TOKEN=<the publishing token>
   WIZARD_KB_READ_TOKEN=<the read-only token>
   ```
   When the repository is on a GitHub Enterprise Server, a fourth line names it (no secret, but the user adds it too):
   `WIZARD_KB_API=https://<that host>/api/v3`.
   These names only serve `docs.ps1`. They do not change how the Wizard installed in this folder runs.
6. **Dry run.** `.\docs.ps1 kb-publish --dry-run`. It checks the notes again, that the repository is private and that
   the account can write to it, then lists what it would add, change and remove. Read the `FAIL` line if there is
   one: 401 means the publishing token is wrong or expired (or `WIZARD_KB_API` is missing, so the token went to
   github.com), 404 means the name is wrong or the token lacks this repository, 403 means it lacks Contents read and
   write or awaits approval. Show the user the list and ask: "Publish these N files to <owner/name>?" Wait for a clear
   yes.
7. **Publish.** `.\docs.ps1 kb-publish --message "First publish of the Wizard knowledge base"`. It prints the commit
   link. Ask the user to open it and check that only `README.md`, `knowledge/` and (if catalogs exist)
   `contracts/sources/` are in the repository.
8. **Check with the users' token.** `.\docs.ps1 kb-check`. `PASS  The read-only token reads …` means every desktop
   app given this token can sync. Remind the user that GitHub cannot tell from outside whether a token can also
   write: they should look once more at the read-only token's page on GitHub and confirm it shows Contents: Read-only.
9. **Give it to the users.** Two ways; ask the user which they want:
   - **One PC (theirs):** in the Wizard desktop app, ⚙ Settings → Knowledge base: the GitHub server (only for a
     GitHub Enterprise Server), the repository and the read-only token → **Test connection** → **Save**. Wizard
     restarts and syncs.
   - **Everyone:** a provisioning file. The user creates the folder `private\` in this folder (Gemini CLI does not
     read it) and, in Notepad, the file `private\company.env` with the company settings, one per line:
     ```
     WIZARD_KB_API=https://<host>/api/v3   (only for a GitHub Enterprise Server)
     WIZARD_KB_REPO=<owner/name>
     WIZARD_KB_TOKEN=<the read-only token>
     WIZARD_PG_HOST=…   WIZARD_PG_PORT=5432   WIZARD_PG_DATABASE=…   WIZARD_PG_USER=…   WIZARD_PG_PASSWORD=…
     GOOGLE_CLOUD_PROJECT=…          (if the organisation uses one)
     WIZARD_GOOGLE_DOMAINS=…         (the company's Google domain, so only company accounts link)
     ```
     (each `WIZARD_PG_…` on its own line; leave out what does not apply). Then run
     `.\docs.ps1 provision private\company.env --name "<company> Wizard" --out private\wizard.provision`
     and tell the user: put `private\wizard.provision` next to `WizardSetup.exe` when handing Wizard out, or let people
     import it from the tray menu (Import a settings file…). It holds the tokens and passwords: share it only inside
     the company.
10. **From now on.** After notes change (tasks 23, 24, 31), run `.\docs.ps1 validate`, then
    `.\docs.ps1 kb-publish --dry-run`, confirm with the user, and `.\docs.ps1 kb-publish`. Users' Wizards pick the change
    up within 30 minutes, or at once with the tray menu's "Sync the knowledge base now".

## Write `outbox\50-knowledge-repo.md` (internal)

- The repository (`owner/name`), the GitHub server, its branch, and the commit link from step 7.
- What was published: notes per area and catalogs (from the publish output), and what step 2 removed or reworded.
- The two tokens by name, with their expiry dates (never the tokens). Add a reminder to make new ones before they
  expire, then publish again and hand out a new provisioning file.
- Where the provisioning file is, if step 9 made one, and who received it.

## Write `outbox\50-shareable.md`

Counts and results only: notes published, catalogs published, the PASS/FAIL lines of `validate`, `kb-publish` and
`kb-check` (with any HTTP status), and how many step-2 findings were fixed. No repository, organisation, people or
note names.

**Done when:** `.\docs.ps1 validate` shows no errors, `.\docs.ps1 kb-publish` printed a commit link (or "nothing
changed"), `.\docs.ps1 kb-check` prints PASS, both output files are written, and `outbox\STATUS.md` has the row
`50 Knowledge base in a private GitHub repository`.
