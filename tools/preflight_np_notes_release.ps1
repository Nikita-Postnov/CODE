# Read-only NP Notes release preflight for Windows PowerShell 5.1.
# Does not fetch, install, stop processes, or change Launcher/Data.
param([string]$LauncherRoot = 'C:\WORK\NP\Launcher')
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($LauncherRoot).TrimEnd('\')
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "Launcher root does not exist: $root"
}
$data = Join-Path $root 'Data'
$script = Join-Path $root 'notes_app.py'
$package = Join-Path $root 'noteapp'
$notes = Join-Path $data 'Notes'
$runtime = Join-Path $root 'Runtime'
$choiceConfig = Join-Path $root 'launcher_config.json'
if (-not (Test-Path -LiteralPath $choiceConfig -PathType Leaf)) {
    $alternative = Join-Path $data 'launcher_config.json'
    if (Test-Path -LiteralPath $alternative -PathType Leaf) {
        $choiceConfig = $alternative
    }
}
$repo = 'Nikita-Postnov/CODE'
Write-Output "LAUNCHER_ROOT=$root"
Write-Output "CHOICE_CONFIG_PRESENT=$(Test-Path -LiteralPath $choiceConfig -PathType Leaf)"
Write-Output "RUNTIME_PRESENT=$(Test-Path -LiteralPath $runtime -PathType Container)"
Write-Output "NOTES_ENTRY_PRESENT=$(Test-Path -LiteralPath $script -PathType Leaf)"
Write-Output "NOTES_PACKAGE_PRESENT=$(Test-Path -LiteralPath (Join-Path $package 'app\__init__.py') -PathType Leaf)"
Write-Output "NOTES_DATA_PRESENT=$(Test-Path -LiteralPath $notes -PathType Container)"
# This path is deliberately inspected rather than guessed from Choice settings.
if (Test-Path -LiteralPath $choiceConfig -PathType Leaf) {
    $json = Get-Content -LiteralPath $choiceConfig -Raw
    $lines = $json -split '\r?\n'
    $references = @($lines | Where-Object { $_ -match '(?i)(notes_app|np_notes|noteapp)' })
    Write-Output "CHOICE_NOTES_REFERENCES=$($references.Count)"
}
$processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.Name -match '^(?i:NP_Notes)\.exe$') -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($script, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
Write-Output "NOTES_PROCESSES=$($processes.Count)"
foreach ($process in $processes) {
    $exe = if ($process.ExecutablePath) { $process.ExecutablePath } else { '(unknown)' }
    Write-Output "NOTES_PROCESS_PID=$($process.ProcessId);NAME=$($process.Name);EXE=$exe"
}
Write-Output 'PROCESSES_NOT_TERMINATED=TRUE'
Write-Output "DATA_NOT_MODIFIED=TRUE"
if (-not (Test-Path -LiteralPath $notes -PathType Container)) {
    throw 'Unable to identify the actual Notes data tree'
}
if (-not (Test-Path -LiteralPath $script -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $package 'app\__init__.py') -PathType Leaf)) {
    Write-Output 'RELEASE_STATUS=INSTALL_LAYOUT_UNCONFIRMED'
}
elseif ($processes.Count -gt 0) {
    Write-Output 'RELEASE_STATUS=STOP_NOTES_BEFORE_INSTALL'
}
else {
    Write-Output 'RELEASE_STATUS=LAYOUT_CONFIRMED_NOT_INSTALLED'
}
