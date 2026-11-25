# Repairs only the Windows taskbar shortcut icon for Choice.
# Windows PowerShell 5.1. Dry-run by default. Does not edit Launcher/Data.
param(
    [string]$LauncherRoot = 'C:\WORK\NP\Launcher',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($LauncherRoot).TrimEnd('\')
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "Launcher root missing: $root"
}

function New-ChoiceIcon([string]$Output) {
    Add-Type -AssemblyName System.Drawing
    $bmp = New-Object System.Drawing.Bitmap(256, 256)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $font = $null
    $brush = $null
    $pen = $null
    $path = $null
    $pngStream = $null
    $file = $null
    $writer = $null
    try {
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
        $g.Clear([System.Drawing.Color]::Transparent)
        $background = [System.Drawing.Color]::FromArgb(255, 58, 22, 100)
        $accent = [System.Drawing.Color]::FromArgb(255, 177, 91, 255)
        $brush = New-Object System.Drawing.SolidBrush($background)
        $pen = New-Object System.Drawing.Pen($accent, 10)
        $g.FillEllipse($brush, 12, 12, 232, 232)
        $g.DrawEllipse($pen, 17, 17, 222, 222)
        $brush.Dispose()
        $brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
        $font = [System.Drawing.Font]::new('Segoe UI', [single]142, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
        $layout = [System.Drawing.RectangleF]::new(20, 18, 220, 225)
        $format = New-Object System.Drawing.StringFormat
        try {
            $format.Alignment = [System.Drawing.StringAlignment]::Center
            $format.LineAlignment = [System.Drawing.StringAlignment]::Center
            $g.DrawString('C', $font, $brush, $layout, $format)
        }
        finally { $format.Dispose() }
        $pngStream = New-Object System.IO.MemoryStream
        $bmp.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)
        $bytes = $pngStream.ToArray()
        $file = New-Object System.IO.FileStream($Output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
        $writer = New-Object System.IO.BinaryWriter($file)
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]1)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$bytes.Length)
        $writer.Write([uint32]22)
        $writer.Write($bytes)
    }
    finally {
        if ($writer) { $writer.Dispose() }
        elseif ($file) { $file.Dispose() }
        if ($pngStream) { $pngStream.Dispose() }
        if ($font) { $font.Dispose() }
        if ($brush) { $brush.Dispose() }
        if ($pen) { $pen.Dispose() }
        if ($g) { $g.Dispose() }
        if ($bmp) { $bmp.Dispose() }
    }
}

$taskbar = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
$links = @()
if (Test-Path -LiteralPath $taskbar -PathType Container) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($path in (Get-ChildItem -LiteralPath $taskbar -Filter '*.lnk' -File)) {
        $link = $shell.CreateShortcut($path.FullName)
        $target = "$($link.TargetPath) $($link.Arguments)"
        # Never touch other Python cards or launcher shortcuts.
        if ($path.BaseName -match '^(?i:Choice)(?:\s|$)' -and
            $target.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $links += [pscustomobject]@{ Path=$path.FullName; Shortcut=$link; Target=$target }
        }
    }
}
Write-Output "CHOICE_SHORTCUTS=$($links.Count)"
foreach ($match in $links) {
    Write-Output "SHORTCUT=$($match.Path)"
    Write-Output "TARGET=$($match.Target)"
    Write-Output "ICON_BEFORE=$($match.Shortcut.IconLocation)"
}

$icons = @(
    (Join-Path $root 'choice.ico'),
    (Join-Path $root 'Choice.ico'),
    (Join-Path $root 'Data\choice.ico')
)
$existing = $icons | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$icon = if ($existing) { [string]$existing } else { Join-Path $root 'Choice_Taskbar.ico' }
Write-Output "ICON_PATH=$icon"
if (-not $Apply) {
    Write-Output 'MODE=DRY_RUN'
    return
}
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    New-ChoiceIcon $icon
}
if ($links.Count -eq 0) {
    Write-Output 'STATUS=ICON_READY_NO_MATCHING_PINNED_SHORTCUT'
    Write-Output 'ACTION=Unpin existing Choice taskbar icon, then pin the Choice app again'
    return
}
$backupDir = Join-Path $env:USERPROFILE ('Documents\Choice_Taskbar_Backup_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
foreach ($match in $links) {
    Copy-Item -LiteralPath $match.Path -Destination (Join-Path $backupDir ([IO.Path]::GetFileName($match.Path))) -ErrorAction Stop
    $match.Shortcut.IconLocation = "$icon,0"
    $match.Shortcut.Save()
}
Write-Output "SHORTCUT_BACKUP=$backupDir"
Write-Output "UPDATED_SHORTCUTS=$($links.Count)"
Write-Output 'STATUS=ICON_ASSIGNED'
Write-Output 'NOTE=Windows may require unpinning and repinning Choice to refresh the taskbar cache'
