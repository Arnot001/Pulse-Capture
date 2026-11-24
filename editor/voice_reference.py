"""Private reference preparation and cancellable local speaker extraction."""
from array import array
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave

from capture.ffmpeg_backend import process_options
from .voice_assets import digest, wav_info
from .voice_conversion import MODEL_REV, SOURCE_REV, available, runtime_python, runtime_root, verify_runtime

PERMISSIONS = ('own voice', 'speaker consent', 'licensed')
PRESENTATIONS = ('Unspecified', 'Male', 'Female', 'Androgynous')


def reference_labels(values):
    result = dict(values)
    for key in ('name', 'provenance', 'permission'):
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise ValueError('Provide a name, permission and source/consent details.')
    if result['permission'] not in PERMISSIONS or result.get('consent') is not True:
        raise ValueError('Confirm you have permission to create and reuse this voice.')
    if result.get('presentation', 'Unspecified') not in PRESENTATIONS:
        raise ValueError('Choose a supported voice presentation.')
    for key in ('name', 'language', 'accent', 'presentation', 'style', 'provenance'):
        if key in result:
            if not isinstance(result[key], str) or not 1 <= len(result[key].strip()) <= (2000 if key == 'provenance' else 160):
                raise ValueError(f'Provide a short, nonempty {key}.')
            result[key] = result[key].strip()
    return result


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ValueError('Reference import cancelled. Original recording retained.')


def run_local(command, cancel=None, timeout=180):
    check_cancel(cancel)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **process_options())
    deadline = time.monotonic() + timeout
    try:
        while True:
            check_cancel(cancel)
            if time.monotonic() > deadline:
                raise ValueError('Reference processing timed out. Original recording retained.')
            try:
                stdout, stderr = process.communicate(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                pass
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    check_cancel(cancel)
    if process.returncode:
        raise ValueError('Reference processing failed: ' + stderr.decode('utf-8', 'replace')[-1200:])
    return stdout


@dataclass
class PreparedReference:
    temporary: object
    original: Path
    wav: Path
    source_name: str
    source_sha256: str
    info: dict

    def close(self):
        self.temporary.cleanup()


def prepare_reference(source, ffmpeg, cancel=None):
    source = Path(source).resolve()
    if not source.is_file() or source.suffix.lower() not in ('.wav', '.mp3', '.flac', '.m4a', '.ogg'):
        raise ValueError('Choose a local WAV, MP3, FLAC, M4A or OGG reference.')
    if not 0 < source.stat().st_size <= 64*1024*1024:
        raise ValueError('Reference must be nonempty and no larger than 64 MB.')
    check_cancel(cancel)
    temporary = tempfile.TemporaryDirectory(prefix='pulse-reference-')
    folder = Path(temporary.name)
    original, wav = folder/('original'+source.suffix.lower()), folder/'reference.wav'
    try:
        shutil.copyfile(source, original)
        source_hash = digest(original)
        # Restrict demuxers/protocols so an audio-looking playlist cannot fetch URLs.
        run_local([str(ffmpeg), '-v', 'error', '-nostdin', '-n', '-protocol_whitelist', 'file',
                   '-format_whitelist', 'wav,mp3,flac,mov,ogg', '-i', str(original),
                   '-map', '0:a:0', '-vn', '-t', '61', '-ac', '1', '-ar', '22050',
                   '-c:a', 'pcm_s16le', str(wav)], cancel, 60)
        info = wav_info(wav)
        if not 3 <= info['duration'] <= 60:
            raise ValueError('Choose 3–60 seconds of one speaker; 10–30 seconds of clean speech is recommended.')
        with wave.open(str(wav), 'rb') as reader:
            pcm = array('h', reader.readframes(reader.getnframes()))
        size = 441
        active = sum(math.sqrt(sum(x*x for x in pcm[i:i+size])/size) >= 184
                     for i in range(0, len(pcm)-size+1, size)) * .02
        clipping = sum(abs(x) >= 32700 for x in pcm)/len(pcm)
        if active < 3:
            raise ValueError('Reference needs at least 3 seconds of audible speech; silence/very quiet audio is unsuitable.')
        if clipping > .02:
            raise ValueError('Reference is heavily clipped. Choose a clean, undistorted recording.')
        info.update(active_seconds=round(active, 2), clipping_fraction=clipping,
                    quality_note='Energy checks only; cannot verify one speaker, speech, noise or consent.')
        check_cancel(cancel)
        return PreparedReference(temporary, original, wav, source.name, source_hash, info)
    except BaseException:
        temporary.cleanup()
        raise


def extract_reference(reference, destination, cancel=None, runtime=None):
    runtime = Path(runtime) if runtime else runtime_root()
    check_cancel(cancel)
    if not available(runtime):
        raise ValueError('Install the local Voice Studio runtime first. No downloads run automatically.')
    verify_runtime(runtime)
    worker = Path(__file__).with_name('voice_conversion_worker.py')
    output = run_local([str(runtime_python(runtime)), str(worker), '--runtime', str(runtime),
                        '--source', str(reference.wav), '--destination', str(destination),
                        '--extract-reference'], cancel)
    return dict(json.loads(output.decode('utf-8').strip().splitlines()[-1]),
                source_revision=SOURCE_REV, model_revision=MODEL_REV, extraction_version=1)


def validate_embedding(path, cancel=None, runtime=None):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= 1024*1024:
        raise ValueError('Expected a speaker embedding under 1 MB.')
    check = ("import sys,torch; x=torch.load(sys.argv[1],map_location='cpu',weights_only=True); "
             "assert isinstance(x,torch.Tensor) and x.dtype==torch.float32 and "
             "x.shape==(1,256,1) and torch.isfinite(x).all(), 'Invalid embedding'")
    run_local([str(runtime_python(runtime)), '-c', check, str(path)], cancel, 45)
