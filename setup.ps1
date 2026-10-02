# Install or refresh Wizard in this folder from GitHub. No admin rights, git, pip or Node build needed.
# Only this file is needed on a work PC: save it as setup.ps1 in an empty folder (e.g. C:\Wizard) and run .\setup.ps1.
# GitHub token: the DG_GITHUB_TOKEN environment variable, or a DG_GITHUB_TOKEN=<token> line in .env in the same folder.
# Downloads the exact commit of `main`, a portable Python and locked libraries (SHA-256 verified) from this repository's
# GitHub release, installs a clean release under releases\, keeps .env, data\, content\ and outbox\, refreshes the
# Gemini CLI task folder, and checks the installation. Same model as the B2B installer.
#
#   .\setup.ps1                 first install or refresh (uses DG_GITHUB_TOKEN from the environment or .env)
#   .\update_app.ps1            stop Wizard, refresh, start again (the normal way to update)
[CmdletBinding()]
param(
    [string]$InstallDir,
    [string]$Repository = 'datap0nd/wizard',
    [string]$Ref = 'main',
    [string]$LocalSource,
    [ValidatePattern('^(local|[a-f0-9]{40})$')][string]$SourceCommit = 'local',
    [string]$DownloadCache,
    [switch]$SkipCheck
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Read-EnvFile([string]$Path) {
    $values = @{}
    if (Test-Path -LiteralPath $Path) {
        foreach ($raw in [IO.File]::ReadAllLines($Path)) {
            $line = $raw.Trim()
            if (-not $line -or $line.StartsWith('#')) { continue }
            if ($line -notmatch '^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { throw "Invalid line in .env: '$line'. Use KEY=value lines." }
            $key = $Matches[1]; $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) { $value = $value.Substring(1, $value.Length - 2) }
            $values[$key] = $value
        }
    }
    return $values
}
function Setting([string]$Key, [hashtable]$Values) {
    if (Test-Path -LiteralPath "Env:$Key") { return [Environment]::GetEnvironmentVariable($Key) }
    return $Values[$Key]
}

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
$bootstrap = Read-EnvFile (Join-Path $scriptRoot '.env')
if (-not $InstallDir) { $InstallDir = Setting 'WIZARD_INSTALL_ROOT' $bootstrap }
if (-not $InstallDir) { $InstallDir = $scriptRoot }
if (-not [IO.Path]::IsPathRooted($InstallDir)) { $InstallDir = Join-Path $scriptRoot $InstallDir }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$envPath = Join-Path $InstallDir '.env'
$localValues = Read-EnvFile $envPath
# Same GitHub token the data-governance and B2B installers use (Contents: read on datap0nd/wizard).
$githubToken = Setting 'DG_GITHUB_TOKEN' $localValues
foreach ($alias in @('WIZARD_GITHUB_TOKEN', 'PAT_CODE')) { if (-not $githubToken) { $githubToken = Setting $alias $localValues } }
$githubHeaders = @{ 'User-Agent' = 'Wizard-Setup'; 'Accept' = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
if ($githubToken) { $githubHeaders['Authorization'] = "Bearer $githubToken" }
if (-not $DownloadCache) { $DownloadCache = Join-Path $InstallDir '.downloads' }
$DownloadCache = [IO.Path]::GetFullPath($DownloadCache)
New-Item -ItemType Directory -Force -Path $DownloadCache | Out-Null
$script:releaseAssets = $null
$script:downloads = 0
$script:reused = 0
$setupLock = $null

function Download-File([string]$Url, [string]$Path, [hashtable]$Headers) {
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Path -Headers $Headers -UseBasicParsing -TimeoutSec 300
            return
        } catch {
            if ($attempt -eq 8) { throw "GitHub download failed after 8 attempts ($($_.Exception.Message)). Check the corporate proxy and DG_GITHUB_TOKEN." }
            $wait = [Math]::Min(30, $attempt * 3)
            Write-Host "  Download attempt $attempt failed: $($_.Exception.Message). Retrying in $wait seconds."
            Start-Sleep -Seconds $wait
        }
    }
}
function Expand-CheckedArchive([string]$Archive, [string]$Target) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $prefix = [IO.Path]::GetFullPath($Target).TrimEnd('\') + '\'
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $resolved = [IO.Path]::GetFullPath((Join-Path $Target $entry.FullName))
            if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid path in downloaded archive.' }
        }
    } finally { $zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Target)
}
function Get-LockedArchive($Item, [string]$Tag) {
    if ([IO.Path]::GetFileName($Item.filename) -ne $Item.filename -or $Item.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Invalid archive lock entry.' }
    $archivePath = Join-Path $DownloadCache $Item.filename
    if ((Test-Path -LiteralPath $archivePath) -and (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -eq $Item.sha256) {
        $script:reused++
        return $archivePath
    }
    if (-not $script:releaseAssets) {
        for ($attempt = 1; $attempt -le 4 -and -not $script:releaseAssets; $attempt++) {
            try { $script:releaseAssets = (Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/tags/$Tag" -Headers $githubHeaders -TimeoutSec 60).assets }
            catch {
                if ($attempt -eq 4) { throw "The portable runtime release '$Tag' is unavailable ($($_.Exception.Message)). Check the proxy and DG_GITHUB_TOKEN." }
                Start-Sleep -Seconds ($attempt * 3)
            }
        }
    }
    $asset = @($script:releaseAssets | Where-Object { $_.name -ceq $Item.filename -and $_.state -eq 'uploaded' })
    if ($asset.Count -ne 1) { throw "The portable runtime release is missing $($Item.filename)." }
    Write-Host "Downloading $($Item.filename)"
    $binaryHeaders = $githubHeaders.Clone(); $binaryHeaders['Accept'] = 'application/octet-stream'
    Download-File "https://api.github.com/repos/$Repository/releases/assets/$($asset[0].id)" $archivePath $binaryHeaders
    if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne $Item.sha256) { throw "Checksum mismatch for $($Item.filename)." }
    $script:downloads++
    return $archivePath
}
function Copy-Tree([string]$From, [string]$To) {
    # robocopy skips developer-only folders; exit codes below 8 mean success.
    & robocopy $From $To /E /NFL /NDL /NJH /NJS /NP /XD .git .github .tools .venv var artifacts node_modules __pycache__ .pytest_cache .mypy_cache .ruff_cache .claude /XF .env | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying $From failed (robocopy $LASTEXITCODE)." }
    $global:LASTEXITCODE = 0
}
function Set-EnvDefault([string]$Key, [string]$Value, [string]$Comment) {
    if (-not $Value) { return }
    $current = Read-EnvFile $envPath
    if ($current.ContainsKey($Key)) { return }
    $text = ''
    if (Test-Path -LiteralPath $envPath) { $text = [IO.File]::ReadAllText($envPath); if ($text -and -not $text.EndsWith("`n")) { $text += "`r`n" } }
    if ($Comment) { $text += "# $Comment`r`n" }
    $text += "$Key=$Value`r`n"
    [IO.File]::WriteAllText($envPath, $text, $utf8)
    Write-Host "  .env: $Key=$Value"
}

try {
    if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Repository must use owner/name format.' }
    $setupLock = [IO.File]::Open((Join-Path $InstallDir '.setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $installId = [guid]::NewGuid().ToString('N').Substring(0, 8)
    if ($LocalSource) {
        $source = [IO.Path]::GetFullPath($LocalSource)
        $commit = $SourceCommit
    } else {
        $encodedRef = [uri]::EscapeDataString($Ref)
        $commit = $null
        for ($attempt = 1; $attempt -le 4 -and -not $commit; $attempt++) {
            try { $commit = (Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/commits/${encodedRef}?cache=$installId$attempt" -Headers $githubHeaders -TimeoutSec 60).sha }
            catch {
                $lookupError = $_
                $code = 0; try { $code = [int]$_.Exception.Response.StatusCode } catch { }
                if ($code -in 401, 404 -or $attempt -eq 4) { break }
                Write-Host "GitHub lookup attempt $attempt failed ($($_.Exception.Message)); retrying."
                Start-Sleep -Seconds ($attempt * 3)
            }
        }
        if (-not $commit) {
            $status = ''; try { $status = [int]$lookupError.Exception.Response.StatusCode } catch { }
            $tokenState = if (-not $githubToken) { "No DG_GITHUB_TOKEN was found. Set it as an environment variable, or put the line DG_GITHUB_TOKEN=<token> in $envPath, then run setup.ps1 again." } else { "A token was found ($($githubToken.Length) characters)." }
            $hint = switch ($status) {
                401 { 'The token is invalid or expired.' }
                404 { "The token cannot see $Repository. Add this repository to the token (fine-grained: Contents read-only), or use a token with the repo scope." }
                403 { 'The token was refused: check SSO authorization and rate limits.' }
                default { 'api.github.com is unreachable: check the proxy, TLS inspection and firewall.' }
            }
            throw "Cannot read $Ref of $Repository (HTTP $status). $tokenState $hint"
        }
        Write-Host "Installing Wizard $($commit.Substring(0, 12)) from $Repository"
        $archive = Join-Path $DownloadCache "source-$installId.zip"
        Download-File "https://api.github.com/repos/$Repository/zipball/$commit" $archive $githubHeaders
        $extracted = Join-Path $DownloadCache "source-$installId"
        Expand-CheckedArchive $archive $extracted
        Remove-Item -LiteralPath $archive -Force
        $folders = @(Get-ChildItem -LiteralPath $extracted -Directory)
        if ($folders.Count -ne 1) { throw 'Unexpected repository archive layout.' }
        $source = $folders[0].FullName
        # Installer fixes in the new revision apply to this same update.
        $freshSetup = Join-Path $source 'setup.ps1'
        if ($PSCommandPath -and (Get-FileHash -LiteralPath $freshSetup).Hash -ne (Get-FileHash -LiteralPath $PSCommandPath).Hash) {
            $setupLock.Dispose(); $setupLock = $null
            Write-Host 'Continuing with the newly downloaded setup.ps1.'
            $fresh = @{ InstallDir = $InstallDir; Repository = $Repository; LocalSource = $source; SourceCommit = $commit; DownloadCache = $DownloadCache }
            if ($SkipCheck) { $fresh.SkipCheck = $true }
            & $freshSetup @fresh
            exit $LASTEXITCODE
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'run.py'))) { throw "$source is not a Wizard source folder (run.py missing)." }

    $short = if ($commit -match '^[a-f0-9]{40}$') { $commit.Substring(0, 12) } else { 'local' }
    $release = Join-Path $InstallDir "releases\$short-$installId"
    Copy-Tree $source $release
    if ($extracted) { Remove-Item -LiteralPath $extracted -Recurse -Force -ErrorAction SilentlyContinue }

    # Portable Python and libraries, verified against the release's own locks.
    $runtime = Get-Content -LiteralPath (Join-Path $release 'runtime.lock.json') -Raw | ConvertFrom-Json
    $dependencies = Get-Content -LiteralPath (Join-Path $release 'dependencies.lock.json') -Raw | ConvertFrom-Json
    $assets = Get-Content -LiteralPath (Join-Path $release 'portable_assets.lock.json') -Raw | ConvertFrom-Json
    if ($assets.release_tag -notmatch '^portable-[A-Za-z0-9_.-]+$' -or $assets.format -ne 1) { throw 'Invalid portable_assets.lock.json.' }
    if ((Get-FileHash -LiteralPath (Join-Path $release 'runtime.lock.json')).Hash -ne $assets.runtime_lock_sha256 -or
        (Get-FileHash -LiteralPath (Join-Path $release 'dependencies.lock.json')).Hash -ne $assets.dependency_lock_sha256) { throw 'Runtime locks do not match the portable release.' }
    $pythonZip = Get-LockedArchive $runtime $assets.release_tag
    $runtimeDir = Join-Path $InstallDir "runtime\python-$($runtime.version)-amd64"
    $python = Join-Path $runtimeDir 'python.exe'
    $ready = Join-Path $runtimeDir '.ready'
    $runtimeValid = (Test-Path -LiteralPath $ready) -and (Test-Path -LiteralPath $python) -and ((Get-Content -LiteralPath $ready -Raw).Trim() -eq $runtime.sha256)
    if ($runtimeValid) { & $python -c 'import sqlite3, ssl, ctypes' 2>$null; $runtimeValid = $LASTEXITCODE -eq 0 }
    if (-not $runtimeValid) {
        if (Test-Path -LiteralPath $runtimeDir) { $runtimeDir = "$runtimeDir-$installId"; $python = Join-Path $runtimeDir 'python.exe' }
        Expand-CheckedArchive $pythonZip $runtimeDir
        & $python -c 'import sqlite3, ssl, ctypes; print(''Portable Python ready'')'
        if ($LASTEXITCODE -ne 0) { throw 'Portable Python could not start on this PC.' }
        Set-Content -LiteralPath (Join-Path $runtimeDir '.ready') -Value $runtime.sha256
    } else { Write-Host 'Reusing portable Python.' }
    foreach ($package in $dependencies.packages) { $null = Get-LockedArchive $package $assets.release_tag }
    Write-Host "Archives: $script:reused reused, $script:downloads downloaded."
    & $python (Join-Path $release 'scripts\vendor_dependencies.py') --cache $DownloadCache --store (Join-Path $InstallDir 'dependencies') --target (Join-Path $release 'vendor') --lock (Join-Path $release 'dependencies.lock.json')
    if ($LASTEXITCODE -ne 0) { throw 'Library installation failed.' }

    # First-run settings: only missing keys are added; your values are never changed.
    if (-not (Test-Path -LiteralPath $envPath)) {
        [IO.File]::WriteAllText($envPath, "# Wizard settings for this PC. See .env.example in the release for every option.`r`n", $utf8)
    }
    Set-EnvDefault 'WIZARD_AGENT_RUNTIME' 'gemini-cli' 'Gemini runtime: gemini-cli (your Gemini CLI), code-assist, or replay (recorded demo answers)'
    Set-EnvDefault 'WIZARD_GEMINI_MODEL' 'gemini-3.8-flash' ''
    Set-EnvDefault 'WIZARD_DATA_DIR' 'data' 'Database and per-user Gemini state (kept across updates)'
    $upn = ''; try { $upn = (& whoami /upn 2>$null | Out-String).Trim() } catch { }
    if ($upn -notmatch '@') { $upn = '' }
    Set-EnvDefault 'WIZARD_LOCAL_USER_EMAIL' $upn 'Your work email: must match the Google account you link to Gemini'
    Set-EnvDefault 'WIZARD_LOCAL_USER_NAME' $env:USERNAME ''
    $gemini = Get-Command gemini.cmd -ErrorAction SilentlyContinue
    if (-not $gemini) { $gemini = Get-Command gemini -ErrorAction SilentlyContinue }
    if ($gemini) {
        $bundle = Join-Path (Split-Path -Parent $gemini.Source) 'node_modules\@google\gemini-cli\bundle\gemini.js'
        if (Test-Path -LiteralPath $bundle) { Set-EnvDefault 'WIZARD_GEMINI_CLI_JS' $bundle 'Gemini CLI found by setup' }
    }
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($node) { Set-EnvDefault 'WIZARD_NODE' $node.Source '' }
    if ($env:GOOGLE_CLOUD_PROJECT) { Set-EnvDefault 'GOOGLE_CLOUD_PROJECT' $env:GOOGLE_CLOUD_PROJECT 'Enterprise Gemini project (from your environment)' }

    # Folders you own (never overwritten) and Gemini CLI task files (refreshed every update).
    foreach ($folder in @('outbox', 'data')) { New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir $folder) | Out-Null }
    $content = Join-Path $InstallDir 'content'
    if (-not (Test-Path -LiteralPath $content)) {
        Copy-Tree (Join-Path $release 'templates\content') $content
        Write-Host 'Created content\ from the documentation template (put platform documents in content\inbox\<platform>\).'
    }
    $tasks = Join-Path $InstallDir 'tasks'
    if (Test-Path -LiteralPath $tasks) { Remove-Item -LiteralPath $tasks -Recurse -Force }
    Copy-Tree (Join-Path $release 'workpc\tasks') $tasks
    Copy-Item -LiteralPath (Join-Path $release 'workpc\GEMINI.md') -Destination (Join-Path $InstallDir 'GEMINI.md') -Force
    Copy-Item -LiteralPath (Join-Path $release 'workpc\.geminiignore') -Destination (Join-Path $InstallDir '.geminiignore') -Force
    $commands = Join-Path $InstallDir '.gemini\commands\wizard'
    New-Item -ItemType Directory -Force -Path $commands | Out-Null
    Copy-Item -Path (Join-Path $release 'workpc\.gemini\commands\wizard\*.toml') -Destination $commands -Force

    # Check before selecting the release: a release that cannot start never replaces a working one.
    $checkCode = 0
    if (-not $SkipCheck) {
        Write-Host ''
        & $python (Join-Path $release 'run.py') --home $InstallDir --check
        $checkCode = $LASTEXITCODE
        if ($checkCode -ge 2) { throw "The new release failed its check (above); the previous release is still selected. Fix the named setting in $envPath and run setup.ps1 again." }
    }
    $pointer = @{ release = $release; python = $python; commit = $commit; installed_at = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json
    $pending = Join-Path $InstallDir "current-$installId.json"
    [IO.File]::WriteAllText($pending, $pointer, $utf8)
    $current = Join-Path $InstallDir 'current.json'
    if (Test-Path -LiteralPath $current) { [IO.File]::Replace($pending, $current, (Join-Path $InstallDir 'previous.json')) } else { [IO.File]::Move($pending, $current) }
    foreach ($name in @('setup.ps1', 'start.ps1', 'update_app.ps1')) { Copy-Item -LiteralPath (Join-Path $release $name) -Destination (Join-Path $InstallDir $name) -Force }

    # Keep the three newest releases (the selected and previous ones are always kept).
    $keep = @($release)
    $previous = Join-Path $InstallDir 'previous.json'
    if (Test-Path -LiteralPath $previous) { $keep += (Get-Content -LiteralPath $previous -Raw | ConvertFrom-Json).release }
    $old = @(Get-ChildItem -LiteralPath (Join-Path $InstallDir 'releases') -Directory | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3)
    foreach ($dir in $old) { if ($keep -notcontains $dir.FullName) { Remove-Item -LiteralPath $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue } }

    Write-Host ''
    Write-Host "Wizard is installed in $InstallDir" -ForegroundColor Green
    Write-Host "Active release: $release"
    if ($checkCode -eq 1) { Write-Host 'Gemini CLI is not ready yet (see the check above). Replay mode works: set WIZARD_AGENT_RUNTIME=replay in .env to demo without Gemini.' -ForegroundColor Yellow }
    Write-Host 'Next: .\start.ps1   (Gemini CLI tasks: run gemini in this folder, trust the folder, then /wizard:tasks)'
} catch {
    Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($setupLock) { $setupLock.Dispose() }
}
exit 0
