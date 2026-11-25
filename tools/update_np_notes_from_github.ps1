# Safe NP Notes version checking/updating; Windows PowerShell 5.1.
# By default read-only. -Apply backs up Notes and installs the complete package.
param(
    [string]$LauncherRoot = 'C:\WORK\NP\Launcher',
    [switch]$Apply,
    [string]$ExpectedReleaseCommit = ''
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = [IO.Path]::GetFullPath($LauncherRoot).TrimEnd('\')
$python = Join-Path $root 'Runtime\python.exe'
$entry = Join-Path $root 'notes_app.py'
$notes = Join-Path $root 'Data\Notes'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Portable NP Notes Python not found' }
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw 'NP Notes entrypoint missing' }
if (-not (Test-Path -LiteralPath $notes -PathType Container)) { throw 'NP Notes data folder missing' }
$work = Join-Path $env:TEMP ('NPNotesRelease_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work -Force | Out-Null
try {
    # raw.githubusercontent.com/main is mutable and can be stale behind
    # a CDN, corporate proxy or browser cache. Resolve the current GitHub
    # commit through the API with a unique query, then load ALL helpers and
    # the manifest from the same immutable commit.
    if ($ExpectedReleaseCommit -and $ExpectedReleaseCommit -cnotmatch '^[0-9a-f]{40}    $checker = Join-Path $work 'check_np_notes_release.py'
    $output = @(& $python $checker --launcher-root $root --manifest $manifestPath)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot safely check NP Notes version' }
    $output | ForEach-Object { Write-Output $_ }
    $status = @($output | Where-Object { $_ -eq 'NP_NOTES_VERSION=UP_TO_DATE' })
    if ($status.Count -gt 0) {
        Write-Output 'NP_NOTES_RELEASE_ACTION=NONE_ALREADY_CURRENT'
        return
    }
    if (-not $Apply) {
        Write-Output 'NP_NOTES_RELEASE_ACTION=UPDATE_AVAILABLE_USE_APPLY'
        return
    }
    $running = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -ieq 'NP_Notes.exe' -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
    if ($running.Count -gt 0) { throw 'Close NP Notes completely, including tray, before updating' }
    $backupDir = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('NP_Notes_Data_Backups\Before_GitHub_Code_Update_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Split-Path -Parent $backupDir) -Force | Out-Null
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $work 'backup_np_notes_data.ps1') -SourceRoot (Join-Path $root 'Data') -BackupRoot $backupDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $backupDir 'SHA256-manifest.json') -PathType Leaf)) {
        throw 'Verified NP Notes backup failed; refusing update'
    }
    Write-Output "NP_NOTES_BACKUP_VERIFIED=$backupDir"
    # The shared Data backup script intentionally excludes NPNotesSync. Preserve
    # encrypted credentials, durable queues and deletion tombstones separately,
    # next to the verified Notes backup. Never copy another Choice app's files.
    $syncState = Join-Path $root 'Data\NPNotesSync'
    if (Test-Path -LiteralPath $syncState) {
        $stateEntry = Get-Item -LiteralPath $syncState -Force
        if (-not $stateEntry.PSIsContainer -or
            (($stateEntry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw 'NP Notes sync state path is unsafe; refusing update'
        }
        $stateBackup = Join-Path $backupDir 'NPNotesSync'
        if (Test-Path -LiteralPath $stateBackup) {
            throw 'NP Notes sync state backup already exists'
        }
        New-Item -ItemType Directory -Path $stateBackup -Force | Out-Null
        $stateFiles = @(
            Get-ChildItem -LiteralPath $syncState -Recurse -Force -File -ErrorAction Stop
        )
        $stateEntries = @(
            Get-ChildItem -LiteralPath $syncState -Recurse -Force -ErrorAction Stop
        )
        foreach ($item in $stateEntries) {
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Unsafe link/junction found in NP Notes sync state'
            }
        }
        $syncManifest = [System.Collections.Generic.List[object]]::new()
        foreach ($item in $stateEntries) {
            $relative = $item.FullName.Substring($syncState.Length).TrimStart('\')
            $target = Join-Path $stateBackup $relative
            if ($item.PSIsContainer) {
                New-Item -ItemType Directory -Path $target -Force | Out-Null
            }
            else {
                $parent = Split-Path -Parent $target
                if (-not (Test-Path -LiteralPath $parent)) {
                    New-Item -ItemType Directory -Path $parent -Force | Out-Null
                }
                $hashBefore = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
                Copy-Item -LiteralPath $item.FullName -Destination $target -ErrorAction Stop
                $hashAfter = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
                $hashSourceAfter = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
                if ($hashBefore -ne $hashAfter -or $hashBefore -ne $hashSourceAfter) {
                    throw 'NP Notes sync state changed during backup'
                }
                $syncManifest.Add([pscustomobject]@{RelativePath=$relative;SHA256=$hashBefore})
            }
        }
        $manifestNames = @($syncManifest | ForEach-Object { $_.RelativePath })
        $latestNames = @(
            Get-ChildItem -LiteralPath $syncState -Recurse -Force -File |
                ForEach-Object { $_.FullName.Substring($syncState.Length).TrimStart('\') }
        )
        if ((Compare-Object -ReferenceObject $manifestNames -DifferenceObject $latestNames |
            Measure-Object).Count -ne 0) {
            throw 'NP Notes sync state changed during backup enumeration'
        }
        ConvertTo-Json -InputObject @($syncManifest.ToArray()) -Depth 3 |
            Set-Content -LiteralPath (Join-Path $stateBackup 'SHA256-manifest.json') -Encoding UTF8
        Write-Output "NP_NOTES_SYNC_STATE_BACKUP_VERIFIED=$($syncManifest.Count)"
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $work 'install_np_notes_code.ps1') -LauncherRoot $root -CommitSha $manifest.source_commit -Apply
    if ($LASTEXITCODE -ne 0) { throw 'NP Notes code installation failed; code rollback is preserved' }
    $result = @(& $python $checker --launcher-root $root --manifest $manifestPath)
    if ($LASTEXITCODE -ne 0 -or @($result | Where-Object { $_ -eq 'NP_NOTES_VERSION=UP_TO_DATE' }).Count -ne 1) {
        throw 'Release verification failed after install; preserve rollback and inspect'
    }
    $result | ForEach-Object { Write-Output $_ }
    Write-Output 'NP_NOTES_RELEASE_ACTION=UPDATED_AND_VERIFIED'
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
) {
        throw 'Expected release commit must be a full 40-character SHA'
    }
    $nonce = [guid]::NewGuid().ToString('N')
    $apiHeaders = @{
        'User-Agent' = 'NPNotes-ReleaseUpdater/2.0'
        'Accept' = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
        'Cache-Control' = 'no-cache'
        'Pragma' = 'no-cache'
    }
    $branchInfo = Invoke-RestMethod -Uri (
        "https://api.github.com/repos/Nikita-Postnov/CODE/branches/main?nonce=$nonce"
    ) -Headers $apiHeaders -UseBasicParsing -ErrorAction Stop
    $mainSha = [string]$branchInfo.commit.sha
    if ($mainSha -cnotmatch '^[0-9a-f]{40}    $checker = Join-Path $work 'check_np_notes_release.py'
    $output = @(& $python $checker --launcher-root $root --manifest $manifestPath)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot safely check NP Notes version' }
    $output | ForEach-Object { Write-Output $_ }
    $status = @($output | Where-Object { $_ -eq 'NP_NOTES_VERSION=UP_TO_DATE' })
    if ($status.Count -gt 0) {
        Write-Output 'NP_NOTES_RELEASE_ACTION=NONE_ALREADY_CURRENT'
        return
    }
    if (-not $Apply) {
        Write-Output 'NP_NOTES_RELEASE_ACTION=UPDATE_AVAILABLE_USE_APPLY'
        return
    }
    $running = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -ieq 'NP_Notes.exe' -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
    if ($running.Count -gt 0) { throw 'Close NP Notes completely, including tray, before updating' }
    $backupDir = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('NP_Notes_Data_Backups\Before_GitHub_Code_Update_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Split-Path -Parent $backupDir) -Force | Out-Null
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $work 'backup_np_notes_data.ps1') -SourceRoot (Join-Path $root 'Data') -BackupRoot $backupDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $backupDir 'SHA256-manifest.json') -PathType Leaf)) {
        throw 'Verified NP Notes backup failed; refusing update'
    }
    Write-Output "NP_NOTES_BACKUP_VERIFIED=$backupDir"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $work 'install_np_notes_code.ps1') -LauncherRoot $root -CommitSha $manifest.source_commit -Apply
    if ($LASTEXITCODE -ne 0) { throw 'NP Notes code installation failed; code rollback is preserved' }
    $result = @(& $python $checker --launcher-root $root --manifest $manifestPath)
    if ($LASTEXITCODE -ne 0 -or @($result | Where-Object { $_ -eq 'NP_NOTES_VERSION=UP_TO_DATE' }).Count -ne 1) {
        throw 'Release verification failed after install; preserve rollback and inspect'
    }
    $result | ForEach-Object { Write-Output $_ }
    Write-Output 'NP_NOTES_RELEASE_ACTION=UPDATED_AND_VERIFIED'
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
) {
        throw 'Cannot verify immutable GitHub main SHA'
    }
    $source = "https://raw.githubusercontent.com/Nikita-Postnov/CODE/$mainSha/tools"
    foreach ($name in @('np_notes_release.json', 'check_np_notes_release.py', 'install_np_notes_code.ps1', 'backup_np_notes_data.ps1')) {
        $target = Join-Path $work $name
        Invoke-WebRequest -Uri "$source/$name?nonce=$nonce" -OutFile $target -UseBasicParsing -Headers @{ 'Cache-Control'='no-cache'; 'Pragma'='no-cache' } -ErrorAction Stop
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
            throw "Missing immutable updater resource: $name"
        }
    }
    $manifestPath = Join-Path $work 'np_notes_release.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.source_repository -ne 'Nikita-Postnov/CODE' -or $manifest.source_directory -ne 'Other_dev' -or [string]$manifest.source_commit -cnotmatch '^[0-9a-f]{40}    $checker = Join-Path $work 'check_np_notes_release.py'
    $output = @(& $python $checker --launcher-root $root --manifest $manifestPath)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot safely check NP Notes version' }
    $output | ForEach-Object { Write-Output $_ }
    $status = @($output | Where-Object { $_ -eq 'NP_NOTES_VERSION=UP_TO_DATE' })
    if ($status.Count -gt 0) {
        Write-Output 'NP_NOTES_RELEASE_ACTION=NONE_ALREADY_CURRENT'
        return
    }
    if (-not $Apply) {
        Write-Output 'NP_NOTES_RELEASE_ACTION=UPDATE_AVAILABLE_USE_APPLY'
        return
    }
    $running = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -ieq 'NP_Notes.exe' -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
    if ($running.Count -gt 0) { throw 'Close NP Notes completely, including tray, before updating' }
    $backupDir = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('NP_Notes_Data_Backups\Before_GitHub_Code_Update_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Split-Path -Parent $backupDir) -Force | Out-Null
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $work 'backup_np_notes_data.ps1') -SourceRoot (Join-Path $root 'Data') -BackupRoot $backupDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $backupDir 'SHA256-manifest.json') -PathType Leaf)) {
        throw 'Verified NP Notes backup failed; refusing update'
    }
    Write-Output "NP_NOTES_BACKUP_VERIFIED=$backupDir"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $work 'install_np_notes_code.ps1') -LauncherRoot $root -CommitSha $manifest.source_commit -Apply
    if ($LASTEXITCODE -ne 0) { throw 'NP Notes code installation failed; code rollback is preserved' }
    $result = @(& $python $checker --launcher-root $root --manifest $manifestPath)
    if ($LASTEXITCODE -ne 0 -or @($result | Where-Object { $_ -eq 'NP_NOTES_VERSION=UP_TO_DATE' }).Count -ne 1) {
        throw 'Release verification failed after install; preserve rollback and inspect'
    }
    $result | ForEach-Object { Write-Output $_ }
    Write-Output 'NP_NOTES_RELEASE_ACTION=UPDATED_AND_VERIFIED'
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
) {
        throw 'GitHub release manifest is invalid'
    }
    Write-Output "UPDATER_MAIN_SHA=$mainSha"
    Write-Output "UPDATER_RELEASE_SHA=$($manifest.source_commit)"
    if ($ExpectedReleaseCommit -and [string]$manifest.source_commit -cne $ExpectedReleaseCommit) {
        throw "Stale or unexpected NP Notes release manifest; refusing to report UP_TO_DATE"
    }
    $checker = Join-Path $work 'check_np_notes_release.py'
    $output = @(& $python $checker --launcher-root $root --manifest $manifestPath)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot safely check NP Notes version' }
    $output | ForEach-Object { Write-Output $_ }
    $status = @($output | Where-Object { $_ -eq 'NP_NOTES_VERSION=UP_TO_DATE' })
    if ($status.Count -gt 0) {
        Write-Output 'NP_NOTES_RELEASE_ACTION=NONE_ALREADY_CURRENT'
        return
    }
    if (-not $Apply) {
        Write-Output 'NP_NOTES_RELEASE_ACTION=UPDATE_AVAILABLE_USE_APPLY'
        return
    }
    $running = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -ieq 'NP_Notes.exe' -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
    if ($running.Count -gt 0) { throw 'Close NP Notes completely, including tray, before updating' }
    $backupDir = Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('NP_Notes_Data_Backups\Before_GitHub_Code_Update_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Split-Path -Parent $backupDir) -Force | Out-Null
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $work 'backup_np_notes_data.ps1') -SourceRoot (Join-Path $root 'Data') -BackupRoot $backupDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $backupDir 'SHA256-manifest.json') -PathType Leaf)) {
        throw 'Verified NP Notes backup failed; refusing update'
    }
    Write-Output "NP_NOTES_BACKUP_VERIFIED=$backupDir"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $work 'install_np_notes_code.ps1') -LauncherRoot $root -CommitSha $manifest.source_commit -Apply
    if ($LASTEXITCODE -ne 0) { throw 'NP Notes code installation failed; code rollback is preserved' }
    $result = @(& $python $checker --launcher-root $root --manifest $manifestPath)
    if ($LASTEXITCODE -ne 0 -or @($result | Where-Object { $_ -eq 'NP_NOTES_VERSION=UP_TO_DATE' }).Count -ne 1) {
        throw 'Release verification failed after install; preserve rollback and inspect'
    }
    $result | ForEach-Object { Write-Output $_ }
    Write-Output 'NP_NOTES_RELEASE_ACTION=UPDATED_AND_VERIFIED'
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
