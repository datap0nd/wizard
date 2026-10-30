# 2026-10-30 — Export settings: the same Wizard on another PC

**Owner:** project owner. **Status:** decided (30 October 2026).

**Context.** The owner: "I want to set exactly the same app on a different PC... I want to export my settings file
basically. and import it there." Settings reach a PC only in a provisioning file (`wizard.provision`), stored with
DPAPI on import, so copying `%LOCALAPPDATA%\Wizard` does not work: the secrets open only for the Windows account that
stored them. A person who changed Settings after importing the company file had no file that holds both.

**Decision.**
- **Export settings…** in WizardBar's tray menu, next to **Import a settings file…**. The service builds the file
  (`settings_pane.export`, `POST /internal/v1/desktop/export`); only WizardBar on this PC may ask, with its per-launch
  control token on the loopback address. WizardBar saves it where the person chooses.
- **What it holds:** the keys of the imported company file and every Settings field, each with the value this PC uses
  (environment > `.env` > this PC's Settings > company file), passwords and tokens in plain text. It is an ordinary
  provisioning file, checked as one on the way out and on import, named after the company file with "(exported)".
- **What it leaves out**, as any provisioning file does: the per-PC values (`provisioning.LOCAL_ONLY`), the knowledge
  base's write token (`PC_CHOSEN`, owner decision of the same day: only the person who enters it on a PC holds it), the
  model once picked in the app (no longer a setting), the Gemini sign-in and the portal sign-ins (never settings), and
  the conversations.
- **The person is told first** that the file holds the passwords in plain text, and afterwards what to do on the other
  PC and to delete the file once it is imported.

**Evidence.** `tests/unit/test_settings_pane.py` (precedence, what is left out, a round trip through import on another
data folder, nothing to export), `tests/unit/test_desktop.py` (only with the control token; the menu item and the
endpoint agree). WizardBar built with warnings as errors.
