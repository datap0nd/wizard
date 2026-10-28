# 2026-10-28 — The Big Data Portal is its information catalog and Superset

**Owner:** project owner. **Status:** decided (28 October 2026); access requests are opened and filled for the person
since [the access request decision](2026-10-28-bdp-access-requests.md) the same day. Amends
[2026-10-12](2026-10-12-bdp-superset.md) and [2026-10-23](2026-10-23-portal-browser.md).

**Context.** Wizard treated the Big Data Portal (BDP) as Superset alone: one address (`WIZARD_PORTAL_BDP_URL`,
"Superset's start page"), one sign-in tab, and a guide that said access is "requested in BDP". The owner: "For bigdata
portal, there's two things: the information catalog, where we search for tables and request access to them. Then we
have superset, the actual query tool." And: "In the wizard menu, we should have both links."

**Decision.**
- **Two addresses, one portal.** Settings → Portals has **Big Data Portal: information catalog**
  (`WIZARD_PORTAL_BDP_CATALOG_URL`) and **Big Data Portal: Superset** (`WIZARD_PORTAL_BDP_URL`, unchanged key, so
  existing settings files keep working). BDP stays one system (`bdp`) with one set of rights; either address alone
  is enough to turn it on. Superset is its start page when set.
- **The browser knows both.** Both hosts are reachable; **Sign in to the portals** opens a tab for each, and **Check
  sign-in** reports each. `portal_guide` lists both addresses (`applications`). A step's `/path` resolves on the
  application the page is on, so a path read on the catalog stays on the catalog.
- **Gemini's guide.** Find the table in the information catalog (explore it, then call its own search request),
  then query it in Superset. The catalog's product is not known yet, so the guide gives no catalog helper; work-PC
  task 40 records it.
- **Access is the person's own request.** Wizard never requests access to a table. Inside the tool, on top of the
  existing write rules: clicks on controls named Request are refused, `request` is a write verb (which also stops
  Superset's own `request_access`), a POST to an access-request address (`/access-requests`, `permissionRequest`) is
  refused, and so is a GraphQL mutation. Listing one's own requests (a GET) still reads. When the answer needs a table
  the person cannot query, Gemini names it and points them to the information catalog.

**Consequences.**
- `portals.py`: `PARTS`, `Part`, `Portal.parts`, `.pages`, `.hosts`; the write and click rules above.
  `portal_browser.py`: sign-in tabs, the check and relative paths per application. `GET /api/v1/portals` lists a
  portal's `parts`; the Portals section shows "Big Data Portal (Superset, information catalog)".
- Work-PC task 40 also asks for the catalog's address, product and request route.
- **Residual risk.** A catalog that files an access request through a neutrally named POST (neither a `request` verb
  nor an access-request name) would not be stopped by name; the network rules remain the backstop the 23 October
  decision describes, and the catalog's real requests are first seen on the work PC.

**Evidence.** `tests/unit/test_portals.py`: both addresses and either alone, reachable hosts, relative paths per
application, access-request paths (and a GSCM-style list read that is not one), Superset's `request_access`, GraphQL
mutations against searches, Request clicks, the settings fields and `GET /api/v1/portals`. `tests/integration/test_portal_browser.py`, in a real Chromium with the
catalog and Superset on two hosts: the guide's addresses, a catalog table read as evidence, a path that stays on the
catalog, a refused Request access click and POST (never reaching the server), and the per-application sign-in check.
