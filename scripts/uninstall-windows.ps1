[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [switch]$ConfirmUninstall
)
$ErrorActionPreference = "Stop"
$target = [IO.Path]::GetFullPath($InstallDir)
$root = [IO.Path]::GetPathRoot($target)
if ($target -eq $root -or $target -eq [IO.Path]::GetFullPath($env:USERPROFILE)) { throw "Refusing unsafe uninstall target: $target" }
if (-not (Test-Path $target)) { Write-Host "Nothing to remove: $target"; exit 0 }
if (-not $ConfirmUninstall) { throw "Pass -ConfirmUninstall after reviewing the exact app directory: $target" }
Remove-Item -LiteralPath $target -Recurse -Force
Write-Host "Removed $target. User project folders outside this directory were not touched."
