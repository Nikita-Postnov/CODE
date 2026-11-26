# Install NP Punto Browser's local Windows native messaging bridge.
# Source: PuntoLayoutHost.cs in the same folder. No downloaded or unsigned binaries.
# First run without -Apply performs read-only planning. -CompileOnly builds in TEMP.
[CmdletBinding()]
param(
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId = '',
    [ValidateSet('Chrome','Edge','Both')]
    [string]$Browser = 'Both',
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'NP_Punto_Browser_Bridge'),
    [switch]$Apply,
    [switch]$CompileOnly
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'PuntoLayoutHost.cs'
$exe = Join-Path $InstallRoot 'PuntoLayoutHost.exe'
$manifest = Join-Path $InstallRoot 'com.npcore.punto_layout.json'
$nativeName = 'com.npcore.punto_layout'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "C# source not found next to installer: $source"
}
if ($Apply -and $CompileOnly) { throw '-Apply and -CompileOnly are mutually exclusive' }
if (($Apply -or -not $CompileOnly) -and $ExtensionId -notmatch '^[a-p]{32}$') {
    throw 'ExtensionId is required. Copy ID from NP Punto Browser extension options.'
}
if ($InstallRoot -notlike '*NP_Punto_Browser_Bridge*') {
    throw 'For safety, the installation directory must contain NP_Punto_Browser_Bridge.'
}

$compiler = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw 'Windows .NET Framework 4 C# compiler not found' }

$keys = @()
if ($Browser -eq 'Chrome' -or $Browser -eq 'Both') {
    $keys += 'Registry::HKEY_CURRENT_USER\Software\Google\Chrome\NativeMessagingHosts\' + $nativeName
}
if ($Browser -eq 'Edge' -or $Browser -eq 'Both') {
    $keys += 'Registry::HKEY_CURRENT_USER\Software\Microsoft\Edge\NativeMessagingHosts\' + $nativeName
}
Write-Host "BRIDGE_SOURCE=$source"
Write-Host "INSTALL_ROOT=$InstallRoot"
Write-Host "BROWSER=$Browser"
if ($ExtensionId) { Write-Host "EXTENSION_ID=$ExtensionId" }
if (-not $Apply -and -not $CompileOnly) {
    foreach ($key in $keys) { Write-Host "REGISTRY_WILL_REGISTER=$key" }
    Write-Host 'BRIDGE_ACTION=READ_ONLY'
    exit 0
}

$temp = Join-Path $env:TEMP ("npcore-native-bridge-" + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $temp -Force
try {
    $tempExe = Join-Path $temp 'PuntoLayoutHost.exe'
    $compilerOutput = & $compiler /nologo /target:exe /reference:System.Web.Extensions.dll "/out:$tempExe" $source 2>&1
    if ($LASTEXITCODE -ne 0) {
        $compilerOutput | ForEach-Object { Write-Host $_ }
        throw 'C# native bridge compilation failed'
    }
    if (-not (Test-Path -LiteralPath $tempExe -PathType Leaf)) {
        throw 'Compiler produced no executable'
    }
    & $tempExe --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Native bridge self test failed' }
    Write-Host 'NATIVE_COMPILATION_PASS=TRUE'
    if ($CompileOnly) { Write-Host 'BRIDGE_ACTION=COMPILE_ONLY'; exit 0 }

    foreach ($key in $keys) {
        if (Test-Path -LiteralPath $key) {
            $present = (Get-Item -LiteralPath $key).GetValue('')
            if ($present -and $present -ne $manifest) {
                throw "A different bridge is already registered at: $key"
            }
        }
    }
    if (Test-Path -LiteralPath $manifest -PathType Leaf) {
        $existing = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
        if (@($existing.allowed_origins) -notcontains "chrome-extension://$ExtensionId/") {
            throw 'Existing bridge belongs to another extension ID; installation cancelled.'
        }
    }

    $null = New-Item -ItemType Directory -Path $InstallRoot -Force
    $backup = Join-Path $InstallRoot ('backup-' + (Get-Date -Format yyyyMMdd-HHmmss))
    $null = New-Item -ItemType Directory -Path $backup -Force
    foreach ($path in @($exe,$manifest)) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Copy-Item -LiteralPath $path -Destination $backup -Force
        }
    }
    Copy-Item -LiteralPath $tempExe -Destination $exe -Force
    $hostManifest = @{
        name = $nativeName
        description = 'NP Punto: Windows input language switch'
        path = $exe
        type = 'stdio'
        allowed_origins = @("chrome-extension://$ExtensionId/")
    } | ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText($manifest,$hostManifest,$utf8NoBom)
    $changed = @()
    try {
        foreach ($key in $keys) {
            if (-not (Test-Path -LiteralPath $key)) {
                New-Item -Path $key -Force | Out-Null
            }
            Set-Item -LiteralPath $key -Value $manifest
            $changed += $key
        }
        foreach ($key in $keys) {
            if ((Get-Item -LiteralPath $key).GetValue('') -ne $manifest) {
                throw "Registry verification failed: $key"
            }
        }
        & $exe --self-test
        if ($LASTEXITCODE -ne 0) { throw 'Installed bridge self test failed' }
    } catch {
        foreach ($key in $changed) {
            Remove-Item -LiteralPath $key -Recurse -Force -ErrorAction SilentlyContinue
        }
        foreach ($path in @($exe,$manifest)) {
            $previous = Join-Path $backup (Split-Path -Leaf $path)
            if (Test-Path -LiteralPath $previous -PathType Leaf) {
                Copy-Item -LiteralPath $previous -Destination $path -Force
            } else {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            }
        }
        throw
    }
    Write-Host 'NATIVE_BRIDGE_INSTALLED=TRUE'
    Write-Host 'TYPED_TEXT_TRANSMISSION=FALSE'
    Write-Host "BACKUP_LOCATION=$backup"
    Write-Host 'NEXT=Reload NP Punto Browser extension and test the Windows connection in options'
}
finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
