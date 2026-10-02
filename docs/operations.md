# Operations runbook (Step 15) — skeleton

To be completed and rehearsed with the named operations owner on the pilot host. Items marked TODO are not done.

## Health

- Liveness: `GET /api/v1/health`. Readiness: `GET /api/v1/ready` (store, catalog, runtime label, secret store,
  frontend built).
- TODO: metrics (runs started/failed by code, p50/p95 time to first event and to finish, tool errors by system, model
  429s), alerts, cost/usage caps.

## Common situations

| Symptom | Likely cause | Action |
|---|---|---|
| User sees "Link your own Gemini account" | No per-user sign-in | User links via Account; never copy another user's credentials |
| Runs fail with `model_unreachable` | Proxy/TLS/DNS to Google | Check `HTTPS_PROXY`, `NODE_EXTRA_CA_CERTS`, firewall to `*.googleapis.com` |
| Runs fail with `model_capacity` | Quota or capacity | Retry later; check entitlement/quota in the Google admin console |
| A source tool returns `source_unavailable` | Source outage or schema change | Check the adapter log; the answer discloses the gap; open a source-owner ticket |
| Wrong number reported | Data, definition or model error | Ask the user for the report link; open evidence; Check my data; record in the eval log; escalate to source owner if rows differ from the source |
| Stale data | Source refresh failed | Compare evidence as-of with the source schedule; notify the owner |
| Faulty connector | Bad adapter release | Remove the report/system from `contracts/sources/` (or set status `BLOCKED`) and restart; Gemini can no longer see it |

## Backup, restore, rollback

- TODO: nightly backup of the data dir; restore rehearsal witnessed by IT.
- Rollback: redeploy the previous tagged release; SQLite schema uses `PRAGMA user_version`; a newer database refuses to
  start on an older release (no silent downgrade).

## Retention

Reports expire after `WIZARD_REPORT_RETENTION_DAYS` (default 30) and return 410. TODO: scheduled purge job and
delete/restore workflow approval.

## Escalation

TODO: named on-call owner, source owners per system, security contact.
