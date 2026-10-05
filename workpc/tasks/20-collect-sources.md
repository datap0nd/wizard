# Task 20 — Collect emails and files

**Goal:** gather everything the company documentation should be built from (Outlook mail, decks, workbooks, Word files,
PDFs) and convert it to text you can read. Gemini CLI cannot open PowerPoint, Excel, Word or Outlook files itself;
`.\docs.ps1` converts them through Office on this PC (NASCA-protected files included).
**Output:** `content\inbox\` and `content\inbox\_text\manifest.csv` (internal), `outbox\20-collection.md`
· **Shareable:** `outbox\20-collection.md` only (counts and failure reasons, no names).
**Model:** any; this task does not read the documents yet.

All `.\docs.ps1` commands run in PowerShell in this folder. If your shell is cmd, use
`powershell -NoProfile -ExecutionPolicy Bypass -File docs.ps1 <command>` instead.

## Steps

1. **Check the PC:** `.\docs.ps1 check`. Copy the lines into your notes.
   - pywin32 `BLOCKED`: tell the user that only plain .docx/.pptx/.xlsx files can be read (no protected, legacy or
     .msg files, no slide images) and ask whether to continue anyway.
   - Outlook "not registered": classic Outlook is not installed (the new Outlook cannot be automated). Skip step 3 and
     use step 4.
2. **Files.** Ask the user which folders hold documents about how the company works: strategy and planning decks,
   process descriptions, organisation charts, product and market overviews, definitions, training material, board or
   management packs. Two ways to add them; ask which the user prefers:
   - Copy them into `content\inbox\files\` (subfolders are fine). Only copy; never move or delete the user's files.
   - Or list the folders, one per line, in `content\inbox\_sources.txt`; they are then read where they are. Use this
     for NASCA-protected files: they may refuse to open once copied.
3. **Outlook.** `.\docs.ps1 outlook-folders` lists every mail folder with its item count. Show the list and ask the user:
   which folders (business discussions usually live in Inbox, Sent Items and project folders), since when (suggest the
   last 12 months), and optional keywords to narrow it. Then, per folder:
   `.\docs.ps1 outlook-export --folder "Inbox/Projects" --since 2025-10-01 --max 2000`
   (add `--match word1 word2` for keywords, `--subfolders` to include subfolders). It only reads the mailbox. Items
   marked private or confidential are skipped; never add `--include-private` unless the user insists. If Outlook asks
   whether to allow access, the user should allow it for 10 minutes. Already exported emails are skipped on a re-run.
4. **No classic Outlook:** ask the user to save the relevant emails into `content\inbox\email\` (new Outlook: open the
   email, then "..." > Save as, which gives an .eml file; classic Outlook: drag emails into the folder).
5. **Convert:** `.\docs.ps1 extract`. It converts only new or changed files, so run it again after adding anything.
   Then `.\docs.ps1 status`. If files failed, read the `note` column of `content\inbox\_text\manifest.csv`:
   - "protected" on copied files: put their original folder in `_sources.txt` instead and run `extract` again;
   - "password-protected": ask the user to save an unprotected copy, or leave it out;
   - Office "could not start": ask the user to close dialogs open in Office and run `extract` again.
6. Ask the user whether anything important is missing (a team's folder, a mailbox, a SharePoint library synced to this
   PC). Add it and run `extract` again.

## Write `outbox\20-collection.md`

The `status` lines (counts by kind and status), the failure reasons with counts, and how many Outlook folders were
exported. No file names, folder names, people or subjects.

**Done when:** the manifest exists, every failure has a reason the user has seen, and the user confirmed nothing
important is missing. Record in `STATUS.md` the number of readable sources.
