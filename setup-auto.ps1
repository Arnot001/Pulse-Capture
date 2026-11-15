$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the project virtual environment.' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements-auto.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install local speech recognition.' }
    # Verify the exact decoder version: PyAV 19 breaks faster-whisper 1.2.1.
    & '.\.venv\Scripts\python.exe' -c "import av; from faster_whisper import WhisperModel; assert av.__version__ == '18.1.0', av.__version__; print('Local Whisper decoder OK: PyAV ' + av.__version__)"
    if ($LASTEXITCODE -ne 0) { throw 'Local speech dependency check failed.' }
    # Download model weights only once; do not replace an existing model.
    if (-not (Test-Path -LiteralPath '.auto-models\base.en\model.bin')) {
        & '.\.venv\Scripts\python.exe' -c "from faster_whisper.utils import download_model; download_model('base.en', output_dir='.auto-models/base.en')"
        if ($LASTEXITCODE -ne 0) { throw 'Could not download the speech model.' }
    } else {
        Write-Output 'Existing local speech model retained.'
    }
    Write-Output 'Local English speech captions are ready. Start Pulse Capture with .\launch.ps1.'
} finally {
    Pop-Location
}
