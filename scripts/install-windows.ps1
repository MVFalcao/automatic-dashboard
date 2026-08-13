# User-scoped Windows installer. Administrator rights are not required.
[CmdletBinding()]
param(
    [string]$Source = (Split-Path -Parent $PSScriptRoot),
    [string]$InstallDir = $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "UniversalDashboardAgent" } else { Join-Path $env:USERPROFILE "UniversalDashboardAgent" }),
    [string]$BundleDir,
    [switch]$SkipBrowser,
    [switch]$SkipBuild,
    [switch]$NoCopy
)
$ErrorActionPreference = "Stop"
$installDirExisted = Test-Path -LiteralPath $InstallDir
$backupDir = "$InstallDir.upgrade-backup"
$upgradePrepared = $false
trap {
    if ($upgradePrepared) {
        if (Test-Path -LiteralPath $InstallDir) { Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $backupDir) { Move-Item -LiteralPath $backupDir -Destination $InstallDir -Force }
    } elseif (-not $installDirExisted -and (Test-Path -LiteralPath $InstallDir)) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}

function Fail([string]$Message) { throw $Message }
function Get-CommandPath([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) { Fail "$Name is required. Install it for your user account and run this script again." }
    return $command.Source
}
function Test-MinVersion([string]$Value, [int]$Major, [int]$Minor, [string]$Name) {
    $parsed = [version]($Value.Trim().TrimStart('v'))
    if (($parsed.Major -lt $Major) -or (($parsed.Major -eq $Major) -and ($parsed.Minor -lt $Minor))) {
        Fail "$Name $Major.$Minor or newer is required (found $Value)."
    }
}

if ($BundleDir) {
    $manifest = Join-Path $BundleDir "manifest.sha256"
    if (-not (Test-Path $manifest)) { Fail "Release bundle manifest is missing." }
    foreach ($line in Get-Content $manifest) {
        if (-not $line.Trim()) { continue }
        $parts = $line -split '\s+', 2
        $target = Join-Path $BundleDir $parts[1].Trim().TrimStart('*')
        if (-not (Test-Path $target) -or (Get-FileHash -Algorithm SHA256 $target).Hash.ToLowerInvariant() -ne $parts[0].ToLowerInvariant()) {
            Fail "Release bundle checksum verification failed: $($parts[1])"
        }
    }
    $Source = Join-Path $BundleDir "app"
    $python = Join-Path $BundleDir "runtime\python\python.exe"
    $node = Join-Path $BundleDir "runtime\node\node.exe"
} else {
    $python = Get-CommandPath "python"
    $node = Get-CommandPath "node"
}
$pythonVersion = (& $python --version 2>&1).Trim()
$nodeVersion = (& $node --version 2>&1).Trim()
Test-MinVersion ($pythonVersion -replace "Python ", "") 3 11 "Python"
Test-MinVersion $nodeVersion 24 0 "Node.js"
if (-not (Test-Path (Join-Path $Source "pyproject.toml"))) { Fail "Source directory does not contain pyproject.toml: $Source" }

if ($BundleDir -and $installDirExisted) {
    if (Test-Path -LiteralPath $backupDir) { Fail "A previous upgrade backup exists: $backupDir. Restore or remove it before retrying." }
    Write-Host "Preparing transactional upgrade of $InstallDir..."
    $oldHermes = Join-Path $InstallDir ".hermes-runtime\Scripts\hermes.exe"
    if (Test-Path -LiteralPath $oldHermes) {
        $env:HERMES_HOME = Join-Path $InstallDir ".hermes-data"
        & $oldHermes gateway stop | Out-Null
    }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Move-Item -LiteralPath $InstallDir -Destination $backupDir
    $upgradePrepared = $true
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
if ($upgradePrepared) {
    foreach ($preserved in @(".hermes-data", "config", "projects.json")) {
        $existing = Join-Path $backupDir $preserved
        if (Test-Path -LiteralPath $existing) { Copy-Item -LiteralPath $existing -Destination (Join-Path $InstallDir $preserved) -Recurse -Force }
    }
}
if (-not $NoCopy -and ((Resolve-Path $Source).Path -ne (Resolve-Path $InstallDir).Path)) {
    $excludeDirectories = @(
        ".git",
        ".venv",
        ".hermes-runtime",
        ".playwright",
        "reports",
        "data",
        "dashboard\web\node_modules",
        "dashboard\web\.next"
    ) | ForEach-Object { Join-Path $Source $_ }
    Write-Host "Copying application files to $InstallDir..."
    & robocopy $Source $InstallDir /E /XD $excludeDirectories /XF (Join-Path $Source "private_source_dashboard.xlsx") | Out-Null
    if ($LASTEXITCODE -gt 7) { Fail "Unable to copy application files (robocopy code $LASTEXITCODE)." }
    Write-Host "Application files copied."
}
if ($BundleDir) {
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "runtime") | Out-Null
    Copy-Item -Recurse -Force (Join-Path $BundleDir "runtime\python") (Join-Path $InstallDir "runtime\python")
    Copy-Item -Recurse -Force (Join-Path $BundleDir "runtime\node") (Join-Path $InstallDir "runtime\node")
    $python = Join-Path $InstallDir "runtime\python\python.exe"
    $node = Join-Path $InstallDir "runtime\node\node.exe"
    $env:Path = "$(Join-Path $InstallDir 'runtime\node');$env:Path"
}

