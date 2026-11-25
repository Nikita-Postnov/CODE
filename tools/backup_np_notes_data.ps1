# Verified read-only backup of an NP Notes Data tree.
# Windows PowerShell 5.1+. Does not stop Notes or edit any source file.
param(
    [Parameter(Mandatory=$true)][string]$SourceRoot,
    [Parameter(Mandatory=$true)][string]$BackupRoot
)
$ErrorActionPreference = 'Stop'

function FullPath([string]$PathText) {
    return [IO.Path]::GetFullPath($PathText).TrimEnd('\')
}
function Under([string]$Parent, [string]$Child) {
    return $Child.StartsWith($Parent + '\', [StringComparison]::OrdinalIgnoreCase)
}
$source = FullPath $SourceRoot
$destination = FullPath $BackupRoot
if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Source directory does not exist: $source"
}
$sourceInfo = Get-Item -LiteralPath $source -Force
if (($sourceInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'Source cannot be a link or junction'
}
if ($source -eq $destination -or (Under $source $destination) -or (Under $destination $source)) {
    throw 'Source and destination may not overlap'
}
if (Test-Path -LiteralPath $destination) {
    throw "Backup directory already exists; refusing to overwrite: $destination"
}

# Preflight all entries before writing. Runtime diagnostic logs located
# directly inside Data are not note content and may be exclusively locked.
# Do NOT exclude .log attachments in nested Notes or other data folders.
function IsRuntimeLog($Item) {
    if (-not $Item -or -not $Item.FullName) { return $false }
    $parent = [IO.Path]::GetDirectoryName($Item.FullName).TrimEnd('\')
    if (-not [string]::Equals($parent, $source, [StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    # Include rotated diagnostics, e.g. crash.log.1 and language_indicator_error.log.
    return $Item.Name -match '(?i)\.log(?:\.\d+)?$'
}
$allFiles = @(Get-ChildItem -LiteralPath $source -File -Recurse -Force)
$files = @($allFiles | Where-Object { -not (IsRuntimeLog $_) })
$skippedLogs = @($allFiles | Where-Object { IsRuntimeLog $_ })
$folders = @(Get-ChildItem -LiteralPath $source -Directory -Recurse -Force)
foreach ($entry in @($files) + @($folders)) {
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Link/junction in Data: $($entry.FullName)"
    }
}
$manifest = [System.Collections.Generic.List[object]]::new()
$staging = $destination + '.staging-' + [guid]::NewGuid().ToString('N')
try {
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    foreach ($folder in $folders) {
        $relative = $folder.FullName.Substring($source.Length).TrimStart('\')
        New-Item -ItemType Directory -Path (Join-Path $staging $relative) -Force | Out-Null
    }
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($source.Length).TrimStart('\')
        $target = Join-Path $staging $relative
        $parent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        $before = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        Copy-Item -LiteralPath $file.FullName -Destination $target -ErrorAction Stop
        $after = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        $sourceAfter = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        if ($before -ne $after -or $before -ne $sourceAfter) {
            throw "File changed during backup or hash mismatch: $relative"
        }
        $manifest.Add([pscustomobject]@{
            RelativePath = $relative
            Bytes = $file.Length
            SHA256 = $before
        })
    }
    # Also ensure files did not appear/disappear mid-backup.
    $latest = @(Get-ChildItem -LiteralPath $source -File -Recurse -Force |
        Where-Object { -not (IsRuntimeLog $_) })
    if ($latest.Count -ne $files.Count) {
        throw 'Source file count changed during backup; retry while Notes is closed'
    }
    $manifestPath = Join-Path $staging 'SHA256-manifest.json'
    ConvertTo-Json -InputObject @($manifest.ToArray()) -Depth 4 |
        Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Move-Item -LiteralPath $staging -Destination $destination -ErrorAction Stop
    Write-Output "BACKUP_VERIFIED=$destination"
    Write-Output "FILE_COUNT=$($files.Count)"
    Write-Output "SKIPPED_DIAGNOSTIC_LOGS=$($skippedLogs.Count)"
}
catch {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
