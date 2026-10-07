$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    python pulse_capture.py
} finally {
    Pop-Location
}