$venv = Join-Path $InstallDir ".venv"
$hermes = Join-Path $InstallDir ".hermes-runtime"
$playwright = Join-Path $InstallDir ".playwright"
& $python -m venv $venv
if ($LASTEXITCODE -ne 0) { Fail "Unable to create the application Python environment (exit code $LASTEXITCODE)." }
$venvPython = Join-Path $venv "Scripts\python.exe"
if ($BundleDir) {
    & $venvPython -m pip install --no-index --find-links (Join-Path $BundleDir "wheels") universal-dashboard-agent
    if ($LASTEXITCODE -ne 0) { Fail "Unable to install the offline application wheel (exit code $LASTEXITCODE)." }
} else {
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Fail "Unable to prepare pip (exit code $LASTEXITCODE)." }
    & $venvPython -m pip install --upgrade $InstallDir
    if ($LASTEXITCODE -ne 0) { Fail "Unable to install the application (exit code $LASTEXITCODE)." }
}
if ($BundleDir) {
    Copy-Item -Recurse -Force (Join-Path $BundleDir "runtime\playwright") $playwright
} elseif (-not $SkipBrowser) {
    $env:PLAYWRIGHT_BROWSERS_PATH = $playwright
    & $venvPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { Fail "Unable to install Playwright Chromium (exit code $LASTEXITCODE)." }
}
if ($BundleDir) {
    & $python -m venv $hermes
    if ($LASTEXITCODE -ne 0) { Fail "Unable to create the Hermes environment (exit code $LASTEXITCODE)." }
    $hermesPython = Join-Path $hermes "Scripts\python.exe"
    & $hermesPython -m pip install --no-index --find-links (Join-Path $BundleDir "hermes-wheels") "hermes-agent==0.13.0" "aiohttp==3.13.3"
    if ($LASTEXITCODE -ne 0) { Fail "Unable to install the offline Hermes runtime (exit code $LASTEXITCODE)." }
} else {
    & $python -m venv $hermes
    if ($LASTEXITCODE -ne 0) { Fail "Unable to create the Hermes environment (exit code $LASTEXITCODE)." }
    $hermesPython = Join-Path $hermes "Scripts\python.exe"
    & $hermesPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Fail "Unable to prepare Hermes pip (exit code $LASTEXITCODE)." }
    & $hermesPython -m pip install --upgrade "hermes-agent==0.13.0" "aiohttp==3.13.3"
    if ($LASTEXITCODE -ne 0) { Fail "Unable to install Hermes (exit code $LASTEXITCODE)." }
}
if (-not $BundleDir -and -not $SkipBuild) {
    Push-Location (Join-Path $InstallDir "dashboard\web")
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { Fail "Unable to install frontend dependencies (exit code $LASTEXITCODE)." }
        npm run build
        if ($LASTEXITCODE -ne 0) { Fail "Unable to build the frontend (exit code $LASTEXITCODE)." }
        New-Item -ItemType Directory -Force -Path ".next\standalone\.next\static" | Out-Null
        Copy-Item -Recurse -Force ".next\static\*" ".next\standalone\.next\static"
        if (Test-Path "public") {
            New-Item -ItemType Directory -Force -Path ".next\standalone\public" | Out-Null
            Copy-Item -Recurse -Force "public\*" ".next\standalone\public"
        }
    } finally { Pop-Location }
}

$configDir = Join-Path $InstallDir "config"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$envFile = Join-Path $configDir "local.env"
if (-not (Test-Path $envFile)) {
    @"
# Generated by install-windows.ps1. Keep this file user-readable only.
DASHBOARD_API_HOST=127.0.0.1
DASHBOARD_API_PORT=8000
DASHBOARD_WEB_HOST=127.0.0.1
DASHBOARD_WEB_PORT=3000
DASHBOARD_ALLOWED_ORIGINS=http://127.0.0.1:3000
DASHBOARD_ENFORCE_LOCAL_SECURITY=true
PLAYWRIGHT_BROWSERS_PATH=$playwright
"@ | Set-Content -Encoding UTF8 $envFile
}

