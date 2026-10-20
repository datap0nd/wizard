# Task 41 — Discover GSCM and ASAP, and let Wizard explore them

**Goal:** find out what GSCM and ASAP run on and how they sign people in, set them up as portals that Wizard's own
browser may explore (decision 2026-10-20-portal-browser), sign in once, and try one question per portal while the user
watches the click preview. Nothing in this task copies report rows into documents.
**Output:** `content\inbox\gscm\portal-check.md`, `content\inbox\asap\portal-check.md`, `outbox\41-portal-discovery.md`
(internal) and `outbox\41-portal-shareable.md` · **Shareable:** `outbox\41-portal-shareable.md` only (yes/no answers,
platform names, versions and counts; no addresses, report, folder or people's names).
**Model:** `gemini-3.8-flash` is enough.

All `.\docs.ps1` commands run in PowerShell in this folder. If your shell is cmd, use
`powershell -NoProfile -ExecutionPolicy Bypass -File docs.ps1 <command>` instead.

## Rules for this task

- You never sign in to a portal or open a browser yourself. The user signs in, in the window Wizard opens.
- Never ask for, accept or write down a password, token or cookie.
- The portal addresses are internal: they may appear in `content\` and in `outbox\41-portal-discovery.md`, never in
  the shareable file. Do not copy report rows, report names or folder names into the shareable file.

## Steps

1. **The addresses.** Ask the user to open GSCM and then ASAP in their browser, and to copy each address from the
   address bar (the page they normally start from).
2. **Check from this PC.** Run `.\docs.ps1 gscm-check --url "<GSCM address>"` and
   `.\docs.ps1 asap-check --url "<ASAP address>"`. They send anonymous requests only and write
   `content\inbox\<gscm|asap>\portal-check.md`. Read the lines they print:
   - `FAIL ... could not reach`: note the reason (proxy, certificate, blocked) and continue.
   - `platform:` and `clue:`: what the portal runs on (MicroStrategy, SAP BusinessObjects, a company application...).
   - `sign-in:`, `Windows integrated sign-in`, `asks for a user name and password`: how it signs people in. When a line
     says `add <host> to WIZARD_PORTAL_SIGNIN_HOSTS`, note that host for step 3.
   - `MicroStrategy Library REST API answers`: the API an approved adapter would use (ASAP).
   Then run `.\docs.ps1 extract`.
3. **Set them up in Wizard.** Ask the user to open Wizard → ⚙ Settings → Portals and fill in the GSCM and ASAP
   addresses, plus the sign-in host from step 2 if there was one (Company sign-in hosts). Wizard restarts by itself.
   (You never edit `.env` or the settings yourself.)
4. **Sign in once.** In Wizard → Sources → Portals, the user presses **Sign in** next to GSCM. A browser window opens on
   Wizard's own browser profile; they sign in as usual, then press **Done** in Wizard. Same for ASAP. Then **Check**
   next to each: it should say "Signed in". If a check says "Sign-in needed" again, the session did not stick: note
   what the window showed (a device-compliance message, a second sign-in prompt, an error).
5. **One question per portal.** Ask the user to ask Wizard a question whose answer is on one GSCM page, for example
   "On the GSCM portal, find the latest monthly sell-in report and tell me the top 3 models". Watch the click preview
   with them (the stage shows each page with the element Wizard is about to click outlined). Then the same for ASAP.
   For each, note: did it find the report, how many steps it took, any step it refused (a "refused" error names the
   control), any page it could not read (a table drawn as a picture, a canvas chart), and whether the figures matched
   what the user sees in the portal.

## Write `outbox\41-portal-discovery.md` (internal)

Sections, with the check lines or the user's answers they come from:
- **GSCM:** address, platform and clues, sign-in route, reachable from this PC, Wizard sign-in worked, the test question
  (steps, refusals, unreadable pages, figures matched).
- **ASAP:** the same, plus the Library REST API answer and version.
- **Open questions for IT security and the platform teams:** copy the relevant ones from
  `docs\it-questions.md` in the release folder, marking those this task already answered.

## Write `outbox\41-portal-shareable.md`

One table per portal, question | answer: reachable from this PC; platform; version if shown; sign-in protocol and
identity provider product (no host names); Windows integrated sign-in offered; Library REST API answers (ASAP);
Wizard sign-in worked; session still signed in after a restart of Wizard; test question answered (yes/partly/no);
steps taken; refusals (count, and the kind of control: export, share...); unreadable pages (count, and why: picture,
canvas, other); figures matched the portal (yes/no). Then the check lines with every host name replaced by
`<gscm>`, `<asap>` or `<identity provider>`.

**Done when:** both check files exist, both portals are set up and checked in Wizard (or the file says why not), one
question per portal was tried and described, and the shareable file has no address, report, folder or person name.
If the user could not sign in or could not try a question, mark the task `partial` in `STATUS.md` and say which
answers are missing.
