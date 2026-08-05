#Requires -Version 7.0
<#
.SYNOPSIS
  Safe PublishBranch / PublishTag operations for controlled release refs.

.DESCRIPTION
  Fast-forward-only branch publication and annotated tag push.
  No force flags, rollback tags, packets, or hash authorization options.
  -WhatIf never mutates and never authorizes a later mutation.

.EXITCODES
  0 success / successful dry-run
  1 operation failed or blocked
  2 invalid invocation
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $false)]
  [ValidateSet('PublishBranch', 'PublishTag')]
  [string]$Operation = '',

  [string]$Remote = 'origin',
  [string]$SourceRef = 'develop',
  [string]$TargetBranch = 'main',
  [string]$TagName = '',
  [string]$Message = '',
  [switch]$WhatIf,
  [switch]$Json,
  [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Usage {
  @"
Usage:
  pwsh -NoProfile -File scripts/engineering/release-tag.ps1 -Operation PublishBranch -Remote origin -SourceRef develop -TargetBranch main [-WhatIf] [-Json]
  pwsh -NoProfile -File scripts/engineering/release-tag.ps1 -Operation PublishTag -Remote origin -SourceRef develop -TagName v1.0.0 -Message 'release' [-WhatIf] [-Json]
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

if ([string]::IsNullOrWhiteSpace($Operation)) {
  Write-Error 'Operation is required'
  Write-Usage
  exit 2
}

if ($Remote -notmatch '^[A-Za-z0-9._/-]+$' -or $SourceRef -notmatch '^[A-Za-z0-9._/-]+$') {
  Write-Error 'Remote/SourceRef contain unsupported characters'
  exit 2
}

if ($Operation -eq 'PublishBranch' -and $TargetBranch -notmatch '^[A-Za-z0-9._/-]+$') {
  Write-Error 'TargetBranch is invalid'
  exit 2
}

if ($Operation -eq 'PublishTag') {
  if ([string]::IsNullOrWhiteSpace($TagName) -or $TagName -notmatch '^[A-Za-z0-9._/-]+$') {
    Write-Error 'TagName is required and must be a valid ref name'
    exit 2
  }
  if ([string]::IsNullOrWhiteSpace($Message)) {
    Write-Error 'Message is required for PublishTag'
    exit 2
  }
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

function Invoke-Git {
  param([string[]]$ArgumentList)
  $output = & git @ArgumentList 2>&1
  return [pscustomobject]@{
    ExitCode = $LASTEXITCODE
    Text     = (($output | ForEach-Object { "$_" }) -join "`n").Trim()
  }
}

function New-Check {
  param([string]$Name, [string]$Status, [string]$Detail)
  [pscustomobject]@{ name = $Name; status = $Status; detail = $Detail }
}

$checks = [System.Collections.Generic.List[object]]::new()
$mode = if ($WhatIf) { 'dry_run' } else { 'mutation' }
$errorObject = $null
$status = 'ok'

# Clean worktree required for release/tag mutations and dry-runs that claim readiness.
$porcelain = Invoke-Git @('status', '--porcelain')
if ($porcelain.ExitCode -ne 0) {
  Write-Error 'git status failed'
  exit 2
}
if (-not [string]::IsNullOrWhiteSpace($porcelain.Text)) {
  $checks.Add((New-Check 'clean_worktree' 'failed' 'worktree is dirty'))
  $status = 'blocked'
  $errorObject = [ordered]@{ type = 'operation_blocked'; detail = 'clean worktree required' }
}
else {
  $checks.Add((New-Check 'clean_worktree' 'passed' 'clean'))
}

$sourceSha = Invoke-Git @('rev-parse', $SourceRef)
if ($sourceSha.ExitCode -ne 0 -or $sourceSha.Text -notmatch '^[0-9a-f]{40}$') {
  $checks.Add((New-Check 'source_ref' 'failed' 'source ref unavailable'))
  $status = 'blocked'
  $errorObject = [ordered]@{ type = 'invalid_scope'; detail = 'source ref unavailable' }
}
else {
  $checks.Add((New-Check 'source_ref' 'passed' $sourceSha.Text))
}

$targetDisplay = if ($Operation -eq 'PublishBranch') {
  "{0}/{1}" -f $Remote, $TargetBranch
}
else {
  "{0} tag {1}" -f $Remote, $TagName
}

# Announce exact target before any mutation.
$announcement = "target={0}; commit={1}; mode={2}" -f $targetDisplay, $sourceSha.Text, $mode
$checks.Add((New-Check 'target_announcement' 'passed' $announcement))
if (-not $Json) {
  Write-Output ("[release-tag] {0}" -f $announcement)
}

if ($status -ne 'ok') {
  # blocked before mutation
}
elseif ($Operation -eq 'PublishBranch') {
  $fetch = Invoke-Git @('fetch', $Remote, $TargetBranch)
  if ($fetch.ExitCode -ne 0) {
    # Local bare remotes may still allow ls-remote; treat fetch failure as blocked.
    $checks.Add((New-Check 'fetch_target' 'failed' 'unable to fetch target branch'))
    $status = 'blocked'
    $errorObject = [ordered]@{ type = 'operation_blocked'; detail = 'target branch unavailable' }
  }
  else {
    $checks.Add((New-Check 'fetch_target' 'passed' 'fetched'))
    $remoteSha = Invoke-Git @('rev-parse', ("{0}/{1}" -f $Remote, $TargetBranch))
    if ($remoteSha.ExitCode -ne 0) {
      $checks.Add((New-Check 'remote_target' 'failed' 'remote target missing'))
      $status = 'blocked'
      $errorObject = [ordered]@{ type = 'operation_blocked'; detail = 'remote target missing' }
    }
    else {
      $ff = Invoke-Git @('merge-base', '--is-ancestor', $remoteSha.Text, $sourceSha.Text)
      if ($ff.ExitCode -ne 0) {
        $checks.Add((New-Check 'fast_forward' 'failed' 'non-fast-forward'))
        $status = 'blocked'
        $errorObject = [ordered]@{ type = 'operation_blocked'; detail = 'fast-forward only' }
      }
      else {
        $checks.Add((New-Check 'fast_forward' 'passed' 'fast-forward ok'))
        if ($WhatIf) {
          $checks.Add((New-Check 'publish_branch' 'passed' 'dry-run; no mutation'))
        }
        else {
          $push = Invoke-Git @('push', $Remote, ("{0}:{1}" -f $SourceRef, $TargetBranch))
          if ($push.ExitCode -ne 0) {
            $checks.Add((New-Check 'publish_branch' 'failed' 'push failed'))
            $status = 'failed'
            $errorObject = [ordered]@{ type = 'operation_failed'; detail = 'branch push failed' }
          }
          else {
            $checks.Add((New-Check 'publish_branch' 'passed' 'pushed'))
          }
        }
      }
    }
  }
}
elseif ($Operation -eq 'PublishTag') {
  $existing = Invoke-Git @('rev-parse', '-q', '--verify', ("refs/tags/{0}" -f $TagName))
  if ($existing.ExitCode -eq 0) {
    $checks.Add((New-Check 'tag_conflict' 'failed' 'tag already exists'))
    $status = 'blocked'
    $errorObject = [ordered]@{ type = 'operation_blocked'; detail = 'conflicting tag' }
  }
  else {
    $checks.Add((New-Check 'tag_conflict' 'passed' 'tag available'))
    if ($WhatIf) {
      $checks.Add((New-Check 'publish_tag' 'passed' 'dry-run; no mutation'))
    }
    else {
      $tag = Invoke-Git @('tag', '-a', $TagName, $sourceSha.Text, '-m', $Message)
      if ($tag.ExitCode -ne 0) {
        $checks.Add((New-Check 'publish_tag' 'failed' 'tag create failed'))
        $status = 'failed'
        $errorObject = [ordered]@{ type = 'operation_failed'; detail = 'tag create failed' }
      }
      else {
        $push = Invoke-Git @('push', $Remote, ("refs/tags/{0}" -f $TagName))
        if ($push.ExitCode -ne 0) {
          $checks.Add((New-Check 'publish_tag' 'failed' 'tag push failed'))
          $status = 'failed'
          $errorObject = [ordered]@{ type = 'operation_failed'; detail = 'tag push failed' }
        }
        else {
          $checks.Add((New-Check 'publish_tag' 'passed' 'tag published'))
        }
      }
    }
  }
}

$scope = [ordered]@{
  category          = if ($Operation -eq 'PublishBranch') { 'release_branch' } else { 'push_tag' }
  environment       = 'local'
  target            = $targetDisplay
  resource_boundary = @('remote_release_ref')
  remote            = $Remote
  commit            = $sourceSha.Text
}

$payload = [ordered]@{
  schema_version = 1
  tool           = 'scripts/engineering/release-tag.ps1'
  operation      = if ($Operation -eq 'PublishBranch') { 'publish_branch' } else { 'publish_tag' }
  mode           = $mode
  status         = $status
  summary        = [ordered]@{
    passed      = @($checks | Where-Object { $_.status -eq 'passed' }).Count
    failed      = @($checks | Where-Object { $_.status -eq 'failed' }).Count
    warn        = @($checks | Where-Object { $_.status -eq 'warn' }).Count
    unavailable = @($checks | Where-Object { $_.status -eq 'unavailable' }).Count
  }
  checks         = @($checks)
  scope          = $scope
}
if ($null -ne $errorObject) {
  $payload['error'] = $errorObject
}

if ($Json) {
  $payload | ConvertTo-Json -Depth 6 -Compress
}
else {
  Write-Output ("[release-tag] status={0}" -f $status)
  foreach ($check in $checks) {
    Write-Output ("  {0}: {1} ({2})" -f $check.name, $check.status, $check.detail)
  }
}

if ($status -eq 'ok') { exit 0 }
if ($status -in @('failed', 'blocked', 'unavailable')) { exit 1 }
exit 1
