# 2026-10-20 — Gemini explores the company portals in Wizard's own browser, and the person sees every click

**Owner:** project owner. **Status:** decided (20 October 2026). It changes two AGENTS.md rules (below).

**Context.** Wizard's GSCM and ASAP tools search a report *catalog*: JSON entries in the knowledge base. They never
reach the portals, and every real report is navigation-only until a live API adapter passes a signed parity check
([asap-implementation.md](../asap-implementation.md)). That route waits on the systems' IT teams (sign-in route,
Library URL, project and folder ids for ASAP; the platform itself for GSCM; Superset's API for the Big Data Portal).
Asked how to make Wizard "actually navigate those portals", the owner chose: Wizard explores the portal pages the way a
person does, in a browser of its own, and shows a preview of what it is clicking.

**Options.**
1. Wait for an approved API per system (the existing route). Exact and verifiable, but nothing for months, and only for
   the reports someone onboards.
2. Copy the person's browser session (cookies) into a scraper. Rejected: AGENTS.md forbids copied cookies, and it
   would act outside the person's browser with their credentials.
3. **Wizard's own browser:** Playwright drives the PC's installed Microsoft Edge with a browser profile that belongs to
   Wizard and to this person. They sign in to each portal themselves in a visible window; Gemini then explores with
   read-only steps, and each step is shown to them as a picture.

**Decision.** Option 3, alongside option 1 (an approved API adapter stays the way to *verified* rows).

- **Tools** (`services/connectors/wizard_connectors/tools/portal_tools.py`, offered only where portals are set up):
  `wizard_portal_open` (a portal's start page or a path on it), `wizard_portal_click` (a numbered element of the
  latest page view), `wizard_portal_type` (a text, search or choice field), `wizard_portal_page` (look again, scroll,
  back) and `wizard_portal_read_table` (a table or grid as rows, recorded as evidence). Each page view gives Gemini the
  title, address, visible text, numbered elements and tables; it decides where to go (agent-first).
- **Set-up.** `WIZARD_PORTAL_<NAME>=https://...` per portal (Settings → Portals has GSCM, ASAP and BDP), optional
  `WIZARD_PORTAL_<NAME>_HOSTS` for other hosts the portal uses, `WIZARD_PORTAL_SIGNIN_HOSTS` for the company sign-in
  page, `WIZARD_BROWSER` (`auto` = Edge on Windows, `off` turns portals off). Addresses come from the provisioning
  file or the pane, never from Git.
- **Whose access.** The person's own: each person has their own Wizard browser profile (in their data folder), signs
  in through **Sources → Portals → Sign in**, and Wizard never sees or stores a password. Portals need Wizard on the
  person's own PC; a shared server behind SSO refuses the settings. Only the local Owner gets the portal rights.
  Portals usually keep their session in session cookies, which a browser drops when it closes. So the Wizard service
  keeps its own browser's cookies in memory (never on disk) and restores them when the background browser starts
  again: after the sign-in window and after an idle close. While the sign-in window is open they are saved every few
  seconds. They never come from, or go to, the person's everyday browser.
- **What protects the portals (enforced in `portal_browser.py`, not in Gemini's instructions):**
  - pages load only from the portal's hosts and the sign-in hosts; any other page is stopped before it loads, and the
    tab returns to where it was;
  - downloads are cancelled, uploads and printing are blocked, message boxes are dismissed, and a pop-up on another
    host is closed (one on the portal is followed);
  - a click on a control whose name starts with save, delete, export, download, share, send, e-mail, subscribe,
    schedule, publish, edit, rename, move, approve, sign out (and similar) is refused, as are "New…/Create…/Add…"
    buttons and links whose address names an export, download, delete or sign-out;
  - text goes only into plain text, search and choice fields: never a password field, a code or SQL editor (so BDP's
    SQL Lab cannot be used to run queries; that stays under the
    [2026-10-12 decision](2026-10-12-bdp-superset.md)) or a rich-text editor;
  - a sign-in page (a password field, or a page on a sign-in host) stops the step with "sign in" instructions;
  - the background browser announces itself as headless. If a portal refuses it, `WIZARD_BROWSER_VISIBLE=true` runs
    the same steps in a visible window. Wizard does not disguise the browser;
  - every step has a time limit, a run takes at most 60 portal steps, and page text reaches Gemini marked as untrusted
    data (a page cannot ask it to click, type or go anywhere).
- **The preview.** Before a click, typing or table read Wizard takes a screenshot with the target's position; after
  it, another. They stream to the run as `browser_frame` events and appear on the systems stage as a browser frame:
  address bar, the target outlined with a pointer pressing it, the step's caption, and a strip to step back through
  the pictures. Pictures are stored in the person's data folder, served only to them, kept as long as reports
  (`WIZARD_REPORT_RETENTION_DAYS`) and deleted with the conversation.
- **Labels.** A table read from a page is data mode `LIVE`, connector status `BROWSER_READ`, with the page address,
  the pages that led to it and a digest. It is never labelled verified, and Check my data cannot re-run it.

**Consequences.**
- AGENTS.md allows browser automation for these portals only, through these tools, and lists `BROWSER_READ`.
- New runtime dependency: `playwright` (Python, with its Node driver). It drives the installed Edge, so no browser is
  downloaded. Locks: `uv.lock` and the portable `dependencies.lock.json`; the `desktop` workflow publishes the portable
  runtime release a new lock needs.
- New verification layer `portal-browser` (pytest marker `browser`): BLOCKED where no Chromium-based browser exists.
- **Residual risks (for IT security):**
  - The refusal list works from names. A portal control that changes something but is named like a reading one
    ("OK", "Apply" in an edit dialog) could be clicked. Wizard only reaches it by clicking through, and portals
    normally ask for confirmation, which Wizard dismisses.
  - Company policy may restrict automated browsing of these portals, or block Edge's automation (the
    `RemoteDebuggingAllowed` policy). Wizard then reports the browser as unavailable. The questions are in
    [it-questions.md](../it-questions.md).
  - Screenshots hold whatever the page showed. They stay on the person's PC, under the same retention as reports.

**Evidence.**
- `tests/unit/test_portal_browser.py` drives a real Chromium against a fake portal (`tests/portal_site.py`):
  - folders, clickable `<div>`s, a choice field, a search with Enter, a table and an ARIA grid read as typed rows;
  - export and download refused, the SQL editor refused, and no POST ever reaching the server;
  - a link to another host stopped before any request, a pop-up on the portal followed, a message box dismissed;
  - the sign-in page detected, and the step limit enforced;
  - a session-cookie sign-in surviving the background browser's restart;
  - the refusal rules, settings and entitlements also checked without a browser.
- `tests/integration/test_portal_api.py` replays a whole run: pictures streamed between each call's start and finish,
  served only to their owner, LIVE evidence with the page address, deleted with the conversation.
- `apps/web/src/components/PortalPreview.test.tsx` covers the preview (outline position, stepping back, back to live)
  and the navigation trail.
