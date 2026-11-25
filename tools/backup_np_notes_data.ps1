# NP Notes ONLY: verified, read-only Windows PowerShell 5.1 backup.
# Data is SHARED with other Choice tools; never recursively back up all Data.
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
if (-not (Test-Path -LiteralPath (Join-Path $source 'Notes') -PathType Container)) {
    throw "Notes directory missing; refusing to back up the wrong Data folder: $source"
}
if ($source -eq $destination -or (Under $source $destination) -or (Under $destination $source)) {
    throw 'Source and destination may not overlap'
}
if (Test-Path -LiteralPath $destination) {
    throw "Backup directory already exists; refusing to overwrite: $destination"
}

# Explicitly mapped from noteapp/config.py.
# Never include LaptopCare, Nicholas, LanguageIndicator, logs or other apps.
$noteDirs = @('Notes', 'Passwords', 'Plugins', 'Recovery')
$noteFiles = @(
    'settings.ini', 'notes_order.json', 'salt.bin', 'user_dictionary.txt',
    'desktop_notes.json', 'desktop_notes.json.bak',
    'icon.ico', 'tray_icon.ico', 'file.ico'
)
$selectedFiles = [System.Collections.Generic.List[object]]::new()
$selectedDirs = [System.Collections.Generic.List[object]]::new()

foreach ($name in $noteDirs) {
    $dir = Join-Path $source $name
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    $item = Get-Item -LiteralPath $dir -Force
    if (-not $item.PSIsContainer -or
        (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw "Unsafe note directory: $dir"
    }
    $selectedDirs.Add($item)
    foreach ($entry in (Get-ChildItem -LiteralPath $dir -Recurse -Force)) {
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Link/junction in note data: $($entry.FullName)"
        }
        if ($entry.PSIsContainer) {
            $selectedDirs.Add($entry)
        }
        else {
            $selectedFiles.Add($entry)
        }
    }
}
foreach ($name in $noteFiles) {
    $file = Join-Path $source $name
    if (-not (Test-Path -LiteralPath $file)) { continue }
    $item = Get-Item -LiteralPath $file -Force
    if ($item.PSIsContainer -or
        (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw "Unsafe note file: $file"
    }
    $selectedFiles.Add($item)
}
if ($selectedFiles.Count -eq 0) {
    throw 'No Notes data files found; refusing to create a misleading empty backup'
}

$staging = $destination + '.staging-' + [guid]::NewGuid().ToString('N')
$manifest = [System.Collections.Generic.List[object]]::new()
try {
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    foreach ($folder in $selectedDirs) {
        $relative = $folder.FullName.Substring($source.Length).TrimStart('\')
        New-Item -ItemType Directory -Path (Join-Path $staging $relative) -Force | Out-Null
    }
    foreach ($file in $selectedFiles) {
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
            throw "Source changed or hash mismatch: $relative"
        }
        $manifest.Add([pscustomobject]@{
            RelativePath = $relative
            Bytes = (Get-Item -LiteralPath $target).Length
            SHA256 = $before
        })
    }
    # Re-enumerate only Notes' own directories/files to catch concurrent changes.
    $latest = [System.Collections.Generic.List[string]]::new()
    foreach ($name in $noteDirs) {
        $dir = Join-Path $source $name
        if (Test-Path -LiteralPath $dir -PathType Container) {
            foreach ($file in (Get-ChildItem -LiteralPath $dir -File -Recurse -Force)) {
                $latest.Add($file.FullName)
            }
        }
    }
    foreach ($name in $noteFiles) {
        $file = Join-Path $source $name
        if (Test-Path -LiteralPath $file -PathType Leaf) { $latest.Add($file) }
    }
    $first = @($selectedFiles | ForEach-Object { $_.FullName } | Sort-Object)
    $second = @($latest | Sort-Object)
    if (($first.Count -ne $second.Count) -or
        ((Compare-Object -ReferenceObject $first -DifferenceObject $second) | Measure-Object).Count -ne 0) {
        throw 'Note files changed during backup; retry with Notes closed'
    }
    ConvertTo-Json -InputObject @($manifest.ToArray()) -Depth 4 |
        Set-Content -LiteralPath (Join-Path $staging 'SHA256-manifest.json') -Encoding UTF8
    Move-Item -LiteralPath $staging -Destination $destination -ErrorAction Stop
    Write-Output "BACKUP_VERIFIED=$destination"
    Write-Output "FILE_COUNT=$($manifest.Count)"
    Write-Output 'SCOPE=NP_NOTES_ONLY'
}
catch {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
