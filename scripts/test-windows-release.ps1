# Shared Windows release acceptance test used locally and by GitHub Actions.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SetupPath,
    [Parameter(Mandatory=$true)][string]$BundleDir,
    [string]$InstallDir,
    [string]$InstallLog,
    [string]$UpgradeLog
)
$ErrorActionPreference = "Stop"

$SetupPath = (Resolve-Path -LiteralPath $SetupPath).Path
$BundleDir = (Resolve-Path -LiteralPath $BundleDir).Path
$testId = [Guid]::NewGuid().ToString("N")
if (-not $InstallDir) { $InstallDir = Join-Path ([IO.Path]::GetTempPath()) "automatic-dashboard-release-test-$testId" }
if (-not $InstallLog) { $InstallLog = Join-Path ([IO.Path]::GetTempPath()) "automatic-dashboard-install-$testId.log" }
if (-not $UpgradeLog) { $UpgradeLog = Join-Path ([IO.Path]::GetTempPath()) "automatic-dashboard-upgrade-$testId.log" }

function Assert-Path([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "$Label is missing: $Path" }
}

function Invoke-Setup([string]$LogPath, [string]$Label) {
    $arguments = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        ('/DIR="{0}"' -f $InstallDir),
        ('/LOG="{0}"' -f $LogPath)
    )
    $process = Start-Process -FilePath $SetupPath -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "$Label failed with exit code $($process.ExitCode). Review $LogPath" }
}

function Invoke-CheckedScript([string]$ScriptPath, [string[]]$Arguments, [string]$Label) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

$manifestPath = Join-Path $BundleDir "manifest.sha256"
$wheel = Get-ChildItem (Join-Path $BundleDir "wheels\universal_dashboard_agent-*.whl") | Select-Object -First 1
$manifestText = $null
$wheelBytes = $null

try {
    Assert-Path $manifestPath "Release bundle manifest"
    if (-not $wheel) { throw "Application wheel is missing from the release bundle" }

    Invoke-Setup $InstallLog "Silent installation"
    foreach ($required in @(
        ".venv\Scripts\python.exe",
        "runtime\node\node.exe",
        "scripts\smoke-test-install.ps1",
        "scripts\uninstall-windows.ps1",
        "application-version.json"
    )) {
        Assert-Path (Join-Path $InstallDir $required) "Installed release file"
    }

    New-Item -ItemType Directory -Force (Join-Path $InstallDir ".hermes-data") | Out-Null
    "synthetic-preserved-auth-state" | Set-Content (Join-Path $InstallDir ".hermes-data\acceptance-marker.txt")
    '{"schema_version":1,"projects":[]}' | Set-Content (Join-Path $InstallDir "projects.json")

    Invoke-Setup $UpgradeLog "Silent upgrade"
    Assert-Path (Join-Path $InstallDir ".hermes-data\acceptance-marker.txt") "Preserved Hermes authentication marker"
    Assert-Path (Join-Path $InstallDir "projects.json") "Preserved local project registry"

    $smokeScript = Join-Path $InstallDir "scripts\smoke-test-install.ps1"
    Invoke-CheckedScript $smokeScript @("-InstallDir", $InstallDir) "Installed application smoke test"

    $wheelBytes = [IO.File]::ReadAllBytes($wheel.FullName)
    $manifestText = [IO.File]::ReadAllText($manifestPath)
    [IO.File]::WriteAllText($wheel.FullName, "synthetic-invalid-wheel")
    $relative = $wheel.FullName.Substring($BundleDir.Length + 1).Replace('\', '/')
    $badHash = (Get-FileHash $wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $matched = $false
    $updated = (Get-Content $manifestPath) | ForEach-Object {
        if ($_ -match "  $([regex]::Escape($relative))$") { $matched = $true; "$badHash  $relative" } else { $_ }
    }
    if (-not $matched) { throw "Application wheel was not found in the release manifest" }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllLines($manifestPath, [string[]]$updated, $utf8)

    $bundleInstaller = Join-Path $BundleDir "scripts\install-windows.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bundleInstaller -BundleDir $BundleDir -InstallDir $InstallDir
    if ($LASTEXITCODE -eq 0) { throw "Synthetic failed upgrade unexpectedly succeeded" }
    Assert-Path (Join-Path $InstallDir ".hermes-data\acceptance-marker.txt") "Hermes state restored after failed upgrade"
    if (Test-Path -LiteralPath "$InstallDir.upgrade-backup") { throw "Failed upgrade left a backup directory behind" }

    [IO.File]::WriteAllBytes($wheel.FullName, $wheelBytes)
    [IO.File]::WriteAllText($manifestPath, $manifestText)
    $wheelBytes = $null
    $manifestText = $null

    $uninstallScript = Join-Path $InstallDir "scripts\uninstall-windows.ps1"
    Invoke-CheckedScript $uninstallScript @("-InstallDir", $InstallDir, "-ConfirmUninstall") "Uninstall smoke test"
    if (Test-Path -LiteralPath $InstallDir) { throw "Uninstall left the test installation behind: $InstallDir" }
    Write-Host "PASS: install, upgrade, loopback smoke test, rollback, and uninstall checks passed."
} finally {
    if ($wheelBytes -and $wheel) { [IO.File]::WriteAllBytes($wheel.FullName, $wheelBytes) }
    if ($manifestText) { [IO.File]::WriteAllText($manifestPath, $manifestText) }
    if (Test-Path -LiteralPath $InstallDir) {
        $cleanupScript = Join-Path $BundleDir "scripts\uninstall-windows.ps1"
        if (Test-Path -LiteralPath $cleanupScript) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cleanupScript -InstallDir $InstallDir -ConfirmUninstall
        }
    }
}
