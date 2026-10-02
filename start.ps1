# Start Wizard in this console window and open it in the browser. Close the window or press Ctrl+C to stop.
#   .\start.ps1              start (or, if it is already running, just open the browser)
#   .\start.ps1 -NoBrowser   start without opening the browser
[CmdletBinding()]
param([string]$InstallDir, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
if (-not $InstallDir) { $InstallDir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path } }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)

$port = 8770
$envPath = Join-Path $InstallDir '.env'
if (Test-Path -LiteralPath $envPath) {
    foreach ($line in [IO.File]::ReadAllLines($envPath)) { if ($line.Trim() -match '^WIZARD_PORT\s*=\s*([0-9]+)') { $port = [int]$Matches[1] } }
}
$url = "http://127.0.0.1:$port"

function Test-Wizard { try { (Invoke-WebRequest -Uri "$url/api/v1/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false } }

if (Test-Wizard) {
    Write-Host "Wizard is already running: $url" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}

$pointer = Join-Path $InstallDir 'current.json'
if (Test-Path -LiteralPath $pointer) {
    $current = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
    $python = $current.python; $run = Join-Path $current.release 'run.py'; $home_ = $InstallDir
} elseif (Test-Path -LiteralPath (Join-Path $InstallDir 'run.py')) {
    $python = 'python'; $run = Join-Path $InstallDir 'run.py'; $home_ = $null   # development checkout
} else {
    throw "No installed release in $InstallDir. Run .\setup.ps1 first."
}
if (-not (Test-Path -LiteralPath $run)) { throw "The selected release is missing ($run). Run .\setup.ps1 again." }

$arguments = @("`"$run`"")
if ($home_) { $arguments += @('--home', "`"$home_`"") }
Write-Host "Starting Wizard on $url (this window shows its log; close it or press Ctrl+C to stop)" -ForegroundColor Cyan
$process = Start-Process -FilePath $python -ArgumentList ($arguments -join ' ') -NoNewWindow -PassThru
Set-Content -LiteralPath (Join-Path $InstallDir '.wizard.pid') -Value $process.Id
try {
    $ready = $false
    for ($i = 0; $i -lt 60 -and -not $process.HasExited; $i++) { if (Test-Wizard) { $ready = $true; break }; Start-Sleep -Milliseconds 500 }
    if ($ready) {
        Write-Host "Wizard is ready: $url" -ForegroundColor Green
        if (-not $NoBrowser) { Start-Process $url }
    } elseif ($process.HasExited) {
        throw "Wizard stopped during start-up (exit $($process.ExitCode)). Read the messages above; run .\setup.ps1 to re-check the installation."
    }
    $process.WaitForExit()
} finally {
    Remove-Item -LiteralPath (Join-Path $InstallDir '.wizard.pid') -ErrorAction SilentlyContinue
}
exit $process.ExitCode
