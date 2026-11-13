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
if ($ReplaceExisting) {
    $destination = Join-Path $desktop $ExistingShortcutName
    if (-not (Test-Path -LiteralPath $destination)) {
        throw "Existing shortcut was not found: $destination"
    }
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
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($destination)
$shortcut.TargetPath = Join-Path $PSHOME 'powershell.exe'
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '"'
$shortcut.WorkingDirectory = $folder
$icon = Join-Path $folder 'assets\branding\pulse.ico'
if (Test-Path -LiteralPath $icon) { $shortcut.IconLocation = $icon }
$shortcut.Description = 'Pulse Capture — Audio Sync Test (local source checkout)'
$shortcut.Save()
Write-Host "Shortcut now launches the new checkout: $destination"
Write-Host "Source folder: $folder"
