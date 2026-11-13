$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    python -m pip install -r requirements-audio.txt
    if ($LASTEXITCODE -ne 0) { throw 'Windows system-audio support installation failed.' }
    Write-Host 'System-audio support installed. Restart Pulse Capture and click REFRESH DEVICES.'
} finally {
    Pop-Location
}
