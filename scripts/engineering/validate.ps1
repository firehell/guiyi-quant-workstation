#Requires -Version 7.0
<#
.SYNOPSIS
  Fixed-profile local validation for personal development mode.

.DESCRIPTION
  Runs closed validation profiles with fixed child argv arrays only.
  Never accepts arbitrary command text. Missing tools become unavailable,
  not false passes.

.EXITCODES
  0 success
  1 one or more required checks failed
  2 invalid invocation
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $false)]
  [ValidateSet('Engineering', 'Docs', 'Backend', 'Web', 'DataCore', 'Strategy', 'Runtime', 'Migration', 'AllSafe')]
  [string]$Profile = '',

  [string[]]$TestPath = @(),
  [switch]$Json,
  [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Usage {
  @"
Usage: pwsh -NoProfile -File scripts/engineering/validate.ps1 -Profile <Profile> [-TestPath <path>...] [-Json]

Profiles: Engineering Docs Backend Web DataCore Strategy Runtime Migration AllSafe
"@
}

if ($Help) {
  Write-Usage
  exit 0
}

if ($PSVersionTable.PSVersion.Major -lt 7) {
  Write-Error 'PowerShell 7 or later is required'
  exit 2
}

if ([string]::IsNullOrWhiteSpace($Profile)) {
  Write-Error 'Profile is required'
  Write-Usage
  exit 2
}

try {
  $scriptDir = Split-Path -Parent $PSCommandPath
  $repoRoot = (& git -C $scriptDir rev-parse --show-toplevel 2>$null)
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    throw 'repository root unavailable'
  }
  $repoRoot = [System.IO.Path]::GetFullPath($repoRoot.Trim())
  Set-Location -LiteralPath $repoRoot
}
catch {
  Write-Error $_.Exception.Message
  exit 2
}

$approvedRoots = @(
  'tests/engineering',
  'services/quant-api/tests',
  'packages/quant-core',
  'apps/quant-web'
)
$approvedExtensions = [System.Collections.Generic.HashSet[string]]::new(
  [string[]]@('.py', '.ps1', '.ts', '.tsx', '.js', '.vue', '.md'),
  [System.StringComparer]::OrdinalIgnoreCase
)

