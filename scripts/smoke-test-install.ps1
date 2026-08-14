[CmdletBinding()]
param(
    [string]$InstallDir = $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "UniversalDashboardAgent" } else { Join-Path $env:USERPROFILE "UniversalDashboardAgent" }),
    [int]$Port = 8000,
    [int]$WebPort = 13000
)
$ErrorActionPreference = "Stop"
$python = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Installed Python environment not found: $InstallDir" }
$node = Join-Path $InstallDir "runtime\node\node.exe"
if (-not (Test-Path $node)) { $node = (Get-Command node).Source }
$env:DASHBOARD_ENFORCE_LOCAL_SECURITY = "true"
$env:DASHBOARD_LOCAL_AUTH_TOKEN = (& $python -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
$env:DASHBOARD_HERMES_RUNTIME = Join-Path $InstallDir ".hermes-runtime"
$env:DASHBOARD_HERMES_HOME = Join-Path $InstallDir ".hermes-data"
$env:HERMES_HOME = $env:DASHBOARD_HERMES_HOME
$env:DASHBOARD_ALLOWED_ORIGINS = "http://127.0.0.1:$WebPort"
$env:DASHBOARD_API_ORIGIN = "http://127.0.0.1:$Port"
$webStdout = Join-Path ([IO.Path]::GetTempPath()) "automatic-dashboard-web-$PID.stdout.log"
$webStderr = Join-Path ([IO.Path]::GetTempPath()) "automatic-dashboard-web-$PID.stderr.log"

function Start-Api {
    $process = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','dashboard.api.main:app','--host','127.0.0.1','--port',$Port) -WorkingDirectory $InstallDir -PassThru
    for ($i = 0; $i -lt 60; $i++) {
        try { if ((Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/health").StatusCode -eq 200) { return $process } } catch { Start-Sleep -Milliseconds 250 }
    }
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw "API did not start"
}

& $python -m automation.release.diagnostics --root $InstallDir --runtime $env:DASHBOARD_HERMES_RUNTIME --node $node --browser-path (Join-Path $InstallDir ".playwright")
$api = Start-Api
$web = $null
try {
    try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/hermes/status" | Out-Null; throw "Unauthenticated API request was accepted" } catch { if ($_.Exception.Response.StatusCode.value__ -ne 401) { throw } }
    $headers = @{ Authorization = "Bearer $env:DASHBOARD_LOCAL_AUTH_TOKEN" }
    $status = Invoke-RestMethod -Headers $headers "http://127.0.0.1:$Port/api/hermes/status"
    if ($null -eq $status.ready -or $null -eq $status.gateway_authenticated) { throw "Hermes status is incomplete" }
    $standalone = Join-Path $InstallDir "dashboard\web\.next\standalone\server.js"
    if (Test-Path $standalone) {
        $env:HOSTNAME = "127.0.0.1"; $env:PORT = "$WebPort"
        $web = Start-Process -FilePath $node -ArgumentList "server.js" -WorkingDirectory (Split-Path -Parent $standalone) -RedirectStandardOutput $webStdout -RedirectStandardError $webStderr -PassThru
    } else {
        $web = Start-Process -FilePath "npm" -ArgumentList @('run','start','--','-H','127.0.0.1','-p',$WebPort) -WorkingDirectory (Join-Path $InstallDir "dashboard\web") -RedirectStandardOutput $webStdout -RedirectStandardError $webStderr -PassThru
    }
    $page = $null
    for ($i = 0; $i -lt 120; $i++) {
        if ($web.HasExited) { break }
        try { $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$WebPort"; if ($page.StatusCode -eq 200) { break } } catch { Start-Sleep -Milliseconds 250 }
    }
    if ($null -eq $page -or $page.StatusCode -ne 200) {
        if (Test-Path -LiteralPath $webStdout) { Write-Host "Frontend stdout:"; Get-Content -LiteralPath $webStdout }
        if (Test-Path -LiteralPath $webStderr) { Write-Host "Frontend stderr:"; Get-Content -LiteralPath $webStderr }
        $webExit = if ($web.HasExited) { $web.ExitCode } else { "still running" }
        throw "Browser UI did not load (frontend process: $webExit)"
    }
    Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$WebPort/backend/api/hermes/status" | Out-Null
    Stop-Process -Id $api.Id -Force; $api.WaitForExit(); $api = Start-Api
    Invoke-RestMethod -Headers $headers "http://127.0.0.1:$Port/api/providers" | Out-Null
    Write-Host "PASS: Hermes/API/web loopback, auth, browser proxy, shutdown, and restart checks passed."
} finally {
    if ($web) { Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue }
    if ($api) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
    $hermes = Join-Path $env:DASHBOARD_HERMES_RUNTIME "Scripts\hermes.exe"
    if (Test-Path $hermes) { & $hermes gateway stop | Out-Null }
    Remove-Item -LiteralPath $webStdout, $webStderr -Force -ErrorAction SilentlyContinue
}
