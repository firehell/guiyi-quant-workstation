#Requires -Version 7.0
<#
.SYNOPSIS
  Read-only personal-development preflight for Windows / PowerShell 7.

.DESCRIPTION
  Checks Git/PowerShell versions, repository root, branch, dirty path summary
  (paths only), and tool availability. develop is an allowed daily branch.
  Never prints environment values or credentials.

.EXITCODES
  0 success
  1 check failure
  2 invalid invocation
#>
[CmdletBinding()]
param(
  [switch]$Json,
  [switch]$RequireClean,
  [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Usage {
  @"
Usage: pwsh -NoProfile -File scripts/engineering/preflight.ps1 [-Json] [-RequireClean]

Read-only checks. develop is allowed. Dirty paths warn by default.
-RequireClean fails when the worktree is dirty (release/tag use).
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

function New-Check {
  param(
    [string]$Name,
    [ValidateSet('passed', 'failed', 'warn', 'unavailable')][string]$Status,
    [string]$Detail
  )
  [pscustomobject]@{
    name   = $Name
    status = $Status
    detail = $Detail
  }
}

function Invoke-Fixed {
  param(
    [Parameter(Mandatory)][string]$FilePath,
    [string[]]$ArgumentList = @()
  )
  $output = & $FilePath @ArgumentList 2>&1
  $code = $LASTEXITCODE
  $text = ($output | ForEach-Object { "$_" }) -join "`n"
  return [pscustomobject]@{
    ExitCode = $code
    Text     = $text.Trim()
  }
}

function Test-CommandAvailable {
  param([Parameter(Mandatory)][string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

try {
  $scriptDir = Split-Path -Parent $PSCommandPath
  $gitProbe = Invoke-Fixed -FilePath 'git' -ArgumentList @(
    '-C', $scriptDir, 'rev-parse', '--show-toplevel'
  )
  if ($gitProbe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($gitProbe.Text)) {
    throw 'unable to resolve repository root'
  }
  $repoRoot = [System.IO.Path]::GetFullPath($gitProbe.Text.Trim())
  Set-Location -LiteralPath $repoRoot
}
catch {
  Write-Error ("invalid repository: {0}" -f $_.Exception.Message)
  exit 2
}

$checks = [System.Collections.Generic.List[object]]::new()

$gitVersion = Invoke-Fixed -FilePath 'git' -ArgumentList @('--version')
if ($gitVersion.ExitCode -eq 0) {
  $checks.Add((New-Check 'git' 'passed' $gitVersion.Text))
}
else {
  $checks.Add((New-Check 'git' 'failed' 'git not found'))
}

$checks.Add((New-Check 'pwsh' 'passed' ("pwsh={0}" -f $PSVersionTable.PSVersion.ToString())))

$rootCheck = Invoke-Fixed -FilePath 'git' -ArgumentList @('rev-parse', '--show-toplevel')
$resolvedRoot = if ($rootCheck.ExitCode -eq 0) {
  [System.IO.Path]::GetFullPath($rootCheck.Text.Trim())
}
else {
  ''
}
if ($resolvedRoot -eq $repoRoot) {
  $checks.Add((New-Check 'git_root' 'passed' $repoRoot))
}
else {
  $checks.Add((New-Check 'git_root' 'failed' 'repository root mismatch'))
}

$branchResult = Invoke-Fixed -FilePath 'git' -ArgumentList @('rev-parse', '--abbrev-ref', 'HEAD')
$branch = if ($branchResult.ExitCode -eq 0) { $branchResult.Text.Trim() } else { 'unknown' }
# Personal mode: develop is the daily branch and must pass.
if ($branch -in @('main', 'master')) {
  $checks.Add((New-Check 'branch' 'warn' ("branch={0}" -f $branch)))
}
else {
  $checks.Add((New-Check 'branch' 'passed' ("branch={0}" -f $branch)))
}

$statusResult = Invoke-Fixed -FilePath 'git' -ArgumentList @('status', '--porcelain')
$dirtyLines = @()
if ($statusResult.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($statusResult.Text)) {
  $dirtyLines = @(
    $statusResult.Text -split "`n" |
      Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
      ForEach-Object {
        $line = $_.TrimEnd()
        if ($line.Length -ge 3) { $line.Substring(3).Trim() } else { $line }
      }
  )
}
if ($dirtyLines.Count -gt 0) {
  $summary = "dirty_paths={0}; paths={1}" -f $dirtyLines.Count, (($dirtyLines | Select-Object -First 20) -join ', ')
  if ($RequireClean) {
    $checks.Add((New-Check 'dirty_worktree' 'failed' $summary))
  }
  else {
    $checks.Add((New-Check 'dirty_worktree' 'warn' $summary))
  }
}
else {
  $checks.Add((New-Check 'dirty_worktree' 'passed' 'clean'))
}

foreach ($tool in @('python', 'uv', 'node', 'pnpm')) {
  if (Test-CommandAvailable $tool) {
    $ver = Invoke-Fixed -FilePath $tool -ArgumentList @('--version')
    $detail = if ($ver.ExitCode -eq 0) { $ver.Text } else { 'available' }
    $checks.Add((New-Check $tool 'passed' $detail))
  }
  else {
    $checks.Add((New-Check $tool 'unavailable' ("{0} not found" -f $tool)))
  }
}

$dataCandidates = @(
  'data',
  'data/parquet',
  'data/raw'
)
foreach ($relative in $dataCandidates) {
  $full = Join-Path $repoRoot $relative
  if (Test-Path -LiteralPath $full) {
    $checks.Add((New-Check ("data_path:{0}" -f $relative) 'passed' 'present'))
  }
  else {
    $checks.Add((New-Check ("data_path:{0}" -f $relative) 'warn' 'absent'))
  }
}

$secretNamePattern = [regex]'^(?i).*(PASSWORD|PASSWD|TOKEN|SECRET|API[_-]?KEY|WEBHOOK|LICENSE|PRIVATE[_-]?KEY|DATABASE_URL).*$'
$secretNameCount = @(
  [System.Environment]::GetEnvironmentVariables().Keys |
    Where-Object { $secretNamePattern.IsMatch([string]$_) }
).Count
$checks.Add((New-Check 'secret_like_env_names' 'passed' ("count={0}" -f $secretNameCount)))

$failed = @($checks | Where-Object { $_.status -eq 'failed' }).Count
$unavailable = @($checks | Where-Object { $_.status -eq 'unavailable' }).Count
$warn = @($checks | Where-Object { $_.status -eq 'warn' }).Count
$passed = @($checks | Where-Object { $_.status -eq 'passed' }).Count
$status = if ($failed -gt 0) { 'failed' } else { 'ok' }

$payload = [ordered]@{
  schema_version = 1
  tool           = 'scripts/engineering/preflight.ps1'
  operation      = 'preflight'
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
  Write-Output ("[preflight] status={0} branch={1}" -f $status, $branch)
  foreach ($check in $checks) {
    Write-Output ("  {0}: {1} ({2})" -f $check.name, $check.status, $check.detail)
  }
}

if ($failed -gt 0) {
  exit 1
}
exit 0
