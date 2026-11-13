# 2026-11-13 — Quick setup: a new person's first steps, at the top of Settings

**Owner:** project owner. **Status:** decided (13 November 2026).

**Context.** The owner: "When someone downloads wizard, there should be a 'quick setup' in settings at the top button.
This will take them through Wizard, how it works, through the gemini sign in, through importing a settings file, etc."
Until now a new person had to find each piece alone: **Import a settings file…** in the tray menu, the Gemini link in
Account, the portals' sign-in in Settings → Portals.

**Decision.**
- **Quick setup** is the first thing in Settings (a button above every section), and **Quick setup…** is in WizardBar's
  tray menu. It opens by itself once, the first time Wizard starts on a PC whose person has not linked Gemini yet
  (remembered in the page's storage; never again by itself, and never where the page cannot remember it).
- **Seven steps**, each skippable and reachable from the step list: Welcome (what Wizard is); How it works (asking,
  Gemini's analysis, read-only with evidence and data modes, attached files); Settings file; Gemini; Portals; Check;
  Done (what is set up and what is left, with a way back to each).
- **Settings file.** The person chooses `wizard.provision`; the page sends its text to `POST /api/v1/settings/import`
  (the person at their own install only, as every Settings call). The service checks it as an import at start-up checks
  one (`provisioning.parse`), stores it as the company file (secrets through DPAPI), records the setting names in the
  audit log, and restarts when no question or queue is running, as Save does. A file that is not valid stores nothing
  and says why. The person is told to delete the file they chose: it holds passwords in plain text. The tray's
  **Import a settings file…** and a file beside `WizardSetup.exe` work as before.
- **The settings file comes before the Gemini sign-in**: it can set the Gemini project and the company's Google domains
  the sign-in needs.
- **Gemini** is the same sign-in as Account (the person's own enterprise Google account, the code pasted back); **Portals**
  opens the same visible Wizard browser window for the person to sign in; **Check** runs each Settings connection test
  this PC has a value for (knowledge base, database, NERP, dashboards, Metronome) with its saved settings, and shows
  whether Gemini is ready. Quick setup changes nothing the rest of Settings could not, and sends nothing anywhere else.

**Evidence.** `tests/unit/test_settings_pane.py` (the import: the person at the PC only, an invalid file or a per-PC key
refused with nothing stored, secrets encrypted, the restart, the values Wizard loads afterwards);
`apps/web/src/components/QuickSetup.test.tsx` (every step to Finish, the import and restart, a refused file, the
Gemini sign-in, the portals window, only the configured connections tested). WizardBar's menu item: built by the
`desktop` workflow with warnings as errors.
