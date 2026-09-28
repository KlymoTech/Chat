[CmdletBinding()]
param(
    [switch]$FailOnViolation
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot

$rules = @(
    @{ Root = 'frontend/src'; Extensions = @('.ts', '.tsx'); Limit = 250; Area = 'frontend' },
    @{ Root = 'backend/src/northstar_api'; Extensions = @('.py'); Limit = 300; Area = 'backend' }
)

$excludedName = '(\.test|\.spec)\.'
$violations = @()

foreach ($rule in $rules) {
    $path = Join-Path $repositoryRoot $rule.Root
    $files = Get-ChildItem -LiteralPath $path -Recurse -File | Where-Object {
        $_.Extension -in $rule.Extensions -and $_.Name -notmatch $excludedName -and $_.FullName -notmatch '__pycache__'
    }

    foreach ($file in $files) {
        $lines = (Get-Content -LiteralPath $file.FullName).Count
        if ($lines -gt $rule.Limit) {
            $violations += [PSCustomObject]@{
                Area = $rule.Area
                Lines = $lines
                Limit = $rule.Limit
                File = $file.FullName.Substring($repositoryRoot.Length + 1).Replace('\', '/')
            }
        }
    }
}

if ($violations.Count -eq 0) {
    Write-Host 'Maintainability audit passed.'
    exit 0
}

$violations | Sort-Object Area, @{ Expression = 'Lines'; Descending = $true } | Format-Table -AutoSize
Write-Host ("{0} production files exceed their size limit. See docs/maintainability-architecture.md." -f $violations.Count)

if ($FailOnViolation) {
    exit 1
}
