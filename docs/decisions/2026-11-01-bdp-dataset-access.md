# 2026-11-01 — Access to the Big Data Portal's datasets: the form's own fields, drop-downs, and prepared requests

**Owner:** project owner. **Status:** decided (1 November 2026); updated the same day (reaching the table and opening its form, below). Amends
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

## Update, 1 November 2026: the window reaches the table and opens its request form

**Context.** The first request on the work PC (a table found in the catalog) opened the catalog's start page: "the
request form opens the generic website. doesnt open the reqeust form." Gemini had found the table through the
catalog's search, which gives no page address, and the tool fell back to the start page without a word.

**Decision.**
- **A table needs its way there.** `portal_request_access` refuses a request for tables whose address is a start page
  of the portal (the catalog's or Superset's; the person's saved request page excepted). Gemini gives the table's own
  page, or, for a catalog that keeps one address whatever table is open, `open_steps`: the navigation it ran with
  `portal_run` from that address to the table's page (goto, fill, select, click, press Enter, wait; at most 12), and
  `form_button`, the text of the control there that opens the request form (it may request access; a name that saves,
  sends, submits or confirms is refused).
- **The window follows them.** In the person's window, Wizard runs those steps with the same refusals as Gemini's own
  steps (no click on a control named for a change, only this portal's pages), then presses the control that opens the
  form (form_button, else a usual name such as Request access when exactly one is shown; never a POST form's submit
  button), once. For four seconds after that press, any request the portal's write rules (`write_reason`) call a
  change is stopped: if pressing it would file the request in one click, nothing is filed, and the note on the page
  says so and asks the person to press it themselves (their own press later goes through). The form then fills as
  before; the person checks it and submits.
- **What was prepared before.** A prepared request that opens only a start page says so in the window instead of
  pressing anything; the guide lists them (`to_prepare_again`), and preparing a table again replaces its unopened
  request in place. Where a request form appeared is kept (`form_pages_seen`, last 20) so Gemini learns the catalog's
  addresses.

**Consequences.** AGENTS.md's exception names the steps and the guarded press. API `access-request` takes
`open_steps` and `form_button`; a card opens its prepared request by id. The request task finds once how a dataset's
page is reached and gives the way for each.

**Residual risk.** A step proved in the background can fail in the window when the page changed; the note says which
step and the person finds the table. A one-click request whose write the rules do not recognise by name would not be
stopped; the request window's press happens only after the person's own Open, on a control Gemini named or a usual
request name, and AGENTS.md's network rules remain the backstop.

**Evidence.** `tests/unit/test_access_requests.py`: start pages refused for a table (catalog, with a trailing slash,
Superset), a table page and open_steps accepted, bad steps and buttons refused, the list keeping the way there and a
table prepared again replacing its unopened request, `to_prepare_again`, and the API's route for a card no longer on
the list. `tests/integration/test_portal_browser.py`, in a real Chromium: a catalog at one address, reached by search,
Enter and the result, its Request access pressed and the form filled with nothing sent; a one-click Request access
whose POST is stopped and reported, and goes through when the person presses it later; a request prepared with only
the start page says so. `AccessRequestCard.test.tsx`.
