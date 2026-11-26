# Exercises the Windows Native Messaging protocol without switching the keyboard.
param([Parameter(Mandatory=$true)][string]$HostExe)
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $HostExe
$origin = 'chrome-extension://abcdefghijklmnopabcdefghijklmnop/'
$manifest = Join-Path $dir 'com.npcore.punto_layout.json'
$json = @{
    name = 'com.npcore.punto_layout'
    description = 'NP Punto protocol test'
    path = $HostExe
    type = 'stdio'
    allowed_origins = @($origin)
} | ConvertTo-Json -Depth 4
[IO.File]::WriteAllText($manifest,$json,(New-Object System.Text.UTF8Encoding($false)))
function Read-NativeMessage([string]$Caller,[hashtable]$Request) {
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $HostExe
    $start.Arguments = $Caller
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $p = [System.Diagnostics.Process]::Start($start)
    try {
        $payload = [Text.Encoding]::UTF8.GetBytes(($Request | ConvertTo-Json -Compress))
        $stdin = $p.StandardInput.BaseStream
        $header = [BitConverter]::GetBytes([int]$payload.Length)
        $stdin.Write($header,0,4)
        $stdin.Write($payload,0,$payload.Length)
        $stdin.Flush()
        $stdin.Close()
        $output = $p.StandardOutput.BaseStream
        $lengthBytes = New-Object byte[] 4
        $read = 0
        while($read -lt 4) {
            $n = $output.Read($lengthBytes,$read,4-$read)
            if($n -le 0) { throw 'No native message header received' }
            $read += $n
        }
        $length = [BitConverter]::ToInt32($lengthBytes,0)
        if($length -lt 2 -or $length -gt 4096) { throw 'Invalid response length' }
        $bytes = New-Object byte[] $length
        $read = 0
        while($read -lt $length) {
            $n = $output.Read($bytes,$read,$length-$read)
            if($n -le 0) { throw 'Incomplete native response' }
            $read += $n
        }
        $p.WaitForExit(4000) | Out-Null
        return ([Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json)
    } finally {
        if(-not $p.HasExited){$p.Kill()}
        $p.Dispose()
    }
}
$ok = Read-NativeMessage -Caller $origin -Request @{action='ping'}
if($ok.status -ne 'ready'){throw "Ping failed: $($ok.status)"}
$badOrigin = Read-NativeMessage -Caller 'chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/' -Request @{action='ping'}
if($badOrigin.status -ne 'unauthorized'){throw "Wrong origin accepted: $($badOrigin.status)"}
$badAction = Read-NativeMessage -Caller $origin -Request @{action='incorrect'}
if($badAction.status -ne 'invalid'){throw 'Malformed request was accepted'}
$invalidLanguage = Read-NativeMessage -Caller $origin -Request @{action='switch';language='de'}
if($invalidLanguage.status -ne 'invalid'){throw 'Unsupported language was accepted'}
Write-Host 'NATIVE_PROTOCOL_PASS=TRUE'
Write-Host 'INPUT_LANGUAGE_UNCHANGED=TRUE'
