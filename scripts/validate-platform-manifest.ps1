param(
  [string]$Manifest = "platform.yaml"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Manifest)) { throw "Missing $Manifest" }

$text = Get-Content -Raw -LiteralPath $Manifest
$topLevel = @("apiVersion", "app", "deployment_status", "owner", "region", "stage", "tier", "budget_usd_month", "images", "processes", "resources", "secrets", "slo")
foreach ($field in $topLevel) {
  $matches = [regex]::Matches($text, "(?m)^$([regex]::Escape($field)):\s*(.*)$")
  if ($matches.Count -ne 1) { throw "Expected exactly one top-level $field field" }
}

if ($text -notmatch '(?m)^apiVersion:\s*platform/v1\s*$') { throw "Unsupported platform apiVersion" }
if ($text -notmatch '(?m)^deployment_status:\s*planned\s*$') { throw "Unqualified manifest must stay planned" }
$stage = [regex]::Match($text, '(?m)^stage:\s*(\S+)\s*$').Groups[1].Value
$tier = [regex]::Match($text, '(?m)^tier:\s*(\S+)\s*$').Groups[1].Value
if ($stage -notmatch '^[0-4]$' -or $tier -ne "T$stage") { throw "stage and tier must agree and be in the 0-4 ladder" }
if ($text -notmatch '(?m)^budget_usd_month:\s*([1-9][0-9]*)\s*$') { throw "Monthly budget must be a positive integer" }
if ($text -match '(?im)ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY') { throw "Static cloud credentials are forbidden" }

$registry = [regex]::Match($text, '(?m)^capability_registry:\s*(\S+)\s*$').Groups[1].Value
if (-not $registry -or -not (Test-Path -LiteralPath $registry -PathType Leaf)) {
  throw "Capability registry must name an existing file"
}
$processNames = [regex]::Matches($text, '(?m)^\s{2}- name:\s*([^\s#]+)\s*$') | ForEach-Object { $_.Groups[1].Value }
if ($processNames.Count -eq 0 -or @($processNames | Select-Object -Unique).Count -ne $processNames.Count) {
  throw "Process names must be present and unique"
}
$handlers = [regex]::Matches($text, '(?m)^\s+handler:\s*([^\s#]+)\s*$')
foreach ($handler in $handlers) {
  $parts = $handler.Groups[1].Value.Split(':')
  if ($parts.Count -ne 2 -or $parts[0] -notmatch '^northstar_api\.' -or $parts[1] -notmatch '^[A-Za-z_][A-Za-z_0-9]*$') {
    throw "Invalid handler: $($handler.Groups[1].Value)"
  }
  $modulePath = Join-Path 'backend/src' ($parts[0].Replace('.', '/') + '.py')
  if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) { throw "Handler module is missing: $modulePath" }
}

foreach ($requiredFile in @("platform/tiers/t0.yaml", "platform/capabilities/locked.yaml", "CLAUDE.md")) {
  if (-not (Test-Path -LiteralPath $requiredFile)) { throw "Missing platform contract: $requiredFile" }
}

Write-Output "platform manifest: structurally checked; deployment remains planned"
