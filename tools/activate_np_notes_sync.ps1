# Explicit, persistent NP Notes synchronization activation.
# Requires an isolated, verified backup before touching the enabled marker.
# Works with Windows PowerShell 5.1. Never displays or copies DPAPI secrets.
param(
    [string]$LauncherRoot = 'C:\WORK\NP\Launcher',
    [switch]$Disable
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($LauncherRoot).TrimEnd('\')
$state = Join-Path $root 'Data\NPNotesSync'
$marker = Join-Path $state 'sync_enabled.json'
$notes = Join-Path $root 'Data\Notes'
$python = Join-Path $root 'Runtime\python.exe'
$backupScript = Join-Path $PSScriptRoot 'backup_np_notes_data.ps1'

if ($Disable) {
    if (-not (Test-Path -LiteralPath $state -PathType Container)) {
        throw 'NP Notes sync state folder not found'
    }
    [IO.File]::WriteAllText($marker, '{"version":1,"enabled":false}', [System.Text.UTF8Encoding]::new($false))
    Write-Host 'SYNC_ENABLED=FALSE'
    Write-Host 'Restart NP Notes to stop an active worker'
    exit 0
}

foreach ($file in @(
    (Join-Path $root 'notes_app.py'),
    (Join-Path $root 'noteapp\sync_service.py'),
    (Join-Path $root 'noteapp\incoming_apply.py'),
    (Join-Path $state 'credentials.dpapi'),
    $python,
    $backupScript
)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Required file not found: $file"
    }
}
if (-not (Test-Path -LiteralPath $notes -PathType Container)) {
    throw 'Notes folder missing; activation refused'
}

# The sync flag is only safe to write with NP Notes closed.
$running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match '(?i)(^|[\\/ ])notes_app\.py' })
if ($running.Count -gt 0) {
    throw 'Close NP Notes completely (including system tray) before activation'
}
& $python -c 'import cryptography; import sys; print("CRYPTOGRAPHY_READY=TRUE")'
if ($LASTEXITCODE -ne 0) {
    throw 'Required portable cryptography dependency missing'
}
$backupRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'NP_Notes_Data_Backups'
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$backup = Join-Path $backupRoot (
    'Before_GitHub_Sync_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' +
    [guid]::NewGuid().ToString('N')
)
& $backupScript -SourceRoot (Join-Path $root 'Data') -BackupRoot $backup
if (-not (Test-Path -LiteralPath (Join-Path $backup 'SHA256-manifest.json') -PathType Leaf)) {
    throw 'Verified backup manifest not found; activation refused'
}

$payload = '{"version":1,"enabled":true}'
$temporary = Join-Path $state ('.sync_enabled-' + [guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllText($temporary, $payload, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $marker -Force
}
finally {
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
}
Write-Host "BACKUP_VERIFIED=$backup"
Write-Host 'SYNC_ENABLED=TRUE'
Write-Host 'INTERVAL_SECONDS=300'
Write-Host 'OFFLINE_SAVES_REMAIN_LOCAL=TRUE'
Write-Host 'Restart NP Notes to begin encrypted GitHub synchronization'
