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
| Runs fail with `model_capacity` | Google had no capacity for either model (not the user's quota) through 10 rounds (about 4 minutes), or kept rate-limiting | Flash and the fallback (`WIZARD_GEMINI_FALLBACK_MODEL`, default `gemini-3.1-pro-preview`) take over from each other after two quick tries, as in Gemini CLI; only when both refuse does Wizard wait, then fails. Retry later. `wizard.log` (`wizard.gemini`) has Google's reason and each step's prompt size |
| Answers are slow, with "Gemini is busy" before most steps | Both models refusing at once, or a conversation so large that every step reaches a per-minute limit | `wizard.log`: `Gemini refused` lines give Google's reason, `run … step N` lines the prompt tokens per step |
| A query fails with `relation … does not exist` | A dataset note names a view that was renamed, or that lives in another database | The tool's error lists readable relations with a similar name and the databases that have the exact one; fix the note in the knowledge base |
| Runs fail with `model_quota` | The user's quota for that model is used up (often daily) | Another model, or wait for Google's reset; check entitlement/quota in the Google admin console |
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
