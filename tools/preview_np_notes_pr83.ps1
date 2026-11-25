# Isolated NP Notes preview. Windows PowerShell 5.1+.
# Download and unpack candidate code only; production Launcher\Data stays untouched.
param(
    [string]$LauncherRoot = 'C:\WORK\NP\Launcher',
    [string]$CommitSha = '',
    [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$repo = 'Nikita-Postnov/CODE'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $CommitSha) {
    $head = Invoke-RestMethod -Uri 'https://api.github.com/repos/Nikita-Postnov/CODE/branches/feat/noteapp-safe-improvements-20261125' -Headers @{ 'User-Agent' = 'NP-Notes-Preview' }
    $CommitSha = [string]$head.commit.sha
}
if ($CommitSha -notmatch '^[0-9a-f]{40}$') {
    throw 'Invalid commit SHA'
}
$commit = $CommitSha
$launcher = [IO.Path]::GetFullPath($LauncherRoot).TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $launcher 'Choice.pyw'))) {
    throw "Choice.pyw not found in launcher root: $launcher"
}

$preview = Join-Path $env:TEMP ("NP_Notes_PR83_" + $commit.Substring(0,12))
if ([IO.Path]::GetFullPath($preview).TrimEnd('\').Equals($launcher, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Preview destination cannot equal the production launcher'
}
function Start-IsolatedPreview([string]$Root) {
    $python = @(
        (Join-Path $launcher 'Runtime\pythonw.exe'),
        (Join-Path $launcher 'Runtime\python.exe')
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $python) {
        throw 'No portable Python runtime found in Launcher\Runtime'
    }
    $previousLauncherRoot = $env:LAUNCHER_ROOT
    try {
        $env:LAUNCHER_ROOT = $Root
        Start-Process -FilePath $python -ArgumentList ('"' + (Join-Path $Root 'notes_app.py') + '"') -WorkingDirectory $Root
    }
    finally {
        if ($null -eq $previousLauncherRoot) {
            Remove-Item Env:\LAUNCHER_ROOT -ErrorAction SilentlyContinue
        }
        else {
            $env:LAUNCHER_ROOT = $previousLauncherRoot
        }
    }
    Write-Host 'PREVIEW_REOPENED_WITH_EXISTING_DATA'
}

if (Test-Path -LiteralPath $preview) {
    # Reopen the exact same SHA and isolated Data. Never overwrite data/code.
    $marker = Join-Path $preview 'PREVIEW_ONLY.txt'
    $data = Join-Path $preview 'Data'
    $scriptFile = Join-Path $preview 'notes_app.py'
    $packageFile = Join-Path $preview 'noteapp\app\__init__.py'
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf) -or
        -not (Test-Path -LiteralPath $data -PathType Container) -or
        -not (Test-Path -LiteralPath $scriptFile -PathType Leaf) -or
        -not (Test-Path -LiteralPath $packageFile -PathType Leaf)) {
        throw "Existing preview has an unexpected structure; refusing to change it: $preview"
    }
    $identity = Get-Content -LiteralPath $marker -Raw
    if (-not $identity.Contains("NP Notes isolated preview of $commit")) {
        throw "Existing preview belongs to another revision; refusing to change it: $preview"
    }
    Write-Host "PREVIEW_REUSED=$preview"
    Write-Host "ISOLATED_DATA=$data"
    if ($Launch) {
        Start-IsolatedPreview $preview
    }
    return
}

$work = Join-Path $env:TEMP ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $zip = Join-Path $work 'code.zip'
    $url = "https://github.com/$repo/archive/$commit.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $work 'extracted')
    $project = Get-ChildItem (Join-Path $work 'extracted') |
        Where-Object { $_.PSIsContainer } | Select-Object -First 1
    if (-not $project) { throw 'GitHub archive missing project root' }
    $source = Join-Path $project.FullName 'Other_dev'
    if (-not (Test-Path -LiteralPath (Join-Path $source 'notes_app.py'))) {
        throw 'Missing notes_app.py'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'noteapp\app\__init__.py'))) {
        throw 'Missing noteapp package'
    }

    New-Item -ItemType Directory -Path $preview | Out-Null
    Copy-Item -LiteralPath (Join-Path $source 'notes_app.py') -Destination (Join-Path $preview 'notes_app.py')
    Copy-Item -LiteralPath (Join-Path $source 'noteapp') -Destination (Join-Path $preview 'noteapp') -Recurse
    # A sentinel and the environment override keep noteapp.config inside preview.
    New-Item -ItemType File -Path (Join-Path $preview 'Choice.pyw') | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $preview 'Data') | Out-Null
    Set-Content -LiteralPath (Join-Path $preview 'PREVIEW_ONLY.txt') -Encoding UTF8 -Value @(
        "NP Notes isolated preview of $commit",
        "Production Launcher: $launcher",
        "Candidate: $preview",
        "Only the test Data folder inside Candidate may be modified."
    )
    Write-Host "PREVIEW_READY=$preview"
    Write-Host "ISOLATED_DATA=$(Join-Path $preview 'Data')"

    if ($Launch) {
        Start-IsolatedPreview $preview
    }
}
finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force
    }
}
