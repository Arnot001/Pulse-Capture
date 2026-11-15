$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $bundledFFmpeg = Join-Path $PSScriptRoot 'dist\Pulse Capture\_internal\vendor\ffmpeg.exe'
    if (-not $env:PULSE_FFMPEG -and (Test-Path -LiteralPath $bundledFFmpeg)) {
        $env:PULSE_FFMPEG = $bundledFFmpeg
    }
    if (Test-Path -LiteralPath '.venv\Scripts\python.exe') {
        & '.\.venv\Scripts\python.exe' pulse_capture.py
    } else {
        python pulse_capture.py
    }
} finally {
    Pop-Location
}
