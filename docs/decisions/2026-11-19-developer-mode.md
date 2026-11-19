# 2026-11-19 — Developer mode: Tasks and the other developer settings behind a PIN

**Owner:** project owner. **Status:** decided (19 November 2026).

**Context.** Wizard is being handed to people who download it from the company's GitHub and install it themselves. The
owner: "I just need the app to be a bit more beginner friendly too. I want you to keep tasks and other 'developer' stuff
behind a developer mode PIN code menu protection." Until now Settings opened on every section a developer uses: the
knowledge base and its write token, the Pages site, the database, NERP, the dashboards' token, Metronome, the source
order, the run limits, the proxy, diagnostics, the prompt queue, Tasks and the portal maps. The tray menu offered
**Export settings…**, which writes every password in plain text.

**Decision.**
- **A beginner's Settings** shows Quick setup at the top, the company settings file's name, **Portals** with only the
  sign-in (**Sign in to the portals**, **Check sign-in** and why the sign-in ends; no addresses, no maps), **Version and
  updates**, and **Developer mode** at the bottom. Quick setup is unchanged: it still imports the settings file, links
  Gemini, signs in to the portals and tests every connection this PC has.
- **Developer mode** shows everything else: every other section with its fields and tests, Save, the prompt queue,
  Tasks, the portal maps (Map, Publish), **Share as case** in a chat, and in the tray menu **Sync the knowledge base
  now** and **Export settings…**. A section added to Settings later needs developer mode unless it is added to
  `EVERYDAY` in `SettingsDialog.tsx`.
- **The PIN.** The person types the owner's PIN in Settings → Developer mode → **Unlock**. The service compares its
  salted SHA-256 (`developer_mode.PIN_SHA256`) and, if it matches, keeps developer mode on for this PC until the person
  presses **Turn off developer mode**, across restarts and updates. A wrong PIN says "That PIN is not right." and waits
  a second. The PIN's digits are not in this repository, which is public and copied to the company's GitHub; to change
  the PIN, put the new digest in `developer_mode.py`.
- **This PC's own.** The flag is a file of its own in the data folder (`developer-mode.json`), not a setting: no
  settings file sets it and **Export settings…** never carries it, so a PC set up from an exported file starts as a
  beginner's. Only the person at the PC on their own install can turn it on or off (`settings_owner`, as every Settings
  call); a shared server has none.
- **It hides; it is not a password.** Anyone determined can read the digest and the code. Nothing it hides depends on it
  for safety: the write token stays on the PC that entered it, the control token guards the tray's calls, and the APIs
  answer as before (the release's smoke test still lists the tasks through them). The audit log records each turn on,
  refusal and turn off.

**Evidence.** `tests/unit/test_developer_mode.py` (the digest, on and off by the person at the PC only, a wrong PIN,
kept across a restart, a server without it, the tray's status, never in an export, a damaged file read as off, the
tray's items following it); `apps/web/src/components/SettingsDialog.test.tsx` (a beginner's sections only, a wrong
then the right PIN, turning it off); WizardBar built with warnings as errors.
