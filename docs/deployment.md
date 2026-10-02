# Deployment (Steps 02 and 15) — draft

Nothing is deployed for executives yet. This page records the intended shape so the same build can run on the BI
desktop pilot and move to a managed host.

## Pilot on the BI desktop (requires IT confirmation)

| Item | Intended setting | Status |
|---|---|---|
| Process | `python -m wizard_api` as a Windows service under a dedicated service account (NSSM, as B2B/Metronome) | OPEN |
| Inbound | HTTPS via the corporate reverse proxy that performs SSO and sets `X-Forwarded-Email`; Wizard bound to 127.0.0.1 | OPEN |
| Identity | `WIZARD_AUTH_MODE=trusted-header`, `WIZARD_TRUSTED_PROXIES=<proxy IP>`, `WIZARD_PUBLIC_ORIGIN=https://…`, `WIZARD_SECURE_COOKIES=true` | OPEN |
| Gemini | Node 20+, `@google/gemini-cli@0.62.0` pinned; `WIZARD_AGENT_RUNTIME` chosen by the Step 02 spike; `GOOGLE_CLOUD_PROJECT` | OPEN |
| Proxy/TLS | `HTTPS_PROXY`, `NO_PROXY`, `NODE_EXTRA_CA_CERTS` for corporate TLS inspection | OPEN |
| Content | `WIZARD_CONTENT_DIR` = checkout of the internal wizard-content repo, validated with `scripts/validate_content.py` | Implemented; content OPEN |
| Data dir | `WIZARD_DATA_DIR` outside the install, ACL'd to the service account; contains SQLite, per-user homes, DPAPI secrets | OPEN |
| Secrets | DPAPI (machine-bound to the service account) until IT names a secret store | OPEN |
| Lock/reboot | Service restarts on boot; in-flight runs are marked interrupted on restart | Implemented in app |
| Backups | Nightly copy of `WIZARD_DATA_DIR` excluding `users/*/gemini/tmp`; restore rehearsal | OPEN |

## Build

```powershell
uv sync --frozen
npm --prefix apps/web ci
npm --prefix apps/web run build      # API serves apps/web/dist
uv run python scripts/verify_spec.py
```

Release manifest (Step 15): code SHA, `uv.lock` and `package-lock.json` hashes, Gemini CLI version, model id, prompt hash
(`prompts/system.md`), source contract versions, fiscal/FX rule, host config summary, verify_all output, sign-offs.

## Managed host (Step 15/D)

Same build in a container or service with the approved database (SQLite is a development default, not a production
choice), the approved secret store, and per-user Gemini state on encrypted persistent storage. Move when the desktop
cannot meet service targets.
