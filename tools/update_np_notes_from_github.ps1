# Safe NP Notes version checking/updating; Windows PowerShell 5.1.
# By default read-only. -Apply backs up Notes and installs the complete package.
param(
    [string]$LauncherRoot = 'C:\WORK\NP\Launcher',
    [switch]$Apply
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
    $source = 'https://raw.githubusercontent.com/Nikita-Postnov/CODE/main/tools'
    foreach ($name in @('np_notes_release.json', 'check_np_notes_release.py', 'install_np_notes_code.ps1', 'backup_np_notes_data.ps1')) {
        Invoke-WebRequest -Uri "$source/$name" -OutFile (Join-Path $work $name) -UseBasicParsing
    }
    $manifestPath = Join-Path $work 'np_notes_release.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.source_repository -ne 'Nikita-Postnov/CODE' -or $manifest.source_directory -ne 'Other_dev' -or [string]$manifest.source_commit -cnotmatch '^[0-9a-f]{40}$') {
        throw 'GitHub release manifest is invalid'
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
