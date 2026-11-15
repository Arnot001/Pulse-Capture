# Pulse Capture Windows audio-sync test setup
# Run inside the clean Pulse-Capture-AudioSync-Test Git worktree.
# Never modifies the original Pulse-Capture checkout, files, or desktop shortcut.
[CmdletBinding()]
param(
    [switch] $Launch,
    [switch] $SkipTests
)

$ErrorActionPreference = 'Stop'
$checkout = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$launcher = Join-Path $checkout 'launch-audio-test.ps1'
if (-not (Test-Path -LiteralPath $launcher)) {
    throw 'This is not the Pulse Capture Audio Sync Test checkout.'
}

Push-Location $checkout
try {
    $python = (Get-Command python -ErrorAction Stop).Source

    Write-Host 'Installing optional WASAPI audio support for this Python environment...'
    & $python -m pip install -r (Join-Path $checkout 'requirements-audio.txt')
    if ($LASTEXITCODE -ne 0) { throw 'The Windows audio dependency installation failed.' }

    # Keep the -c payload free of nested quotes for Windows PowerShell 5.1.
    & $python -c 'import pyaudiowpatch'
    if ($LASTEXITCODE -ne 0) { throw 'PyAudioWPatch is not importable. Check which Python interpreter is being used.' }
    Write-Host 'WASAPI AUDIO READY'

    if (-not $SkipTests) {
        $patterns = @(
            'test_audio_sync.py',
            'test_wasapi_clock.py',
            'test_wasapi_audio.py',
            'test_wasapi_recorder.py',
            'test_editor_audio_preview.py'
        )
        foreach ($pattern in $patterns) {
            Write-Host "Running $pattern ..."
            & $python -m unittest discover -s tests -p $pattern -v
            if ($LASTEXITCODE -ne 0) {
                throw "Test failed: $pattern. The existing install/shortcut was not changed."
            }
        }
    }

    $desktop = [Environment]::GetFolderPath('DesktopDirectory')
    $shortcut = Join-Path $desktop 'Pulse Capture (Audio Sync Test).lnk'
    if (Test-Path -LiteralPath $shortcut) {
        $shell = New-Object -ComObject WScript.Shell
        $existing = $shell.CreateShortcut($shortcut)
        if ($existing.Arguments -notlike ('*' + $launcher + '*')) {
            Write-Warning "A test shortcut already exists but targets a different checkout: $($existing.TargetPath) $($existing.Arguments)"
            Write-Warning 'Nothing was overwritten. You can still launch directly using launch-audio-test.ps1.'
        } else {
            Write-Host 'The existing Audio Sync Test desktop shortcut already points here.'
        }
    } else {
        & (Join-Path $checkout 'setup-audio-test-shortcut.ps1')
        if (-not (Test-Path -LiteralPath $shortcut)) {
            throw 'Test shortcut creation did not succeed.'
        }
    }

    Write-Host ''
    Write-Host 'Audio Sync Test prepared. Your original Pulse Capture folder and old shortcut remain untouched.'
    Write-Host "Test checkout: $checkout"
    Write-Host 'Open the Audio Sync Test shortcut, or run .\launch-audio-test.ps1.'
    if ($Launch) { & $launcher }
}
finally {
    Pop-Location
}
