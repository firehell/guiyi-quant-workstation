#Requires -Version 7.0
<#
.SYNOPSIS
  Fail-closed secret scan for repository-contained paths.

.DESCRIPTION
  Scans text files for high-confidence secret pattern families.
  Reports only path, line number, and pattern family. Never prints matched text.

.EXITCODES
  0 success (or warn-only hits)
  1 hits found (fail-closed)
  2 invalid invocation / path escape
#>
[CmdletBinding()]
param(
  [string[]]$Path = @(),
  [switch]$WarnOnly,
  [switch]$Json,
  [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Usage {
  @"
Usage: pwsh -NoProfile -File scripts/engineering/secret-scan.ps1 [-Path <repo-relative>...] [-WarnOnly] [-Json]
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

try {
  $scriptDir = Split-Path -Parent $PSCommandPath
  $repoRoot = (& git -C $scriptDir rev-parse --show-toplevel 2>$null)
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    throw 'repository root unavailable'
  }
  $repoRoot = [System.IO.Path]::GetFullPath($repoRoot.Trim())
}
catch {
  Write-Error $_.Exception.Message
  exit 2
}

function Resolve-ContainedPath {
  param([Parameter(Mandatory)][string]$Candidate)
  $combined = if ([System.IO.Path]::IsPathRooted($Candidate)) {
    $Candidate
  }
  else {
    Join-Path $repoRoot $Candidate
  }
  $full = [System.IO.Path]::GetFullPath($combined)
  $rootPrefix = if ($repoRoot.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
    $repoRoot
  }
  else {
    $repoRoot + [System.IO.Path]::DirectorySeparatorChar
  }
  if (-not ($full.Equals($repoRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
      $full.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase))) {
    throw ("path escapes repository root: {0}" -f $Candidate)
  }
  return $full
}

$skipSuffix = [System.Collections.Generic.HashSet[string]]::new(
  [string[]]@(
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.svg',
    '.parquet', '.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe',
    '.zip', '.gz', '.bz2', '.xz', '.7z', '.tar',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.lock', '.pdf', '.bin', '.dat'
  ),
  [System.StringComparer]::OrdinalIgnoreCase
)
$skipDirs = [System.Collections.Generic.HashSet[string]]::new(
  [string[]]@('.git', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build',
    '.pytest_cache', '.mypy_cache', '.ruff_cache'),
  [System.StringComparer]::OrdinalIgnoreCase
)
$maxBytes = 1000000

$families = @(
  @{ Name = 'wechat_webhook'; Pattern = 'qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]{8,}' }
  @{ Name = 'github_pat'; Pattern = '\bghp_[A-Za-z0-9]{20,}\b' }
  @{ Name = 'github_fine_grained'; Pattern = '\bgithub_pat_[A-Za-z0-9_]{20,}\b' }
  @{ Name = 'aws_access_key'; Pattern = '\bAKIA[0-9A-Z]{16}\b' }
  @{ Name = 'private_key_block'; Pattern = '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----' }
  @{
    Name    = 'secret_assignment'
    Pattern = '(?i)\b(?:DATABASE_URL|QYWX_WEBHOOK(?:_URL)?|API[_-]?KEY|ACCESS[_-]?TOKEN|PASSWORD|SECRET|WEBHOOK(?:_URL)?|TOKEN)\b\s*[:=]\s*([''"])([^''"]{16,})\1'
  }
  @{
    Name    = 'database_url'
    Pattern = '(?i)\bDATABASE_URL\b\s*[:=]\s*(postgres(?:ql)?://[^\s''"\\]{12,})'
  }
)

$placeholderTokens = @(
  'replace-with-', 'example', 'redacted', 'os.getenv', 'environ', 'getenv(',
  'your-', 'your_', 'xxx', 'todo', 'placeholder', '${', 'settings.', 'config.',
  'changeme', 'dummy', 'sample', 'fake-', 'test-only', '<your', 'not-a-real',
  'localstorage', 'normalize_database_url'
)

function Test-ShouldSkip {
  param([Parameter(Mandatory)][string]$FullPath)
  try {
    $rel = [System.IO.Path]::GetRelativePath($repoRoot, $FullPath).Replace('\', '/')
  }
  catch {
    return $true
  }
  $parts = $rel -split '/'
  foreach ($part in $parts) {
    if ($skipDirs.Contains($part)) { return $true }
  }
  if ($rel.StartsWith('data/raw/') -or $rel.StartsWith('data/parquet/')) { return $true }
  if ($rel.Contains('/cache/api_docs/')) { return $true }
  if ($rel.EndsWith('.example')) { return $true }
  $ext = [System.IO.Path]::GetExtension($FullPath)
  if ($skipSuffix.Contains($ext)) { return $true }
  try {
    $info = Get-Item -LiteralPath $FullPath -ErrorAction Stop
    if ($info.Length -gt $maxBytes) { return $true }
  }
  catch {
    return $true
  }
  return $false
}

function Test-IsPlaceholder {
  param([string]$Line)
  $lower = $Line.ToLowerInvariant()
  foreach ($token in $placeholderTokens) {
    if ($lower.Contains($token.ToLowerInvariant())) { return $true }
  }
  if ($Line -match '\$\{[A-Za-z_][A-Za-z0-9_]*\}') { return $true }
  return $false
}

$targets = [System.Collections.Generic.List[string]]::new()
try {
  if ($Path.Count -gt 0) {
    foreach ($item in $Path) {
      $full = Resolve-ContainedPath -Candidate $item
      if (Test-Path -LiteralPath $full -PathType Container) {
        Get-ChildItem -LiteralPath $full -Recurse -File | ForEach-Object {
          if (-not (Test-ShouldSkip $_.FullName)) {
            $targets.Add($_.FullName)
          }
        }
      }
      elseif (Test-Path -LiteralPath $full -PathType Leaf) {
        if (-not (Test-ShouldSkip $full)) {
          $targets.Add($full)
        }
      }
      else {
        throw ("path not found: {0}" -f $item)
      }
    }
  }
  else {
    $listed = & git -C $repoRoot ls-files -z
    if ($LASTEXITCODE -ne 0) {
      throw 'git ls-files failed'
    }
    foreach ($rel in ($listed -split "`0")) {
      if ([string]::IsNullOrWhiteSpace($rel)) { continue }
      $full = Join-Path $repoRoot $rel
      if ((Test-Path -LiteralPath $full -PathType Leaf) -and -not (Test-ShouldSkip $full)) {
        $targets.Add([System.IO.Path]::GetFullPath($full))
      }
    }
  }
}
catch {
  Write-Error $_.Exception.Message
  exit 2
}

$hits = [System.Collections.Generic.List[object]]::new()
$scanned = 0
foreach ($file in $targets) {
  try {
    $lines = [System.IO.File]::ReadAllLines($file)
  }
  catch {
    continue
  }
  $scanned++
  $rel = [System.IO.Path]::GetRelativePath($repoRoot, $file).Replace('\', '/')
  for ($i = 0; $i -lt $lines.Length; $i++) {
    $line = $lines[$i]
    if (Test-IsPlaceholder $line) { continue }
    foreach ($family in $families) {
      if ([regex]::IsMatch($line, $family.Pattern)) {
        $hits.Add([pscustomobject]@{
            path          = $rel
            line          = ($i + 1)
            pattern_family = $family.Name
          })
        break
      }
    }
  }
}

$failed = if ($hits.Count -gt 0 -and -not $WarnOnly) { 1 } else { 0 }
$warn = if ($hits.Count -gt 0 -and $WarnOnly) { $hits.Count } else { 0 }
$status = if ($failed -gt 0) {
  'failed'
}
elseif ($hits.Count -gt 0) {
  'ok'
}
else {
  'ok'
}

$checks = [System.Collections.Generic.List[object]]::new()
$checks.Add([pscustomobject]@{
    name   = 'secret_scan'
    status = if ($hits.Count -eq 0) { 'passed' } elseif ($WarnOnly) { 'warn' } else { 'failed' }
    detail = ("scanned_files={0}; hits={1}" -f $scanned, $hits.Count)
  })
foreach ($hit in ($hits | Select-Object -First 50)) {
  $checks.Add([pscustomobject]@{
      name   = 'secret_hit'
      status = if ($WarnOnly) { 'warn' } else { 'failed' }
      detail = ("{0}:{1}: family={2}" -f $hit.path, $hit.line, $hit.pattern_family)
    })
}

$payload = [ordered]@{
  schema_version = 1
  tool           = 'scripts/engineering/secret-scan.ps1'
  operation      = 'secret_scan'
  mode           = 'read_only'
  status         = $status
  summary        = [ordered]@{
    passed      = @($checks | Where-Object { $_.status -eq 'passed' }).Count
    failed      = @($checks | Where-Object { $_.status -eq 'failed' }).Count
    warn        = @($checks | Where-Object { $_.status -eq 'warn' }).Count
    unavailable = 0
  }
  checks         = @($checks)
}

if ($Json) {
  $payload | ConvertTo-Json -Depth 6 -Compress
}
else {
  Write-Output ("[OK] scanned_files={0}" -f $scanned)
  if ($hits.Count -gt 0) {
    Write-Output ("[FAIL] potential_secrets={0} (values not printed)" -f $hits.Count)
    foreach ($hit in ($hits | Select-Object -First 50)) {
      Write-Output ("  {0}:{1}: family={2}" -f $hit.path, $hit.line, $hit.pattern_family)
    }
  }
  else {
    Write-Output '[OK] no high-confidence secrets found'
  }
}

if ($failed -gt 0) { exit 1 }
exit 0
