[CmdletBinding()]
param(
    [switch] $ReplaceExisting,
    [string] $ExistingShortcutName = 'Pulse Capture.lnk'
)
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (-not (Test-Path -LiteralPath $desktop)) { throw 'Desktop folder not found.' }
$folder = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$launcher = Join-Path $folder 'launch-audio-test.ps1'
if (-not (Test-Path -LiteralPath $launcher)) { throw 'Test launcher missing.' }
$shell = New-Object -ComObject WScript.Shell
if ($ReplaceExisting) {
    if ($ExistingShortcutName -ne (Split-Path -Leaf $ExistingShortcutName) -or
        [IO.Path]::GetExtension($ExistingShortcutName) -ne '.lnk') {
        throw 'Provide the filename of an existing Desktop .lnk shortcut.'
    }
    $destination = Join-Path $desktop $ExistingShortcutName
    if (-not (Test-Path -LiteralPath $destination)) {
        Get-ChildItem -LiteralPath $desktop -Filter '*Capture*.lnk' |
            Select-Object -ExpandProperty Name | ForEach-Object { Write-Host "Found: $_" }
        throw "Existing shortcut was not found: $destination"
    }
    $old = $shell.CreateShortcut($destination)
    Write-Host "Previous shortcut target: $($old.TargetPath)"
    Write-Host "Previous shortcut arguments: $($old.Arguments)"
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $desktop ("Pulse Capture shortcut backup " + $stamp + '.lnk')
    Copy-Item -LiteralPath $destination -Destination $backup -ErrorAction Stop
    Write-Host "Original shortcut saved as: $backup"
} else {
    $destination = Join-Path $desktop 'Pulse Capture (Audio Sync Test).lnk'
    if (Test-Path -LiteralPath $destination) {
        throw "The audio test shortcut already exists: $destination"
    }
}
$shortcut = $shell.CreateShortcut($destination)
$hostExe = (Get-Process -Id $PID).Path
if (-not $hostExe -or -not (Test-Path -LiteralPath $hostExe)) {
    $hostExe = (Get-Command powershell.exe -ErrorAction Stop).Source
}
$shortcut.TargetPath = $hostExe
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '"'
$shortcut.WorkingDirectory = $folder
$icon = Join-Path $folder 'assets\branding\pulse.ico'
if (Test-Path -LiteralPath $icon) { $shortcut.IconLocation = $icon }
$shortcut.Description = 'Pulse Capture — Audio Sync Test (local source checkout)'
$shortcut.Save()
Write-Host "Shortcut now launches the new checkout: $destination"
Write-Host "Source folder: $folder"
