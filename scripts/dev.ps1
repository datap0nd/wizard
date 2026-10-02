# Start Wizard for local development on Windows: API on :8770 (settings from .env) and the Vite dev server on :5173.
#   .\scripts\dev.ps1            # API + hot-reloading web app
#   .\scripts\dev.ps1 -ApiOnly   # API serving the built web app from apps/web/dist
param([switch]$ApiOnly)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host 'Created .env from .env.example (replay mode).' }
uv sync | Out-Null
if (-not (Test-Path apps/web/node_modules)) { npm --prefix apps/web ci --no-audit --no-fund }
if ($ApiOnly) {
  if (-not (Test-Path apps/web/dist/index.html)) { npm --prefix apps/web run build }
  uv run python -m wizard_api
} else {
  $api = Start-Process -PassThru -NoNewWindow uv -ArgumentList 'run', 'python', '-m', 'wizard_api'
  try { npm --prefix apps/web run dev } finally { Stop-Process -Id $api.Id -ErrorAction SilentlyContinue }
}
