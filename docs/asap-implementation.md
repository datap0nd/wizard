# ASAP (MicroStrategy / Strategy) implementation — Step 09

## States

| State | Meaning | Shown as |
|---|---|---|
| NAVIGATION_ONLY | Report can be listed (folder → report → prompts) and opened in ASAP with normal SSO; Wizard cannot read numbers | Lock icon, "Navigation only" |
| ROWS_VERIFIED | One owner-approved report read through Library REST matched the owner's original (same user, same prompts, agreed precision) | "Rows verified" |
| SYNTHETIC_FIXTURE | Release A stand-in data | "Rows · synthetic" |

Browsing a report and reading its rows are separate states. Navigation alone never passes the parity gate.

## Tools (discoverable to Gemini)

`asap_search_reports`, `asap_get_report_schema`, `asap_run_report`, with entitlement checks inside each tool, bounded rows
(≤500) and evidence capture. For live ASAP the same tools will call `wizard_connectors.asap_library.LibraryClient`.

## Library REST client (groundwork, not validated)

`services/connectors/wizard_connectors/asap_library.py`:

- Session via `POST /api/auth/delegate` with an identity token from the approved SSO / trusted-auth route (no passwords in
  Wizard, no copied browser cookies).
- Browse: `GET /api/folders/{id}`; definition: `GET /api/v2/reports/{id}`.
- Rows: `POST /api/v2/reports/{id}/instances` → prompts `GET/PUT /api/reports/{id}/instances/{iid}/prompts[/answers]` →
  paged `GET /api/v2/reports/{id}/instances/{iid}?offset&limit`; `normalise_grid` flattens attribute headers and metric values.
- HTTPS only; no TLS bypass; no `/mstr` event URLs; no write endpoints.

Dossiers need a specific approved **visualization** (chapter/page/viz key) rather than the whole dossier; this is not
implemented until one is approved.

## Parity procedure (first live probe)

1. Owner names one report, its prompt values and the visualization (if a dossier), and runs it in native ASAP as the same
   user; exports the reference result to the approved private location.
2. Wizard reads the same report through `LibraryClient.read_rows` with the same prompt answers.
3. `tests/parity/test_live_parity.py` compares columns, row count and values within the agreed tolerance. It is BLOCKED
   until `WIZARD_PARITY_*` variables point at the tenant, a delegated identity token and the reference file.
4. Owner signs the result; the contract's connector status for that report becomes `ROWS_VERIFIED`; only then can a
   report built on it be labelled LIVE_VERIFIED for those rows.

Open with ASAP IT: supported login route (delegate vs SAML/OIDC), project id, Library base URL, rate limits, whether the
service may hold an identity token per user, folder IDs for the catalog, and prompt answer formats.
