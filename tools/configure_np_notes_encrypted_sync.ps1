# Configure NP Notes sync without printing, logging, or storing plaintext tokens.
# Windows PowerShell 5.1. Encrypts the complete configuration for CurrentUser
# using Windows DPAPI. Never touches or uploads actual note contents.
param(
    [string]$LauncherRoot = 'C:\WORK\NP\Launcher',
    [string]$Owner = 'Nikita-Postnov',
    [string]$Repository = 'NP-Notes-Sync',
    [switch]$Replace
)
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 does not automatically load the System.Security assembly.
Add-Type -AssemblyName System.Security -ErrorAction Stop
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-SensitiveText([string]$Prompt) {
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $ptr = [IntPtr]::Zero
    try {
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        if ($ptr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
        $secure.Dispose()
    }
}

$root = [IO.Path]::GetFullPath($LauncherRoot)
$notes = Join-Path $root 'Data\Notes'
$state = Join-Path $root 'Data\NPNotesSync'
$path = Join-Path $state 'credentials.dpapi'

if (-not (Test-Path -LiteralPath $notes -PathType Container)) {
    throw 'NP Notes local Data\Notes folder is missing'
}
if ((Test-Path -LiteralPath $path) -and -not $Replace) {
    throw 'Encrypted configuration already exists. Use -Replace only for intentional credential rotation'
}
if ($Owner -notmatch '^[\w.-]{1,100}$' -or $Repository -notmatch '^[\w.-]{1,100}$') {
    throw 'Invalid repository name'
}

Write-Host 'Private GitHub repository:' $Owner/$Repository
Write-Host 'The token and encryption passphrase will not be displayed or sent to chat.'
$token = Get-SensitiveText 'GitHub fine-grained token (repository Contents Read/Write)'
$passphrase = Get-SensitiveText 'Shared encryption passphrase (at least 16 characters)'
try {
    if ([string]::IsNullOrWhiteSpace($token) -or $passphrase.Length -lt 16) {
        throw 'Missing token or passphrase shorter than 16 characters'
    }
    # Validate token against the expected private repository without notes access.
    $headers = @{
        Authorization = ('Bearer ' + $token)
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
        'User-Agent' = 'NP-Notes-Sync-Setup'
    }
    $uri = 'https://api.github.com/repos/' + $Owner + '/' + $Repository
    $metadata = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 15
    if ($metadata.private -ne $true -or $metadata.full_name -ne "$Owner/$Repository") {
        throw 'Private repository verification failed'
    }

    $settings = @{
        owner = $Owner
        repository = $Repository
        branch = 'main'
        token = $token
        passphrase = $passphrase
    }
    $json = ConvertTo-Json -InputObject $settings -Compress
    $raw = [Text.Encoding]::UTF8.GetBytes($json)
    $encrypted = [Security.Cryptography.ProtectedData]::Protect(
        $raw, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    New-Item -ItemType Directory -Path $state -Force | Out-Null
    $temporary = Join-Path $state ('.credentials-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllBytes($temporary, $encrypted)
        if ((Test-Path -LiteralPath $path) -and -not $Replace) {
            throw 'A configuration was created concurrently'
        }
        Move-Item -LiteralPath $temporary -Destination $path -Force
    }
    finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
    Write-Host 'CONFIG_STATUS=ENCRYPTED_WITH_WINDOWS_DPAPI'
    Write-Host 'REPOSITORY_PRIVATE=TRUE'
    Write-Host 'NOTES_DATA_MODIFIED=FALSE'
}
finally {
    $token = $null
    $passphrase = $null
    $json = $null
    $raw = $null
}
