# Task 00 — Environment report

**Goal:** tell the developer exactly what this PC offers Wizard, so problems can be fixed without guessing.
**Output:** `outbox\00-environment.md` · **Shareable with the developer:** yes, after the redactions below.

## Steps (PowerShell, all read-only)

1. Versions: `$PSVersionTable.PSVersion`, `[Environment]::OSVersion.VersionString`, `node --version`,
   `gemini --version`, and `(Get-Command gemini).Source`.
2. Settings present (report only "set" or "not set", never the value): environment variables `GOOGLE_CLOUD_PROJECT`,
   `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `NODE_EXTRA_CA_CERTS`.
3. Wizard installation check. In this folder:
   ```
   $c = Get-Content current.json -Raw | ConvertFrom-Json
   & $c.python (Join-Path $c.release 'run.py') --home . --check
   ```
   Copy every output line.
4. Is Wizard running? `Invoke-WebRequest http://127.0.0.1:8770/api/v1/ready -UseBasicParsing` → status code and body.
5. Network reachability. For each URL below run
   `try { (Invoke-WebRequest -Uri <url> -Method Head -UseBasicParsing -TimeoutSec 15).StatusCode } catch { if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { $_.Exception.Message } }`
   — any HTTP status number means reachable; a timeout or name error means blocked:
   `https://api.github.com`, `https://accounts.google.com`, `https://oauth2.googleapis.com`,
   `https://codeassist.google.com`, `https://cloudcode-pa.googleapis.com`.
6. Ask the user which Gemini model the Gemini CLI status bar shows for this session, and whether their own Gemini CLI
   sign-in uses "Login with Google" (enterprise).

## Write `outbox\00-environment.md`

A table per step with the results. **Redact before writing:** user names inside paths (`C:\Users\<user>` → `C:\Users\…`),
email addresses, project ids and hostnames other than the five URLs above.

**Done when:** the file exists with all six sections and no unredacted personal data.
