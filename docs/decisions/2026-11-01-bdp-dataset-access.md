# 2026-11-01 — Access to the Big Data Portal's datasets: the form's own fields, drop-downs, and prepared requests

**Owner:** project owner. **Status:** decided (1 November 2026). Amends
[the access request decision](2026-10-28-bdp-access-requests.md); builds on [tasks](2026-10-31-tasks.md).

**Context.** Mapping the Big Data Portal keeps reaching dashboards whose tables the person cannot read (permission
errors on whole datasets). The owner: "add tasks for first of all, identify the most relevant datasets in DIS (the BDP
part where tables live, data catalog). Then send access requests for the 50 most relevant ones." The catalog's request
form has a free-text Purpose, then a DPA / DSA box: the requester and email already filled, a Purpose drop-down (the
owner's choice is its fifth option), a Subsidiary Name (Full Legal Name) drop-down searched by typing, and the
subsidiary's full legal address, then Submit. "What I want is for the current request page in settings to have these
predefined boxes, and for me to set the values themselves. Then wizard fills that up everytime."

**Options.**
1. Keep free label/answer rows only. Two fields share the label Purpose, and both drop-downs are the portal's own
   components, not `select` elements, so the 28 October form left them to the person on every request.
2. Predefined fields that know their box and kind, with Wizard choosing the person's saved option in the portal's own
   drop-downs, and a list of prepared requests the person goes through one after another.
3. Wizard submits each request. Not asked for ("wizard fills that up"), and a write in a corporate system in the
   person's name; the 28 October decision keeps the submit with the person.

**Decision.** Option 2.
- **Predefined fields.** Settings → Portals → Access request form shows the form's fields for the Big Data Portal,
  each with an empty answer the person sets: Purpose (free text), and in a DPA / DSA box, Purpose (drop-down: the
  option as the list shows it, or its number), Subsidiary Name (Full Legal Name) (drop-down: the name as listed, or
  its code) and Subsidiary Address. Their own extra fields stay below. A field is its section and label, so the two
  Purpose fields keep separate answers; an answer saved before (a plain "Purpose") fills the free-text one. The labels
  live in the code (`access_requests.PRESETS`); the answers stay on this PC, never in Git.
- **Filling.** A free-text field fills only a text box; a drop-down answer fills only a drop-down (a `select`, a
  portal's own drop-down found by its combobox role, list-box trigger, read-only input or class, or an input that
  lists matches as one types). A section prefers the fields under its heading. For a portal's own drop-down Wizard
  **clicks it open, types the answer into the list's search box when the option is not shown (the answer, then the
  code in its brackets, then its first word; never a number alone), and clicks the matching option**: the same text,
  the same text without its number, the number, or the answer as whole words. When several options only contain the
  answer, or none matches, Wizard clears what it typed, closes the list it opened, and lists the field under "fill in
  yourself". Each drop-down is tried once per page.
- **Prepared requests.** `portal_request_access` also puts the request on the person's list (Settings → Portals →
  Prepared requests, at most 100, oldest first; the same request once). **Open the next request** opens the first one
  not opened yet in the request window; the note Wizard shows at the bottom of the page says which one it is ("3 of
  50"), and its **Next request** button shows the next one in the same window. Each open is noted on the list and
  audited (`portals:access_request`, with `queued`; `by: next` from the window), and the person removes requests from
  the list. A card under an answer that matches a prepared request opens it as that request.
- **Tasks.** `tasks/bdp-relevant-datasets.md` ranks the catalog's datasets (by the dashboards they block, the metric
  notes' measures for the person's markets, maintenance) and keeps the list, with each one's catalog page and whether
  the person has access, in the Big Data Portal's map (topic `catalog-relevant-datasets`).
  `tasks/bdp-request-dataset-access.md` prepares requests for the 50 most relevant ones the person lacks. Both are
  instructions only; the names they find stay in the map.
- **What still protects the catalog and the person.** Wizard never presses a key, never clicks a button (other than a
  `type=button` drop-down trigger), a link or anything that submits, and never submits a form: the person checks every
  field and presses Submit. It clicks only the drop-down the fill script matched by label and an option that appeared
  after it opened (`portal_pick.js`), on that portal's own pages. Empty fields only; a field the person cleared is not
  filled again; never a password. Gemini's own steps still refuse every access request and wait while the window is
  open. Moving to the next request is the person's click on Wizard's note.

**Consequences.**
- AGENTS.md: the access request exception names the drop-down clicks and the prepared requests.
- New: `portal_pick.js`; `access_requests.py` gains presets, sections and kinds, the prepared list and
  `search_texts`; the request window reuses itself for the next request and refreshes even between jobs; API
  `POST /api/v1/portals/{system}/access-request` takes `queued` (an id or `next`), new
  `POST /api/v1/portals/{system}/access-queue/remove`; the settings form and its list; two tasks.
- **Residual risk.** A drop-down that matches no pattern is left to the person, and the field is listed. A click that
  opens a drop-down could, on an unusual page, trigger the page's own script; the click is limited to the matched
  drop-down and options that just appeared, and the person still checks and submits. The real catalog's form is first
  filled on the work PC.

**Evidence.** `tests/unit/test_access_requests.py`: the predefined fields, sections and kinds, a saved answer moving
into its preset, the prepared list (order, once, full, opened ones making room, wrapping Next), the search texts, the
tool adding to the list, the API opening the next one, a named one and a card's, and removing.
`tests/integration/test_portal_browser.py`, in a real Chromium against a form shaped like the catalog's (made-up
options and companies): the free-text Purpose and the DPA / DSA Purpose each get their own answer; a library-style
drop-down whose list opens outside the form is chosen by number; a combobox that matches only on the code is found by
typing the code; the requester and email are left; nothing is sent until the person's Submit; Next request opens the
second prepared request and is audited; a subsidiary the list does not have is left empty with what was typed cleared.
