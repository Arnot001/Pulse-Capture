$ErrorActionPreference = 'Stop'
$old = Join-Path (Split-Path $PSScriptRoot -Parent) 'Pulse-Capture'
if (-not $env:PULSE_FFMPEG -and (Test-Path (Join-Path $old 'vendor\ffmpeg.exe'))) {
    $env:PULSE_FFMPEG = Join-Path $old 'vendor\ffmpeg.exe'
    $env:PULSE_FFPROBE = Join-Path $old 'vendor\ffprobe.exe'
}
Push-Location $PSScriptRoot
try {
    & (Get-Command python -ErrorAction Stop).Source pulse_capture.py
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Pulse Capture exited with code $LASTEXITCODE."
        Read-Host 'Press Enter to close'
    }
} finally {
    Pop-Location
}
