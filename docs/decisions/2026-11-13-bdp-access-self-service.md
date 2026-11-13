# 2026-11-13 — Wizard names the Big Data Portal tables the person needs; the person requests access

**Owner:** project owner. **Status:** decided (13 November 2026). Supersedes
[2026-10-28 Wizard opens the access request form](2026-10-28-bdp-access-requests.md),
[2026-11-01 Access to the Big Data Portal's datasets](2026-11-01-bdp-dataset-access.md) and
[2026-11-01 Wizard sends the access requests the person approves](2026-11-01-bdp-access-sending.md). Returns to the rule
of [the information catalog decision](2026-10-28-bdp-information-catalog.md): access is the person's own request.

**Context.** Wizard prepared access requests in the Big Data Portal's information catalog (`portal_request_access`),
opened the request form in a visible window of the person's Wizard browser, filled their saved answers into it, kept a
list of prepared requests, and, once the person had submitted one themselves, submitted the ones they approved. The
owner: "Wizard is not requesting access for people anymore in BDP. remove that functionality. It will say: these tables
are the ones you need, please request access. That's it, people then request themselves."

**Options.** (1) Keep the feature and hide it. (2) Keep the saved answers and the request window, drop sending. (3)
Remove it: Gemini says which tables the person needs and the person requests access in the catalog themselves.

**Decision.** Option 3.
- **Gemini names the tables.** When an answer needs tables the person cannot query, Gemini lists them as the catalog
  names them, with each one's catalog page address when it has one and what the analysis needs it for, and tells the
  person to request access themselves in the information catalog. It says the data waits until access is granted and
  never claims that access was requested (system prompt, `portal_guides/bdp.md`).
- **Wizard requests nothing.** Removed: the `portal_request_access` tool, the access request window (opening, filling,
  choosing drop-down options, Next request, sending, the proof from the person's own submission), the saved answers and
  the prepared requests (Settings → Portals), the request card under an answer, the `access_request_proposed` event and
  the `/api/v1/portals/{system}/access-*` endpoints, with `access_requests.py`, `portal_fill.js`, `portal_pick.js` and
  `portal_clicks.js`.
- **The guard stays.** Gemini's own portal steps still refuse every access request inside the tool: Request buttons
  and controls, addresses that start with request, POSTs to an access-request address (`/access-requests`,
  `permissionRequest`, `tableAccessRequest.do`), Superset's `request_access` and GraphQL mutations.

**Consequences.** Nothing in Wizard opens, fills or sends a request form. An `access-requests.json` left in a person's
portal-browser folder by an earlier version is no longer read; it holds their saved answers and prepared list, nothing
from the portals, and can be deleted. Old answers that showed a request card show the answer alone, and their
`access_request_proposed` events are no longer streamed. The visible window of the Wizard browser is the sign-in window
only. AGENTS.md's exception for access requests is replaced by this rule.

**Evidence.** `tests/unit/test_portals.py` (the tool and the endpoints are gone; the refusals of request controls,
addresses and POSTs), `tests/integration/test_portal_browser.py` (a refused Request access click and POST in a real
browser; the guide offers no request form).