$firstRun = Join-Path $InstallDir "dashboard-first-run.ps1"
@"
`$ErrorActionPreference = 'Stop'
`$env:DASHBOARD_ENFORCE_LOCAL_SECURITY = 'true'
`$env:DASHBOARD_LOCAL_AUTH_TOKEN = (& '$venvPython' -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
`$env:PLAYWRIGHT_BROWSERS_PATH = '$playwright'
`$env:PATH = "$(Join-Path $hermes 'Scripts');$(Split-Path $node -Parent);`$env:PATH"
& '$venvPython' -m automation.release.first_run --root '$InstallDir' --runtime '$hermes' --node '$node' --browser-path '$playwright' `$args
"@ | Set-Content -Encoding UTF8 $firstRun
$start = Join-Path $InstallDir "dashboard-start.ps1"
$hermesExecutable = Join-Path $hermes "Scripts\hermes.exe"
@"
`$ErrorActionPreference = 'Stop'
`$env:PLAYWRIGHT_BROWSERS_PATH = '$playwright'
`$env:DASHBOARD_ENFORCE_LOCAL_SECURITY = 'true'
`$env:DASHBOARD_ALLOWED_ORIGINS = 'http://127.0.0.1:3000'
`$env:DASHBOARD_LOCAL_AUTH_TOKEN = (& '$venvPython' -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
`$env:DASHBOARD_HERMES_RUNTIME = '$hermes'
`$env:DASHBOARD_HERMES_HOME = '$InstallDir\.hermes-data'
`$env:DASHBOARD_API_ORIGIN = 'http://127.0.0.1:8000'
if (Test-NetConnection -ComputerName 127.0.0.1 -Port 8000 -InformationLevel Quiet) {
  try { if ((Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/health').StatusCode -eq 200) { Start-Process 'http://127.0.0.1:3000'; exit 0 } } catch { }
}
`$api = Start-Process -FilePath '$venvPython' -ArgumentList '-m','uvicorn','dashboard.api.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory '$InstallDir' -PassThru
try {
  for (`$i = 0; `$i -lt 60; `$i++) { try { if ((Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/health').StatusCode -eq 200) { break } } catch { Start-Sleep -Milliseconds 250 } }
  Push-Location '$InstallDir\dashboard\web'
  `$env:HOSTNAME='127.0.0.1'; `$env:PORT='3000'
  if (Test-Path '.next\standalone\server.js') { `$web = Start-Process -FilePath '$node' -ArgumentList '.next\standalone\server.js' -WorkingDirectory '$InstallDir\dashboard\web' -PassThru -WindowStyle Hidden }
  else { `$web = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','start','--','-H','127.0.0.1','-p','3000' -WorkingDirectory '$InstallDir\dashboard\web' -PassThru -WindowStyle Hidden }
  for (`$i = 0; `$i -lt 60; `$i++) { try { if ((Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:3000').StatusCode -eq 200) { break } } catch { Start-Sleep -Milliseconds 250 } }
  Start-Process 'http://127.0.0.1:3000'
  Wait-Process -Id `$web.Id
} finally {
  Pop-Location
  if (`$web) { Stop-Process -Id `$web.Id -Force -ErrorAction SilentlyContinue }
  Stop-Process -Id `$api.Id -Force -ErrorAction SilentlyContinue
  `$env:HERMES_HOME = '$InstallDir\.hermes-data'
  & '$hermesExecutable' gateway stop | Out-Null
}
"@ | Set-Content -Encoding UTF8 $start

$wasUpgrade = $upgradePrepared
@"
{
  "schema_version": 1,
  "application_version": "0.2.0",
  "upgraded_from_existing_installation": $($wasUpgrade.ToString().ToLowerInvariant())
}
"@ | Set-Content -Encoding UTF8 (Join-Path $InstallDir "application-version.json")

if ($wasUpgrade -and (Test-Path -LiteralPath $backupDir)) {
    $upgradePrepared = $false
    Remove-Item -LiteralPath $backupDir -Recurse -Force
    Write-Host "Upgrade complete. Provider authentication, configuration, and the local project registry were preserved."
}

Write-Host "Installed Universal Dashboard Agent in $InstallDir"
Write-Host "Run first-run diagnostics/provider setup: $firstRun"
Write-Host "Start the loopback-only app: $start"
Write-Host "To uninstall, use scripts/uninstall-windows.ps1 -InstallDir '$InstallDir' -ConfirmUninstall."
