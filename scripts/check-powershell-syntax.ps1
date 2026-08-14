[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Path
)
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
if ($errors.Count) {
    $errors | Format-List
    exit 1
}
Write-Host "PowerShell syntax OK: $Path"
