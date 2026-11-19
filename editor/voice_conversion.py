"""Local conversion supervisor; model downloads are a separate explicit setup step."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from capture.ffmpeg_backend import process_options
from .ai_voiceover import library_root
from .voice_assets import digest, metadata, new_path, run_audio, wav_info

SOURCE_REV = '74a1d147b17a8c3092dd5430504bd83ef6c7eb23'
MODEL_REV = 'f36e7edfe1684461a8343844af60babc2efbb727'
MODEL_URL = 'https://huggingface.co/myshell-ai/OpenVoiceV2'


def runtime_root():
    return Path(os.environ.get('PULSE_VOICE_RUNTIME', library_root().parent / 'voice-runtime'))


def runtime_python(root=None):
    root = Path(root) if root else runtime_root()
    return root / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def available(root=None):
    root = Path(root) if root else runtime_root()
    return (runtime_python(root).is_file() and (root / 'installed.json').is_file()
            and (root / 'checkpoints/converter/checkpoint.pth').is_file())


def verify_runtime(root):
    manifest = json.loads((root / 'installed.json').read_text(encoding='utf-8'))
    if manifest['source_revision'] != SOURCE_REV or manifest['model_revision'] != MODEL_REV:
        raise ValueError('Unsupported conversion runtime revision. Run Voice Studio setup.')
    for name, expected in manifest['sha256'].items():
        file = (root / name).resolve()
        if not file.is_relative_to(root.resolve()) or digest(file) != expected:
            raise ValueError('Conversion runtime verification failed: ' + name)


def convert_voice(source, voice_file, ffmpeg, settings, root=None, runtime=None, cancel=None):
    settings.validate()
    wav_info(source)
    runtime = Path(runtime) if runtime else runtime_root()
    if not available(runtime):
        raise ValueError('Local conversion is not installed. Run Voice Studio setup first.')
    verify_runtime(runtime)
    target = new_path('converted', root)
    with tempfile.TemporaryDirectory(prefix='pulse-voice-') as tmp:
        prepared, raw = Path(tmp) / 'source.wav', Path(tmp) / 'converted.wav'
        command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
                   '-i', str(source), '-vn', '-ac', '1', '-ar', '22050', '-c:a', 'pcm_s16le', str(prepared)]
        subprocess.run(command, check=True, capture_output=True, timeout=120, **process_options())
        worker = Path(__file__).with_name('voice_conversion_worker.py')
        command = [str(runtime_python(runtime)), str(worker), '--runtime', str(runtime),
                                 '--source', str(prepared), '--destination', str(raw),
                                 '--voice', str(voice_file), '--mix', str(settings.mix)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **process_options())
        deadline = time.monotonic() + max(180, wav_info(source)['duration']*30)
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise ValueError('Conversion cancelled. Original recording retained.')
                if time.monotonic() > deadline:
                    raise ValueError('Conversion timed out. Original recording retained.')
                try:
                    stdout, stderr = process.communicate(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        if process.returncode:
            raise ValueError('Local conversion failed: ' + stderr.decode('utf-8', 'replace')[-1500:])
        run_audio(ffmpeg, raw, target, settings.filters())
        backend_info = json.loads(stdout.decode('utf-8').strip().splitlines()[-1])
    return metadata(target, {'kind': 'speech-to-speech', 'source': str(source),
                             'source_sha256': digest(source), 'voice_sha256': digest(voice_file),
                             'voice_model': str(voice_file), 'model_revision': MODEL_REV,
                             'source_revision': SOURCE_REV, 'backend': backend_info,
                             'settings': asdict(settings), 'ai_generated': True})
