[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$FFmpegDirectory = '',
    [switch]$BundleFFmpeg,
    [switch]$InstallBuildTools
)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if ($InstallBuildTools) {
        & $Python -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw 'Installing build tools failed.' }
    }
    & $Python -m unittest discover -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; build stopped.' }
    $buildArgs = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
                   '--name', 'Pulse Capture', '--icon', 'assets/branding/pulse.ico')
    if ($BundleFFmpeg) {
        if (-not $FFmpegDirectory) {
            $FFmpegDirectory = Split-Path (Get-Command ffmpeg -ErrorAction Stop).Source
        }
        $vendorDir = (Resolve-Path -LiteralPath $FFmpegDirectory).Path
        foreach ($binary in @('ffmpeg.exe', 'ffprobe.exe')) {
            $binaryPath = Join-Path $vendorDir $binary
            if (-not (Test-Path -LiteralPath $binaryPath -PathType Leaf)) {
                throw "Missing $binaryPath"
            }
            $buildArgs += @('--add-binary', "$binaryPath;vendor")
        }
    }
    $buildArgs += @('--add-data', 'assets;assets', 'pulse_capture.py')
    & $Python @buildArgs
    if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
    Copy-Item -LiteralPath 'README.md' -Destination 'dist/Pulse Capture/README.md'
    Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination 'dist/Pulse Capture/THIRD_PARTY_NOTICES.md'
    Write-Host 'Built dist/Pulse Capture/Pulse Capture.exe'
    Write-Host 'Keep the complete Pulse Capture folder together when moving the app.'
} finally {
    Pop-Location
}
