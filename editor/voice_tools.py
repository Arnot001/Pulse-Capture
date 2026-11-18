"""Offline Windows speech reactions for the existing Pulse sound-effect library.

No network request, API key, or third-party speech dependencies. Source text is
encoded as data on stdin; it is never interpolated into PowerShell source.
"""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave

from capture.ffmpeg_backend import process_options

MAX_CHARACTERS = 140
MAX_SECONDS = 20

_SPEAK_COMMAND = r"""
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Speech
    $encoded = [Console]::In.ReadToEnd().Trim()
    $request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded)) | ConvertFrom-Json
    $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $speaker.SetOutputToWaveFile([string]$request.output)
        $speaker.Speak([string]$request.text)
    } finally {
        $speaker.Dispose()
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


def validate_voice_text(text):
    if not isinstance(text, str):
        raise ValueError('Enter words for the spoken reaction.')
    text = ' '.join(text.split())
    if not text or len(text) > MAX_CHARACTERS or any(ord(char) < 32 for char in text):
        raise ValueError(f'Enter 1–{MAX_CHARACTERS} characters of spoken text.')
    return text


def encode_request(text, output):
    """Keep arbitrary spoken text and paths strictly outside executable code."""
    payload = json.dumps({'text': text, 'output': str(output)}, ensure_ascii=False)
    return base64.b64encode(payload.encode('utf-8')).decode('ascii')


def synthesize_windows(text, output):
    """Generate a WAV using the user's installed Windows SAPI voice."""
    text = validate_voice_text(text)
    if os.name != 'nt':
        raise ValueError('Offline voice creation currently requires Windows.')
    output = Path(output)
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', _SPEAK_COMMAND],
            input=encode_request(text, output),
            capture_output=True, text=True, encoding='ascii', errors='replace',
            timeout=45, **process_options())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Windows speech synthesis is unavailable or timed out.') from exc
    if result.returncode:
        raise ValueError('Windows speech synthesis failed: ' + (result.stderr.strip()[:240] or 'no voice installed'))
    if not output.is_file():
        raise ValueError('Windows speech synthesis produced no WAV file.')
    try:
        with wave.open(str(output), 'rb') as audio:
            if not audio.getframerate() or not 0 < audio.getnframes()/audio.getframerate() <= MAX_SECONDS:
                raise ValueError('Spoken reactions must be 20 seconds or shorter.')
    except (OSError, EOFError, wave.Error) as exc:
        raise ValueError('Windows speech synthesis produced an invalid WAV file.') from exc
    return output


def generate_voice_import(text, library, ffmpeg, ffprobe, cancel=None):
    """Create speech, validate via the existing import pipeline, label it Voices."""
    text = validate_voice_text(text)
    stem = re.sub(r'[^a-zA-Z0-9 _-]', '', text).strip()[:48] or 'Reaction'
    with tempfile.TemporaryDirectory(prefix='pulse-voice-') as temporary:
        wav = Path(temporary) / ('Voice - ' + stem + '.wav')
        synthesize_windows(text, wav)
        if cancel is not None and cancel.is_set():
            raise ValueError('Voice creation cancelled.')
        key = library.import_file(wav, 'sfx', ffmpeg, ffprobe)
    library.categorize([key], 'Voices')
    library.update_details(key, dict(audio_type='windows_voice', source='Local Windows SAPI synthesis', transcript=text))
    return key
