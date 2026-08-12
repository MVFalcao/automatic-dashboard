[CmdletBinding()]
param(
    [string]$InstallDir = $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "UniversalDashboardAgent" } else { Join-Path $env:USERPROFILE "UniversalDashboardAgent" }),
    [int]$Port = 18000
)
$ErrorActionPreference = "Stop"
$python = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Installed Python environment not found: $InstallDir" }
& $python -m automation.release.diagnostics --root $InstallDir --runtime (Join-Path $InstallDir ".hermes-runtime") --no-node --no-browser
$process = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','dashboard.api.main:app','--host','127.0.0.1','--port', $Port) -WorkingDirectory $InstallDir -PassThru
try {
    $healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        try { if ((Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/health").StatusCode -eq 200) { $healthy = $true; break } } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $healthy) { throw "API did not respond on 127.0.0.1:$Port" }
    Write-Host "PASS: API health responded on 127.0.0.1:$Port"
} finally { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
