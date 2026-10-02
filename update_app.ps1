# One update path: stop Wizard if it is running, install the newest main from GitHub, start it again.
#   .\update_app.ps1            update and restart
#   .\update_app.ps1 -NoStart   update only
[CmdletBinding()]
param([string]$InstallDir, [string]$Ref = 'main', [switch]$NoStart)
$ErrorActionPreference = 'Stop'
$here = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
if (-not $InstallDir) { $InstallDir = $here }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)

$pidFile = Join-Path $InstallDir '.wizard.pid'
if (Test-Path -LiteralPath $pidFile) {
    $running = Get-Process -Id ([int](Get-Content -LiteralPath $pidFile -Raw).Trim()) -ErrorAction SilentlyContinue
    if ($running -and $running.Path -like "$InstallDir*") {
        Write-Host 'Stopping the running Wizard...'
        Stop-Process -Id $running.Id -Force
        Start-Sleep -Seconds 2
    }
    Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
}

Write-Host 'Updating Wizard...' -ForegroundColor Cyan
& (Join-Path $here 'setup.ps1') -InstallDir $InstallDir -Ref $Ref
if ($LASTEXITCODE -ne 0) { Write-Host 'Update failed; the previous version is still installed.' -ForegroundColor Red; exit $LASTEXITCODE }
if ($NoStart) { Write-Host 'Updated. Start it with .\start.ps1' -ForegroundColor Green; exit 0 }
Start-Process powershell.exe -ArgumentList "-NoExit -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir 'start.ps1')`""
Write-Host 'Updated and started in a new window.' -ForegroundColor Green
exit 0
