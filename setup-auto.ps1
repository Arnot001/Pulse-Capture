# Install optional offline English transcription into the same Python used by
# the existing desktop shortcut. No separate venv and no change to working audio.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $python = (Get-Command python -ErrorAction Stop).Source
    }
    if ($python -like '*\WindowsApps\*') {
        throw 'Microsoft Store Python alias detected. Use the installed Python 3.13 executable.'
    }
    & $python --version
    if ($LASTEXITCODE -ne 0) { throw 'Python could not be started.' }
    Write-Host 'Installing optional offline speech libraries into desktop Python...'
    & $python -m pip install -r (Join-Path $PSScriptRoot 'requirements-auto.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install local speech recognition.' }
    # Import-only avoids quoted Python -c strings getting mangled by Windows PS.
    & $python -c 'import av; import faster_whisper'
    if ($LASTEXITCODE -ne 0) { throw 'Local Whisper decoder is not importable.' }
    & $python (Join-Path $PSScriptRoot 'scripts\prepare_auto_model.py')
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare local English speech model.' }
    Write-Host 'AUTO EDIT SPEECH READY. Restart Pulse Capture using your existing desktop shortcut.' -ForegroundColor Green
}
finally {
    Pop-Location
}
