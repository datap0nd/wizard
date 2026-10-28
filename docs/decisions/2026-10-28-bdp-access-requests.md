# 2026-10-28 — Wizard opens the access request form, filled from the person's saved answers

**Owner:** project owner. **Status:** decided (28 October 2026). Builds on
[the information catalog decision](2026-10-28-bdp-information-catalog.md), which made every access request the
person's own step and refused it inside the tool.

**Context.** The owner: "I want wizard to open the request access page at least. There also should be a form for access
requests (we fill in the same fields over and over) that we should be able to predefine in wizard."

**Options.**
1. A link to the catalog only. Opens the page but leaves every field to the person, every time.
2. Wizard submits the request itself. That is a write in a corporate system in the person's name; AGENTS.md does not
   allow it, and nothing the owner asked for needs it.
3. Wizard opens the request page in a visible window and fills the person's saved answers into the form; the person
   checks it and submits it.

**Decision.** Option 3.
- **The saved form.** Settings → Portals → **Access request form**: the fields the person answers on every request
  (label as the form names it, and their usual answer), plus an optional request page when the catalog has one page for
  every request. Kept on this PC for this person only (`access-requests.json` in their Wizard browser folder). After a
  window closes, the labels Wizard saw on the form are offered as fields to add.
- **Opening it.** **Open the request page** in the settings, or the card Gemini's `portal_request_access` puts under
  an answer when the person lacks access to a table it needs (the tables, the page, and this request's own answers
  such as the reason). Gemini only proposes: nothing opens until the person presses **Open the request form**.
- **The window.** Wizard's own browser opens visibly on the request page (the table's page or the request page). As
  the form appears, including after the person presses Request access themselves, Wizard writes the saved answers and
  this request's into fields whose label matches (label, `aria-label`, a label beside or above the field, placeholder),
  outlines them and shows a note: check every field, then submit it yourself.
- **What protects the catalog and the person.**
  - Wizard fills only empty fields, and never one the person cleared; never a password field.
  - It never clicks, presses a key or submits a form. The person submits; their window has no write filter, like the
    sign-in window.
  - It fills only pages of that portal's own hosts and company domain.
  - Gemini's own steps (`portal_run`) still refuse every access request, and wait until the window is closed.
  - Every open and every save of the form is audited (`portals:access_request`, `portals:access_form`).

**Consequences.**
- AGENTS.md: the portal exception names the request window and its protections.
- New: `access_requests.py`, `portal_fill.js`, the access request window in `portal_browser.py`,
  `portal_request_access`, API `GET`/`POST /api/v1/portals/{system}/access-form` and
  `POST /api/v1/portals/{system}/access-request`, `AccessRequestForm.tsx`, `AccessRequestCard.tsx`.
- **Residual risk.** Matching by label can put an answer in the wrong field when two fields have similar labels; the
  outline and the person's check before submitting are the backstop. A form built from custom drop-downs (not
  `select` elements) is left for the person to fill, and the card and status list the answers that found no field.

**Evidence.** `tests/unit/test_access_requests.py`: the saved form's limits, the addresses a window may open, what it
fills, Gemini's proposal (never sent), the API and its audit, and a reopened answer keeping its card.
`tests/integration/test_portal_browser.py`, in a real Chromium: a catalog table page whose form appears after
Request access, filled from saved answers (text, label beside, table row, `aria-label`, select), a pre-filled field
and the password left alone, a field the person cleared not refilled, no request sent until the person's own click,
which goes through, the form's labels kept for the settings, and Gemini's reads refused while the window is open.
