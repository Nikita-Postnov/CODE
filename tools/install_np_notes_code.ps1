# NP Notes code-only deployment. Windows PowerShell 5.1.
# Default action is report-only; -Apply is explicit and NEVER modifies Data.
param(
    [string]$LauncherRoot = 'C:\WORK\NP\Launcher',
    [string]$CommitSha = '',
    [string]$ManifestPath = '',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Assert-File([string]$PathText) {
    if (-not (Test-Path -LiteralPath $PathText -PathType Leaf)) {
        throw "Missing file: $PathText"
    }
}
function Copy-OnlyCode([string]$From, [string]$To) {
    Copy-Item -LiteralPath (Join-Path $From 'notes_app.py') -Destination (Join-Path $To 'notes_app.py') -Force
    Copy-Item -LiteralPath (Join-Path $From 'noteapp') -Destination (Join-Path $To 'noteapp') -Recurse
}
function GitBlobSha([string]$PathText) {
    $bytes = [IO.File]::ReadAllBytes($PathText)
    $header = [Text.Encoding]::ASCII.GetBytes("blob $($bytes.Length)`0")
    $buffer = New-Object byte[] ($header.Length + $bytes.Length)
    [Array]::Copy($header, 0, $buffer, 0, $header.Length)
    [Array]::Copy($bytes, 0, $buffer, $header.Length, $bytes.Length)
    $sha1 = [Security.Cryptography.SHA1]::Create()
    try {
        return ([BitConverter]::ToString($sha1.ComputeHash($buffer))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha1.Dispose()
    }
}
function Assert-ReleaseFiles([string]$RootPath, [object]$Manifest) {
    if (-not $Manifest -or $Manifest.schema -ne 1 -or
        $Manifest.source_repository -ne 'Nikita-Postnov/CODE' -or
        $Manifest.source_directory -ne 'Other_dev' -or
        -not $Manifest.files -or @($Manifest.files).Count -lt 2) {
        throw 'Invalid NP Notes release manifest'
    }
    $seen = @{}
    foreach ($entry in $Manifest.files) {
        $relative = [string]$entry.path
        $expected = [string]$entry.git_blob_sha
        if (($relative -cne 'notes_app.py' -and
             $relative -cnotmatch '^noteapp/[A-Za-z0-9_./-]+
$entry = Join-Path $root 'notes_app.py'
$package = Join-Path $root 'noteapp'
$data = Join-Path $root 'Data'
$notes = Join-Path $data 'Notes'
Assert-File $entry
Assert-File (Join-Path $package 'app\__init__.py')
if (-not (Test-Path -LiteralPath $notes -PathType Container)) {
    throw "Missing active Notes data directory: $notes"
}
$processes = @(Get-CimInstance Win32_Process |
    Where-Object {
        ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
Write-Output "NOTES_PROCESSES=$($processes.Count)"
Write-Output "DATA_PATH=$data"
Write-Output "DEPLOY_SCOPE=notes_app.py,noteapp"
if (-not $Apply) {
    Write-Output 'DEPLOY_MODE=DRY_RUN'
    return
}
if ($processes.Count -gt 0) {
    throw 'NP Notes is still running; close all Notes processes before installation'
}
if ($CommitSha -notmatch '^[0-9a-f]{40}

# Fetch source into a scratch folder outside the shared launcher/Data.
$work = Join-Path $env:TEMP ('np-notes-code-release-' + [guid]::NewGuid().ToString('N'))
$zip = Join-Path $work 'source.zip'
$unpacked = Join-Path $work 'unzipped'
$stage = Join-Path $work 'stage'
$backupBase = Join-Path $env:USERPROFILE 'Documents\NP_Notes_Code_Backups'
$backup = Join-Path $backupBase ('Code_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + $CommitSha.Substring(0,12))
$rollbackInRoot = Join-Path $root ('.np-notes-rollback-' + [guid]::NewGuid().ToString('N'))
$changed = $false
$entryMoved = $false
$packageMoved = $false
New-Item -ItemType Directory -Path $work | Out-Null
try {
    Invoke-WebRequest -Uri "https://github.com/Nikita-Postnov/CODE/archive/$CommitSha.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath $unpacked
    $tree = Get-ChildItem -LiteralPath $unpacked -Directory | Select-Object -First 1
    if (-not $tree) { throw 'Candidate zip missing repository root' }
    $source = Join-Path $tree.FullName 'Other_dev'
    Assert-File (Join-Path $source 'notes_app.py')
    Assert-File (Join-Path $source 'noteapp\app\__init__.py')
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-OnlyCode $source $stage
    Assert-File (Join-Path $stage 'notes_app.py')
    Assert-File (Join-Path $stage 'noteapp\app\__init__.py')
    if ($manifest) { Assert-ReleaseFiles $stage $manifest }
    if (Test-Path -LiteralPath $backup) { throw 'Code backup already exists' }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-OnlyCode $root $backup
    Assert-File (Join-Path $backup 'notes_app.py')
    Assert-File (Join-Path $backup 'noteapp\app\__init__.py')
    Write-Output "CODE_BACKUP=$backup"

    # No automatic termination of user applications. Recheck before swap.
    $stillRunning = @(Get-CimInstance Win32_Process |
        Where-Object {
            ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
            ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        })
    if ($stillRunning.Count -gt 0) {
        throw 'NP Notes started during preparation; aborting without changing code'
    }
    New-Item -ItemType Directory -Path $rollbackInRoot | Out-Null
    try {
        Move-Item -LiteralPath $package -Destination (Join-Path $rollbackInRoot 'noteapp')
        $packageMoved = $true
        Move-Item -LiteralPath $entry -Destination (Join-Path $rollbackInRoot 'notes_app.py')
        $entryMoved = $true
        $changed = $true
        Copy-OnlyCode $stage $root
        Assert-File (Join-Path $root 'notes_app.py')
        Assert-File (Join-Path $root 'noteapp\app\__init__.py')
        # Validate code files against the staged artifact.
        $left = (Get-FileHash -LiteralPath (Join-Path $root 'notes_app.py') -Algorithm SHA256).Hash
        $right = (Get-FileHash -LiteralPath (Join-Path $stage 'notes_app.py') -Algorithm SHA256).Hash
        if ($left -ne $right) { throw 'Entry file validation failed' }
        if ($manifest) {
            Assert-ReleaseFiles $root $manifest
            Write-Output "RELEASE_FILES_VERIFIED=$(@($manifest.files).Count)"
        }
    }
    catch {
        if ($packageMoved -or $entryMoved) {
            if ($packageMoved) {
                Remove-Item -LiteralPath $package -Recurse -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'noteapp') -Destination $package
            }
            if ($entryMoved) {
                Remove-Item -LiteralPath $entry -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'notes_app.py') -Destination $entry
            }
            $changed = $false
        }
        throw
    }
    Write-Output "CODE_DEPLOYED_SHA=$CommitSha"
    Write-Output 'DATA_NOT_MODIFIED=TRUE'
}
finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ((-not $changed) -and (Test-Path -LiteralPath $rollbackInRoot)) {
        Remove-Item -LiteralPath $rollbackInRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($changed) {
        # Keep on-disk rollback even on success. Never auto-delete previous code.
        Write-Output "ROLLBACK_CODE=$rollbackInRoot"
    }
}
) -or
            $relative -match '(^|/)\.\.(/|$)' -or
            $expected -cnotmatch '^[0-9a-f]{40}
$entry = Join-Path $root 'notes_app.py'
$package = Join-Path $root 'noteapp'
$data = Join-Path $root 'Data'
$notes = Join-Path $data 'Notes'
Assert-File $entry
Assert-File (Join-Path $package 'app\__init__.py')
if (-not (Test-Path -LiteralPath $notes -PathType Container)) {
    throw "Missing active Notes data directory: $notes"
}
$processes = @(Get-CimInstance Win32_Process |
    Where-Object {
        ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
Write-Output "NOTES_PROCESSES=$($processes.Count)"
Write-Output "DATA_PATH=$data"
Write-Output "DEPLOY_SCOPE=notes_app.py,noteapp"
if (-not $Apply) {
    Write-Output 'DEPLOY_MODE=DRY_RUN'
    return
}
if ($processes.Count -gt 0) {
    throw 'NP Notes is still running; close all Notes processes before installation'
}
if ($CommitSha -notmatch '^[0-9a-f]{40}$') {
    throw 'An immutable 40-character commit SHA is mandatory for Apply'
}

# Fetch source into a scratch folder outside the shared launcher/Data.
$work = Join-Path $env:TEMP ('np-notes-code-release-' + [guid]::NewGuid().ToString('N'))
$zip = Join-Path $work 'source.zip'
$unpacked = Join-Path $work 'unzipped'
$stage = Join-Path $work 'stage'
$backupBase = Join-Path $env:USERPROFILE 'Documents\NP_Notes_Code_Backups'
$backup = Join-Path $backupBase ('Code_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + $CommitSha.Substring(0,12))
$rollbackInRoot = Join-Path $root ('.np-notes-rollback-' + [guid]::NewGuid().ToString('N'))
$changed = $false
$entryMoved = $false
$packageMoved = $false
New-Item -ItemType Directory -Path $work | Out-Null
try {
    Invoke-WebRequest -Uri "https://github.com/Nikita-Postnov/CODE/archive/$CommitSha.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath $unpacked
    $tree = Get-ChildItem -LiteralPath $unpacked -Directory | Select-Object -First 1
    if (-not $tree) { throw 'Candidate zip missing repository root' }
    $source = Join-Path $tree.FullName 'Other_dev'
    Assert-File (Join-Path $source 'notes_app.py')
    Assert-File (Join-Path $source 'noteapp\app\__init__.py')
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-OnlyCode $source $stage
    Assert-File (Join-Path $stage 'notes_app.py')
    Assert-File (Join-Path $stage 'noteapp\app\__init__.py')
    if (Test-Path -LiteralPath $backup) { throw 'Code backup already exists' }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-OnlyCode $root $backup
    Assert-File (Join-Path $backup 'notes_app.py')
    Assert-File (Join-Path $backup 'noteapp\app\__init__.py')
    Write-Output "CODE_BACKUP=$backup"

    # No automatic termination of user applications. Recheck before swap.
    $stillRunning = @(Get-CimInstance Win32_Process |
        Where-Object {
            ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
            ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        })
    if ($stillRunning.Count -gt 0) {
        throw 'NP Notes started during preparation; aborting without changing code'
    }
    New-Item -ItemType Directory -Path $rollbackInRoot | Out-Null
    try {
        Move-Item -LiteralPath $package -Destination (Join-Path $rollbackInRoot 'noteapp')
        $packageMoved = $true
        Move-Item -LiteralPath $entry -Destination (Join-Path $rollbackInRoot 'notes_app.py')
        $entryMoved = $true
        $changed = $true
        Copy-OnlyCode $stage $root
        Assert-File (Join-Path $root 'notes_app.py')
        Assert-File (Join-Path $root 'noteapp\app\__init__.py')
        # Validate code files against the staged artifact.
        $left = (Get-FileHash -LiteralPath (Join-Path $root 'notes_app.py') -Algorithm SHA256).Hash
        $right = (Get-FileHash -LiteralPath (Join-Path $stage 'notes_app.py') -Algorithm SHA256).Hash
        if ($left -ne $right) { throw 'Entry file validation failed' }
    }
    catch {
        if ($packageMoved -or $entryMoved) {
            if ($packageMoved) {
                Remove-Item -LiteralPath $package -Recurse -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'noteapp') -Destination $package
            }
            if ($entryMoved) {
                Remove-Item -LiteralPath $entry -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'notes_app.py') -Destination $entry
            }
            $changed = $false
        }
        throw
    }
    Write-Output "CODE_DEPLOYED_SHA=$CommitSha"
    Write-Output 'DATA_NOT_MODIFIED=TRUE'
}
finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ((-not $changed) -and (Test-Path -LiteralPath $rollbackInRoot)) {
        Remove-Item -LiteralPath $rollbackInRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($changed) {
        # Keep on-disk rollback even on success. Never auto-delete previous code.
        Write-Output "ROLLBACK_CODE=$rollbackInRoot"
    }
}
) {
            throw 'Unsafe release file path or digest'
        }
        $key = $relative.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { throw 'Duplicate release manifest path' }
        $seen[$key] = $true
        $path = Join-Path $RootPath ($relative.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw 'Release package missing required file'
        }
        if ((GitBlobSha $path) -cne $expected) {
            throw 'NP Notes release package checksum mismatch'
        }
    }
    if (-not $seen.ContainsKey('notes_app.py') -or
        -not $seen.ContainsKey('noteapp/__init__.py')) {
        throw 'Release manifest missing package entrypoint'
    }
}
$root = [IO.Path]::GetFullPath($LauncherRoot).TrimEnd('\')
$entry = Join-Path $root 'notes_app.py'
$package = Join-Path $root 'noteapp'
$data = Join-Path $root 'Data'
$notes = Join-Path $data 'Notes'
Assert-File $entry
Assert-File (Join-Path $package 'app\__init__.py')
if (-not (Test-Path -LiteralPath $notes -PathType Container)) {
    throw "Missing active Notes data directory: $notes"
}
$processes = @(Get-CimInstance Win32_Process |
    Where-Object {
        ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
Write-Output "NOTES_PROCESSES=$($processes.Count)"
Write-Output "DATA_PATH=$data"
Write-Output "DEPLOY_SCOPE=notes_app.py,noteapp"
if (-not $Apply) {
    Write-Output 'DEPLOY_MODE=DRY_RUN'
    return
}
if ($processes.Count -gt 0) {
    throw 'NP Notes is still running; close all Notes processes before installation'
}
if ($CommitSha -notmatch '^[0-9a-f]{40}$') {
    throw 'An immutable 40-character commit SHA is mandatory for Apply'
}

# Fetch source into a scratch folder outside the shared launcher/Data.
$work = Join-Path $env:TEMP ('np-notes-code-release-' + [guid]::NewGuid().ToString('N'))
$zip = Join-Path $work 'source.zip'
$unpacked = Join-Path $work 'unzipped'
$stage = Join-Path $work 'stage'
$backupBase = Join-Path $env:USERPROFILE 'Documents\NP_Notes_Code_Backups'
$backup = Join-Path $backupBase ('Code_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + $CommitSha.Substring(0,12))
$rollbackInRoot = Join-Path $root ('.np-notes-rollback-' + [guid]::NewGuid().ToString('N'))
$changed = $false
$entryMoved = $false
$packageMoved = $false
New-Item -ItemType Directory -Path $work | Out-Null
try {
    Invoke-WebRequest -Uri "https://github.com/Nikita-Postnov/CODE/archive/$CommitSha.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath $unpacked
    $tree = Get-ChildItem -LiteralPath $unpacked -Directory | Select-Object -First 1
    if (-not $tree) { throw 'Candidate zip missing repository root' }
    $source = Join-Path $tree.FullName 'Other_dev'
    Assert-File (Join-Path $source 'notes_app.py')
    Assert-File (Join-Path $source 'noteapp\app\__init__.py')
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-OnlyCode $source $stage
    Assert-File (Join-Path $stage 'notes_app.py')
    Assert-File (Join-Path $stage 'noteapp\app\__init__.py')
    if (Test-Path -LiteralPath $backup) { throw 'Code backup already exists' }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-OnlyCode $root $backup
    Assert-File (Join-Path $backup 'notes_app.py')
    Assert-File (Join-Path $backup 'noteapp\app\__init__.py')
    Write-Output "CODE_BACKUP=$backup"

    # No automatic termination of user applications. Recheck before swap.
    $stillRunning = @(Get-CimInstance Win32_Process |
        Where-Object {
            ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
            ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        })
    if ($stillRunning.Count -gt 0) {
        throw 'NP Notes started during preparation; aborting without changing code'
    }
    New-Item -ItemType Directory -Path $rollbackInRoot | Out-Null
    try {
        Move-Item -LiteralPath $package -Destination (Join-Path $rollbackInRoot 'noteapp')
        $packageMoved = $true
        Move-Item -LiteralPath $entry -Destination (Join-Path $rollbackInRoot 'notes_app.py')
        $entryMoved = $true
        $changed = $true
        Copy-OnlyCode $stage $root
        Assert-File (Join-Path $root 'notes_app.py')
        Assert-File (Join-Path $root 'noteapp\app\__init__.py')
        # Validate code files against the staged artifact.
        $left = (Get-FileHash -LiteralPath (Join-Path $root 'notes_app.py') -Algorithm SHA256).Hash
        $right = (Get-FileHash -LiteralPath (Join-Path $stage 'notes_app.py') -Algorithm SHA256).Hash
        if ($left -ne $right) { throw 'Entry file validation failed' }
    }
    catch {
        if ($packageMoved -or $entryMoved) {
            if ($packageMoved) {
                Remove-Item -LiteralPath $package -Recurse -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'noteapp') -Destination $package
            }
            if ($entryMoved) {
                Remove-Item -LiteralPath $entry -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'notes_app.py') -Destination $entry
            }
            $changed = $false
        }
        throw
    }
    Write-Output "CODE_DEPLOYED_SHA=$CommitSha"
    Write-Output 'DATA_NOT_MODIFIED=TRUE'
}
finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ((-not $changed) -and (Test-Path -LiteralPath $rollbackInRoot)) {
        Remove-Item -LiteralPath $rollbackInRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($changed) {
        # Keep on-disk rollback even on success. Never auto-delete previous code.
        Write-Output "ROLLBACK_CODE=$rollbackInRoot"
    }
}
) {
    throw 'An immutable 40-character commit SHA is mandatory for Apply'
}
$manifest = $null
if ($ManifestPath) {
    Assert-File $ManifestPath
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$manifest.source_commit -cne $CommitSha) {
        throw 'Release manifest commit does not match pinned installer commit'
    }
}

# Fetch source into a scratch folder outside the shared launcher/Data.
$work = Join-Path $env:TEMP ('np-notes-code-release-' + [guid]::NewGuid().ToString('N'))
$zip = Join-Path $work 'source.zip'
$unpacked = Join-Path $work 'unzipped'
$stage = Join-Path $work 'stage'
$backupBase = Join-Path $env:USERPROFILE 'Documents\NP_Notes_Code_Backups'
$backup = Join-Path $backupBase ('Code_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + $CommitSha.Substring(0,12))
$rollbackInRoot = Join-Path $root ('.np-notes-rollback-' + [guid]::NewGuid().ToString('N'))
$changed = $false
$entryMoved = $false
$packageMoved = $false
New-Item -ItemType Directory -Path $work | Out-Null
try {
    Invoke-WebRequest -Uri "https://github.com/Nikita-Postnov/CODE/archive/$CommitSha.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath $unpacked
    $tree = Get-ChildItem -LiteralPath $unpacked -Directory | Select-Object -First 1
    if (-not $tree) { throw 'Candidate zip missing repository root' }
    $source = Join-Path $tree.FullName 'Other_dev'
    Assert-File (Join-Path $source 'notes_app.py')
    Assert-File (Join-Path $source 'noteapp\app\__init__.py')
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-OnlyCode $source $stage
    Assert-File (Join-Path $stage 'notes_app.py')
    Assert-File (Join-Path $stage 'noteapp\app\__init__.py')
    if (Test-Path -LiteralPath $backup) { throw 'Code backup already exists' }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-OnlyCode $root $backup
    Assert-File (Join-Path $backup 'notes_app.py')
    Assert-File (Join-Path $backup 'noteapp\app\__init__.py')
    Write-Output "CODE_BACKUP=$backup"

    # No automatic termination of user applications. Recheck before swap.
    $stillRunning = @(Get-CimInstance Win32_Process |
        Where-Object {
            ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
            ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        })
    if ($stillRunning.Count -gt 0) {
        throw 'NP Notes started during preparation; aborting without changing code'
    }
    New-Item -ItemType Directory -Path $rollbackInRoot | Out-Null
    try {
        Move-Item -LiteralPath $package -Destination (Join-Path $rollbackInRoot 'noteapp')
        $packageMoved = $true
        Move-Item -LiteralPath $entry -Destination (Join-Path $rollbackInRoot 'notes_app.py')
        $entryMoved = $true
        $changed = $true
        Copy-OnlyCode $stage $root
        Assert-File (Join-Path $root 'notes_app.py')
        Assert-File (Join-Path $root 'noteapp\app\__init__.py')
        # Validate code files against the staged artifact.
        $left = (Get-FileHash -LiteralPath (Join-Path $root 'notes_app.py') -Algorithm SHA256).Hash
        $right = (Get-FileHash -LiteralPath (Join-Path $stage 'notes_app.py') -Algorithm SHA256).Hash
        if ($left -ne $right) { throw 'Entry file validation failed' }
    }
    catch {
        if ($packageMoved -or $entryMoved) {
            if ($packageMoved) {
                Remove-Item -LiteralPath $package -Recurse -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'noteapp') -Destination $package
            }
            if ($entryMoved) {
                Remove-Item -LiteralPath $entry -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'notes_app.py') -Destination $entry
            }
            $changed = $false
        }
        throw
    }
    Write-Output "CODE_DEPLOYED_SHA=$CommitSha"
    Write-Output 'DATA_NOT_MODIFIED=TRUE'
}
finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ((-not $changed) -and (Test-Path -LiteralPath $rollbackInRoot)) {
        Remove-Item -LiteralPath $rollbackInRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($changed) {
        # Keep on-disk rollback even on success. Never auto-delete previous code.
        Write-Output "ROLLBACK_CODE=$rollbackInRoot"
    }
}
) -or
            $relative -match '(^|/)\.\.(/|$)' -or
            $expected -cnotmatch '^[0-9a-f]{40}
$entry = Join-Path $root 'notes_app.py'
$package = Join-Path $root 'noteapp'
$data = Join-Path $root 'Data'
$notes = Join-Path $data 'Notes'
Assert-File $entry
Assert-File (Join-Path $package 'app\__init__.py')
if (-not (Test-Path -LiteralPath $notes -PathType Container)) {
    throw "Missing active Notes data directory: $notes"
}
$processes = @(Get-CimInstance Win32_Process |
    Where-Object {
        ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
Write-Output "NOTES_PROCESSES=$($processes.Count)"
Write-Output "DATA_PATH=$data"
Write-Output "DEPLOY_SCOPE=notes_app.py,noteapp"
if (-not $Apply) {
    Write-Output 'DEPLOY_MODE=DRY_RUN'
    return
}
if ($processes.Count -gt 0) {
    throw 'NP Notes is still running; close all Notes processes before installation'
}
if ($CommitSha -notmatch '^[0-9a-f]{40}$') {
    throw 'An immutable 40-character commit SHA is mandatory for Apply'
}

# Fetch source into a scratch folder outside the shared launcher/Data.
$work = Join-Path $env:TEMP ('np-notes-code-release-' + [guid]::NewGuid().ToString('N'))
$zip = Join-Path $work 'source.zip'
$unpacked = Join-Path $work 'unzipped'
$stage = Join-Path $work 'stage'
$backupBase = Join-Path $env:USERPROFILE 'Documents\NP_Notes_Code_Backups'
$backup = Join-Path $backupBase ('Code_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + $CommitSha.Substring(0,12))
$rollbackInRoot = Join-Path $root ('.np-notes-rollback-' + [guid]::NewGuid().ToString('N'))
$changed = $false
$entryMoved = $false
$packageMoved = $false
New-Item -ItemType Directory -Path $work | Out-Null
try {
    Invoke-WebRequest -Uri "https://github.com/Nikita-Postnov/CODE/archive/$CommitSha.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath $unpacked
    $tree = Get-ChildItem -LiteralPath $unpacked -Directory | Select-Object -First 1
    if (-not $tree) { throw 'Candidate zip missing repository root' }
    $source = Join-Path $tree.FullName 'Other_dev'
    Assert-File (Join-Path $source 'notes_app.py')
    Assert-File (Join-Path $source 'noteapp\app\__init__.py')
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-OnlyCode $source $stage
    Assert-File (Join-Path $stage 'notes_app.py')
    Assert-File (Join-Path $stage 'noteapp\app\__init__.py')
    if (Test-Path -LiteralPath $backup) { throw 'Code backup already exists' }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-OnlyCode $root $backup
    Assert-File (Join-Path $backup 'notes_app.py')
    Assert-File (Join-Path $backup 'noteapp\app\__init__.py')
    Write-Output "CODE_BACKUP=$backup"

    # No automatic termination of user applications. Recheck before swap.
    $stillRunning = @(Get-CimInstance Win32_Process |
        Where-Object {
            ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
            ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        })
    if ($stillRunning.Count -gt 0) {
        throw 'NP Notes started during preparation; aborting without changing code'
    }
    New-Item -ItemType Directory -Path $rollbackInRoot | Out-Null
    try {
        Move-Item -LiteralPath $package -Destination (Join-Path $rollbackInRoot 'noteapp')
        $packageMoved = $true
        Move-Item -LiteralPath $entry -Destination (Join-Path $rollbackInRoot 'notes_app.py')
        $entryMoved = $true
        $changed = $true
        Copy-OnlyCode $stage $root
        Assert-File (Join-Path $root 'notes_app.py')
        Assert-File (Join-Path $root 'noteapp\app\__init__.py')
        # Validate code files against the staged artifact.
        $left = (Get-FileHash -LiteralPath (Join-Path $root 'notes_app.py') -Algorithm SHA256).Hash
        $right = (Get-FileHash -LiteralPath (Join-Path $stage 'notes_app.py') -Algorithm SHA256).Hash
        if ($left -ne $right) { throw 'Entry file validation failed' }
    }
    catch {
        if ($packageMoved -or $entryMoved) {
            if ($packageMoved) {
                Remove-Item -LiteralPath $package -Recurse -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'noteapp') -Destination $package
            }
            if ($entryMoved) {
                Remove-Item -LiteralPath $entry -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'notes_app.py') -Destination $entry
            }
            $changed = $false
        }
        throw
    }
    Write-Output "CODE_DEPLOYED_SHA=$CommitSha"
    Write-Output 'DATA_NOT_MODIFIED=TRUE'
}
finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ((-not $changed) -and (Test-Path -LiteralPath $rollbackInRoot)) {
        Remove-Item -LiteralPath $rollbackInRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($changed) {
        # Keep on-disk rollback even on success. Never auto-delete previous code.
        Write-Output "ROLLBACK_CODE=$rollbackInRoot"
    }
}
) {
            throw 'Unsafe release file path or digest'
        }
        $key = $relative.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { throw 'Duplicate release manifest path' }
        $seen[$key] = $true
        $path = Join-Path $RootPath ($relative.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw 'Release package missing required file'
        }
        if ((GitBlobSha $path) -cne $expected) {
            throw 'NP Notes release package checksum mismatch'
        }
    }
    if (-not $seen.ContainsKey('notes_app.py') -or
        -not $seen.ContainsKey('noteapp/__init__.py')) {
        throw 'Release manifest missing package entrypoint'
    }
}
$root = [IO.Path]::GetFullPath($LauncherRoot).TrimEnd('\')
$entry = Join-Path $root 'notes_app.py'
$package = Join-Path $root 'noteapp'
$data = Join-Path $root 'Data'
$notes = Join-Path $data 'Notes'
Assert-File $entry
Assert-File (Join-Path $package 'app\__init__.py')
if (-not (Test-Path -LiteralPath $notes -PathType Container)) {
    throw "Missing active Notes data directory: $notes"
}
$processes = @(Get-CimInstance Win32_Process |
    Where-Object {
        ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
Write-Output "NOTES_PROCESSES=$($processes.Count)"
Write-Output "DATA_PATH=$data"
Write-Output "DEPLOY_SCOPE=notes_app.py,noteapp"
if (-not $Apply) {
    Write-Output 'DEPLOY_MODE=DRY_RUN'
    return
}
if ($processes.Count -gt 0) {
    throw 'NP Notes is still running; close all Notes processes before installation'
}
if ($CommitSha -notmatch '^[0-9a-f]{40}$') {
    throw 'An immutable 40-character commit SHA is mandatory for Apply'
}

# Fetch source into a scratch folder outside the shared launcher/Data.
$work = Join-Path $env:TEMP ('np-notes-code-release-' + [guid]::NewGuid().ToString('N'))
$zip = Join-Path $work 'source.zip'
$unpacked = Join-Path $work 'unzipped'
$stage = Join-Path $work 'stage'
$backupBase = Join-Path $env:USERPROFILE 'Documents\NP_Notes_Code_Backups'
$backup = Join-Path $backupBase ('Code_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + $CommitSha.Substring(0,12))
$rollbackInRoot = Join-Path $root ('.np-notes-rollback-' + [guid]::NewGuid().ToString('N'))
$changed = $false
$entryMoved = $false
$packageMoved = $false
New-Item -ItemType Directory -Path $work | Out-Null
try {
    Invoke-WebRequest -Uri "https://github.com/Nikita-Postnov/CODE/archive/$CommitSha.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath $unpacked
    $tree = Get-ChildItem -LiteralPath $unpacked -Directory | Select-Object -First 1
    if (-not $tree) { throw 'Candidate zip missing repository root' }
    $source = Join-Path $tree.FullName 'Other_dev'
    Assert-File (Join-Path $source 'notes_app.py')
    Assert-File (Join-Path $source 'noteapp\app\__init__.py')
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-OnlyCode $source $stage
    Assert-File (Join-Path $stage 'notes_app.py')
    Assert-File (Join-Path $stage 'noteapp\app\__init__.py')
    if (Test-Path -LiteralPath $backup) { throw 'Code backup already exists' }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-OnlyCode $root $backup
    Assert-File (Join-Path $backup 'notes_app.py')
    Assert-File (Join-Path $backup 'noteapp\app\__init__.py')
    Write-Output "CODE_BACKUP=$backup"

    # No automatic termination of user applications. Recheck before swap.
    $stillRunning = @(Get-CimInstance Win32_Process |
        Where-Object {
            ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
            ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        })
    if ($stillRunning.Count -gt 0) {
        throw 'NP Notes started during preparation; aborting without changing code'
    }
    New-Item -ItemType Directory -Path $rollbackInRoot | Out-Null
    try {
        Move-Item -LiteralPath $package -Destination (Join-Path $rollbackInRoot 'noteapp')
        $packageMoved = $true
        Move-Item -LiteralPath $entry -Destination (Join-Path $rollbackInRoot 'notes_app.py')
        $entryMoved = $true
        $changed = $true
        Copy-OnlyCode $stage $root
        Assert-File (Join-Path $root 'notes_app.py')
        Assert-File (Join-Path $root 'noteapp\app\__init__.py')
        # Validate code files against the staged artifact.
        $left = (Get-FileHash -LiteralPath (Join-Path $root 'notes_app.py') -Algorithm SHA256).Hash
        $right = (Get-FileHash -LiteralPath (Join-Path $stage 'notes_app.py') -Algorithm SHA256).Hash
        if ($left -ne $right) { throw 'Entry file validation failed' }
    }
    catch {
        if ($packageMoved -or $entryMoved) {
            if ($packageMoved) {
                Remove-Item -LiteralPath $package -Recurse -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'noteapp') -Destination $package
            }
            if ($entryMoved) {
                Remove-Item -LiteralPath $entry -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath (Join-Path $rollbackInRoot 'notes_app.py') -Destination $entry
            }
            $changed = $false
        }
        throw
    }
    Write-Output "CODE_DEPLOYED_SHA=$CommitSha"
    Write-Output 'DATA_NOT_MODIFIED=TRUE'
}
finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ((-not $changed) -and (Test-Path -LiteralPath $rollbackInRoot)) {
        Remove-Item -LiteralPath $rollbackInRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($changed) {
        # Keep on-disk rollback even on success. Never auto-delete previous code.
        Write-Output "ROLLBACK_CODE=$rollbackInRoot"
    }
}
