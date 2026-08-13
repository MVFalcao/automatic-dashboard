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
Test-MinVersion $nodeVersion 20 9 "Node.js"
if (-not (Test-Path (Join-Path $Source "pyproject.toml"))) { Fail "Source directory does not contain pyproject.toml: $Source" }

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
if (-not $NoCopy -and ((Resolve-Path $Source).Path -ne (Resolve-Path $InstallDir).Path)) {
    $excludeDirectories = @(".git", ".venv", ".hermes-runtime", ".playwright", "reports", "data") | ForEach-Object { Join-Path $Source $_ }
    & robocopy $Source $InstallDir /E /XD $excludeDirectories /XF (Join-Path $Source "private_source_dashboard.xlsx") | Out-Null
    if ($LASTEXITCODE -gt 7) { Fail "Unable to copy application files (robocopy code $LASTEXITCODE)." }
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
$venvPython = Join-Path $venv "Scripts\python.exe"
if ($BundleDir) {
    & $venvPython -m pip install --no-index --find-links (Join-Path $BundleDir "wheels") universal-dashboard-agent
} else {
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install --upgrade $InstallDir
}
if ($BundleDir) {
    Copy-Item -Recurse -Force (Join-Path $BundleDir "runtime\playwright") $playwright
} elseif (-not $SkipBrowser) {
    $env:PLAYWRIGHT_BROWSERS_PATH = $playwright
    & $venvPython -m playwright install chromium
}
if ($BundleDir) {
    & $python -m venv $hermes
    $hermesPython = Join-Path $hermes "Scripts\python.exe"
    & $hermesPython -m pip install --no-index --find-links (Join-Path $BundleDir "hermes-wheels") "hermes-agent==0.13.0"
} else {
    & $python -m venv $hermes
    $hermesPython = Join-Path $hermes "Scripts\python.exe"
    & $hermesPython -m pip install --upgrade pip
    & $hermesPython -m pip install --upgrade "hermes-agent==0.13.0"
}
if (-not $BundleDir -and -not $SkipBuild) {
    Push-Location (Join-Path $InstallDir "dashboard\web")
    try {
        npm ci
        npm run build
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
@"
`$ErrorActionPreference = 'Stop'
`$env:PLAYWRIGHT_BROWSERS_PATH = '$playwright'
`$env:DASHBOARD_ENFORCE_LOCAL_SECURITY = 'true'
`$env:DASHBOARD_ALLOWED_ORIGINS = 'http://127.0.0.1:3000'
`$env:DASHBOARD_LOCAL_AUTH_TOKEN = (& '$venvPython' -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
`$env:DASHBOARD_HERMES_RUNTIME = '$hermes'
`$env:DASHBOARD_API_ORIGIN = 'http://127.0.0.1:8000'
`$api = Start-Process -FilePath '$venvPython' -ArgumentList '-m','uvicorn','dashboard.api.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory '$InstallDir' -PassThru
try {
  Push-Location '$InstallDir\dashboard\web'
  if (Test-Path '.next\standalone\server.js') { `$env:HOSTNAME='127.0.0.1'; `$env:PORT='3000'; & '$node' '.next\standalone\server.js' }
  else { npm run start -- -H 127.0.0.1 -p 3000 }
} finally { Pop-Location; Stop-Process -Id `$api.Id -Force -ErrorAction SilentlyContinue }
"@ | Set-Content -Encoding UTF8 $start

Write-Host "Installed Universal Dashboard Agent in $InstallDir"
Write-Host "Run first-run diagnostics/provider setup: $firstRun"
Write-Host "Start the loopback-only app: $start"
Write-Host "To uninstall, use scripts/uninstall-windows.ps1 -InstallDir '$InstallDir' -ConfirmUninstall."
