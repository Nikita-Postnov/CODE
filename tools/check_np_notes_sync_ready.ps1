# NP Notes cloud sync readiness check. Read-only; never loads note contents or secrets.
# PowerShell 5.1; does not activate synchronization.
param([string]$LauncherRoot = 'C:\WORK\NP\Launcher')
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($LauncherRoot)
$entry = Join-Path $root 'notes_app.py'
$module = Join-Path $root 'noteapp\sync_service.py'
$state = Join-Path $root 'Data\NPNotesSync'
$credentials = Join-Path $state 'credentials.dpapi'
$runtime = Join-Path $root 'Runtime\python.exe'
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw 'NP Notes entrypoint not found'
}
if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) {
    throw 'NP Notes portable Python not found'
}
if (-not (Test-Path -LiteralPath $credentials -PathType Leaf)) {
    throw 'Protected credentials missing'
}
if ((Get-Item -LiteralPath $credentials).Length -le 0) {
    throw 'Protected credentials file is empty'
}
if (-not (Test-Path -LiteralPath $module -PathType Leaf)) {
    Write-Output 'SYNC_CODE_INSTALLED=FALSE'
}
else {
    Write-Output 'SYNC_CODE_INSTALLED=TRUE'
}
& $runtime -c 'import cryptography; print("CRYPTOGRAPHY_AVAILABLE=TRUE")'
if ($LASTEXITCODE -ne 0) {
    throw 'cryptography module unavailable'
}
Write-Output 'PROTECTED_CREDENTIAL_FILE_PRESENT=TRUE'
Write-Output 'REAL_NOTES_READ=FALSE'
Write-Output 'SYNC_ACTIVATED_BY_THIS_CHECK=FALSE'