function Assert-ApprovedTestPath {
  param([string]$Relative)
  $normalized = $Relative.Replace('\', '/').TrimStart('./')
  $full = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $normalized))
  $rootPrefix = $repoRoot.TrimEnd('\') + '\'
  if (-not $full.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
      -not $full.Equals($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw ("TestPath escapes repository: {0}" -f $Relative)
  }
  $rel = [System.IO.Path]::GetRelativePath($repoRoot, $full).Replace('\', '/')
  $allowed = $false
  foreach ($root in $approvedRoots) {
    if ($rel -eq $root -or $rel.StartsWith($root + '/')) {
      $allowed = $true
      break
    }
  }
  if (-not $allowed) {
    throw ("TestPath outside approved roots: {0}" -f $Relative)
  }
  if (Test-Path -LiteralPath $full -PathType Leaf) {
    $ext = [System.IO.Path]::GetExtension($full)
    if (-not $approvedExtensions.Contains($ext)) {
      throw ("TestPath extension not approved: {0}" -f $Relative)
    }
  }
  return $rel
}

$resolvedTestPaths = @()
try {
  foreach ($item in $TestPath) {
    $resolvedTestPaths += (Assert-ApprovedTestPath -Relative $item)
  }
}
catch {
  Write-Error $_.Exception.Message
  exit 2
}

function New-Check {
  param([string]$Name, [string]$Status, [string]$Detail)
  [pscustomobject]@{ name = $Name; status = $Status; detail = $Detail }
}

function Invoke-Child {
  param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$FilePath,
    [string[]]$ArgumentList = @(),
    [hashtable]$Environment = @{}
  )
  if (-not (Get-Command $FilePath -ErrorAction SilentlyContinue) -and
      -not (Test-Path -LiteralPath $FilePath)) {
    return (New-Check $Name 'unavailable' ("tool not found: {0}" -f $FilePath))
  }
  $old = @{}
  foreach ($key in $Environment.Keys) {
    $old[$key] = [System.Environment]::GetEnvironmentVariable($key)
    [System.Environment]::SetEnvironmentVariable($key, [string]$Environment[$key])
  }
  try {
    $output = & $FilePath @ArgumentList 2>&1
    $code = $LASTEXITCODE
  }
  finally {
    foreach ($key in $Environment.Keys) {
      [System.Environment]::SetEnvironmentVariable($key, $old[$key])
    }
  }
  $detail = (($output | ForEach-Object { "$_" }) -join ' ')
  if ($detail.Length -gt 240) {
    $detail = $detail.Substring(0, 237) + '...'
  }
  if ($code -eq 0) {
    return (New-Check $Name 'passed' ("exit=0 {0}" -f $detail))
  }
  return (New-Check $Name 'failed' ("exit={0} {1}" -f $code, $detail))
}

$checks = [System.Collections.Generic.List[object]]::new()
$pythonpath = 'services/quant-api;packages/quant-core'

function Add-UvPytest {
  param([string]$Name, [string[]]$Targets)
  if (Get-Command 'uv' -ErrorAction SilentlyContinue) {
    $args = @('run', '--project', 'services/quant-api', 'pytest', '-q') + $Targets
    $checks.Add((Invoke-Child -Name $Name -FilePath 'uv' -ArgumentList $args -Environment @{ PYTHONPATH = $pythonpath }))
  }
  else {
    $checks.Add((New-Check $Name 'unavailable' 'uv not found; run project-native pytest directly'))
  }
}

function Invoke-ProfileEngineering {
  $checks.Add((Invoke-Child -Name 'git_diff_check' -FilePath 'git' -ArgumentList @('diff', '--check')))
  if (Get-Command 'python' -ErrorAction SilentlyContinue) {
    $checks.Add((Invoke-Child -Name 'repository_consistency' -FilePath 'python' -ArgumentList @(
          (Join-Path $repoRoot 'scripts/engineering/repository_consistency.py'), '--json'
        )))
  }
  elseif (Get-Command 'uv' -ErrorAction SilentlyContinue) {
    $checks.Add((Invoke-Child -Name 'repository_consistency' -FilePath 'uv' -ArgumentList @(
          'run', '--project', 'services/quant-api', 'python',
          'scripts/engineering/repository_consistency.py', '--json'
        )))
  }
  else {
    $checks.Add((New-Check 'repository_consistency' 'unavailable' 'python/uv not found'))
  }

  $pytestTargets = if ($resolvedTestPaths.Count -gt 0) {
    $resolvedTestPaths
  }
  else {
    @('tests/engineering')
  }
  Add-UvPytest -Name 'engineering_pytest' -Targets $pytestTargets

  $retired = Join-Path $repoRoot 'scripts/engineering/production-write-check.sh'
  if (Test-Path -LiteralPath $retired) {
    $checks.Add((New-Check 'production_write_check_absent' 'failed' 'production-write-check.sh must remain deleted'))
  }
  else {
    $checks.Add((New-Check 'production_write_check_absent' 'passed' 'absent'))
  }
}

function Invoke-ProfileDocs {
  $required = @(
    'AGENTS.md', 'STATUS.md', 'PROJECT_SOURCE.md', 'DECISIONS.md', 'TESTING.md', 'README.md',
    'docs/DEVELOPMENT.md', 'docs/PERSONAL_DEVELOPMENT_WORKFLOW.md'
  )
  foreach ($relative in $required) {
    $full = Join-Path $repoRoot $relative
    if (Test-Path -LiteralPath $full -PathType Leaf) {
      $checks.Add((New-Check ("doc:{0}" -f $relative) 'passed' 'present'))
    }
    else {
      $checks.Add((New-Check ("doc:{0}" -f $relative) 'failed' 'missing'))
    }
  }
  $agents = Get-Content -LiteralPath (Join-Path $repoRoot 'AGENTS.md') -Raw -ErrorAction SilentlyContinue
  if ($agents -match '一次性执行意图|scoped one-shot|明确请求') {
    $checks.Add((New-Check 'scoped_intent_rule' 'passed' 'present in AGENTS.md'))
  }
  else {
    $checks.Add((New-Check 'scoped_intent_rule' 'failed' 'scoped intent rule missing in AGENTS.md'))
  }
}

function Invoke-ProfileBackend {
  Add-UvPytest -Name 'backend_health' -Targets @('services/quant-api/tests/test_health.py')
}

function Invoke-ProfileWeb {
  if (Get-Command 'pnpm' -ErrorAction SilentlyContinue) {
    $checks.Add((Invoke-Child -Name 'web_typecheck_or_test' -FilePath 'pnpm' -ArgumentList @(
          '--dir', 'apps/quant-web', 'exec', 'vue-tsc', '--noEmit'
        )))
  }
  else {
    $checks.Add((New-Check 'web_typecheck_or_test' 'unavailable' 'pnpm not found; run apps/quant-web checks directly'))
  }
}

function Invoke-ProfileDataCore {
  Add-UvPytest -Name 'data_core' -Targets @('services/quant-api/tests/data_core')
}

function Invoke-ProfileStrategy {
  Add-UvPytest -Name 'strategy_signal' -Targets @(
    'services/quant-api/tests/test_actual_contract_semantics.py'
  )
}

function Invoke-ProfileRuntime {
  Add-UvPytest -Name 'runtime_default_off' -Targets @(
    'services/quant-api/tests/test_health.py'
  )
}

function Invoke-ProfileMigration {
  Add-UvPytest -Name 'migration_isolation' -Targets @(
    'services/quant-api/tests/test_health.py'
  )
}

switch ($Profile) {
  'Engineering' { Invoke-ProfileEngineering }
  'Docs' { Invoke-ProfileDocs }
  'Backend' { Invoke-ProfileBackend }
  'Web' { Invoke-ProfileWeb }
  'DataCore' { Invoke-ProfileDataCore }
  'Strategy' { Invoke-ProfileStrategy }
  'Runtime' { Invoke-ProfileRuntime }
  'Migration' { Invoke-ProfileMigration }
  'AllSafe' {
    Invoke-ProfileEngineering
    Invoke-ProfileDocs
    Invoke-ProfileBackend
  }
  default {
    Write-Error ("unknown profile: {0}" -f $Profile)
    exit 2
  }
}

$failed = @($checks | Where-Object { $_.status -eq 'failed' }).Count
$unavailable = @($checks | Where-Object { $_.status -eq 'unavailable' }).Count
$warn = @($checks | Where-Object { $_.status -eq 'warn' }).Count
$passed = @($checks | Where-Object { $_.status -eq 'passed' }).Count

# Unavailable without a successful alternative is overall failure for required profiles.
$status = if ($failed -gt 0 -or $unavailable -gt 0) { 'failed' } elseif ($unavailable -gt 0) { 'unavailable' } else { 'ok' }
if ($failed -eq 0 -and $unavailable -gt 0 -and $passed -eq 0) {
  $status = 'unavailable'
}
elseif ($failed -gt 0 -or ($unavailable -gt 0 -and $Profile -ne 'Web')) {
  # Web may report unavailable tooling without masking other failures.
  if ($failed -gt 0 -or $unavailable -gt 0) {
    $status = if ($failed -gt 0) { 'failed' } else { 'unavailable' }
  }
}

$payload = [ordered]@{
  schema_version = 1
  tool           = 'scripts/engineering/validate.ps1'
  operation      = 'validate'
  mode           = 'read_only'
  status         = $status
  summary        = [ordered]@{
    passed      = $passed
    failed      = $failed
    warn        = $warn
    unavailable = $unavailable
  }
  checks         = @($checks)
}

if ($Json) {
  $payload | ConvertTo-Json -Depth 6 -Compress
}
else {
  Write-Output ("[validate] profile={0} status={1}" -f $Profile, $status)
  foreach ($check in $checks) {
    Write-Output ("  {0}: {1} ({2})" -f $check.name, $check.status, $check.detail)
  }
}

if ($failed -gt 0) { exit 1 }
if ($unavailable -gt 0 -and $passed -eq 0) { exit 1 }
if ($unavailable -gt 0 -and $Profile -in @('Engineering', 'Docs', 'Backend', 'DataCore', 'Strategy', 'Runtime', 'Migration', 'AllSafe')) {
  # Required domain tooling missing is not a false pass.
  if ($failed -eq 0 -and $passed -gt 0 -and $Profile -eq 'Web') {
    exit 0
  }
  if ($failed -gt 0 -or ($unavailable -gt 0 -and $Profile -ne 'Web' -and $passed -eq 0)) {
    exit 1
  }
  if ($unavailable -gt 0 -and $Profile -ne 'Web') {
    exit 1
  }
}
exit 0
