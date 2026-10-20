# Questions for IT, the platform teams and IT security

Wizard reaches GSCM, ASAP and the Big Data Portal in two ways:

- **Wizard's own browser** ([decision](decisions/2026-10-20-portal-browser.md)): works now, with the person's own
  sign-in. Its figures are labelled Live, never verified.
- **An approved API adapter per platform** ([ASAP](asap-implementation.md), [BDP](decisions/2026-10-12-bdp-superset.md)):
  exact rows that can pass a signed parity check and be labelled verified.

These questions unblock both. Work-PC tasks 40 and 41 answer the ones marked *(task)* from the PC itself, so ask the
teams only for the rest. Each question says what Wizard does with the answer.

## IT security (Wizard's portal browser)

1. **Is automated, read-only browsing of GSCM, ASAP and BDP allowed under the person's own sign-in?** Wizard drives the
   PC's Edge with a separate browser profile, on the person's PC, at a person's pace (one page every few seconds, at
   most 60 steps per question). It never saves, exports, shares or sends. → If not allowed, set `WIZARD_BROWSER=off` in
   the company settings file and wait for the API adapters.
2. **Does company policy block Edge automation** (the `RemoteDebuggingAllowed` Edge policy) or unsigned helper programs
   in `%LOCALAPPDATA%\Programs\Wizard` (Playwright's `node.exe`, Python's `greenlet`)? → Wizard reports the browser as
   unavailable; an exception for Wizard's install folder fixes it.
3. **Will conditional access accept a sign-in from a second Edge profile on a managed PC?** Some tenants require the
   signed-in Edge profile for device compliance. → If it does not, the person sees a compliance message in the sign-in
   window (task 41 records it), and IT decides whether to allow it.
4. **How long do portal sessions last?** → How often people press **Sign in** again.
5. **Are screenshots of portal pages acceptable on the person's PC** (in Wizard's data folder, under report retention,
   default 30 days, deleted with the conversation)? → Otherwise lower `WIZARD_REPORT_RETENTION_DAYS`.
6. **Which sign-in hosts do the portals pass through** (Entra ID, AD FS, a gateway)? *(task 41: `gscm-check` /
   `asap-check` name them)* → They go in `WIZARD_PORTAL_SIGNIN_HOSTS`.

## ASAP (MicroStrategy) IT

1. **The Library base address and project id** for the reports executives use. *(task 41 finds the base)* → The
   API adapter's settings.
2. **The supported API sign-in route:** delegated identity token (`POST /api/auth/delegate`), SAML or OIDC for API
   clients, or trusted authentication. Never a shared account or copied cookies. → Which route `LibraryClient` uses.
3. **May a desktop application hold a per-user identity token** (stored with Windows DPAPI on the person's PC)? → Whether
   people sign in once or for each question.
4. **Rate limits and concurrent session limits** for Library REST. → Wizard's per-question limits.
5. **The folder ids** of the folders Wizard should catalogue. → `scripts/import_asap_catalog.py` drafts the catalog from
   them (metadata only).
6. **Prompt answer formats** for the main prompts (market, month, model). → How Wizard answers prompts through the API.
7. **One approved report for the first parity check:** its prompt values, and for a dossier the chapter, page and
   visualization. → The parity test that turns that report's rows from Live into verified.
8. **Is the MicroStrategy version 11.3 or later?** *(task 41: `asap-check` reads `/api/status`)* → Which API version
   the adapter targets.

## GSCM (IT VOC)

1. **What is GSCM built on?** *(task 41: `gscm-check` recognises MicroStrategy, BusinessObjects, Power BI, Tableau,
   Oracle Analytics, Qlik, Cognos and Superset)* If it is MicroStrategy, the ASAP adapter is reused.
2. **Is there an inventory of the ~100 reports** (names, folders, descriptions, owners)? → It becomes the GSCM catalog
   (`contracts/sources/gscm.json`), so Gemini can search reports before opening the portal.
3. **Does GSCM have an API or export service for applications?** Which one, how it signs in, and whether it applies
   each person's rights. → Whether a GSCM API adapter is possible.
4. **How are rights set:** per report, per market, per role? → How Wizard's entitlements map to GSCM's.
5. **Data refresh and restatement:** when sell-in, sell-out and channel stock refresh, and how long partner data can be
   restated (the platform guide says up to two months). → The freshness and caveats on every GSCM figure.
6. **Partner-level and stock-age reports:** do they exist, and who may see them? → Questions Wizard could answer later.

## Big Data Portal (Superset)

The questions are in [task 40](../workpc/tasks/40-bdp-discovery.md) (*open questions for the BDP team*). For the portal
browser, one more:

1. **Should Wizard browse Superset dashboards and charts** (read-only, the person's own access)? SQL Lab stays out of
   reach. Wizard never types into a code or SQL editor, and running SQL waits for the
   [2026-10-12 decision](decisions/2026-10-12-bdp-superset.md).
