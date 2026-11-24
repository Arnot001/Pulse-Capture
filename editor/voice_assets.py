"""Private, immutable narration assets. No network and no SFX duration limit."""
from array import array
from dataclasses import asdict, dataclass
import hashlib
from functools import lru_cache
import json
import math
from pathlib import Path
import shutil
import subprocess
import uuid
import wave

from capture.ffmpeg_backend import process_options
from .ai_voiceover import library_root

MAX_SECONDS = 1800


def wav_info(path):
    path = Path(path).resolve()
    stat = path.stat()
    return dict(_wav_info(str(path), stat.st_size, stat.st_mtime_ns))


@lru_cache(maxsize=64)
def _wav_info(path, size, modified):
    with wave.open(str(path), 'rb') as reader:
        if reader.getcomptype() != 'NONE' or reader.getsampwidth() != 2:
            raise ValueError('Use a PCM 16-bit WAV narration recording.')
        rate, channels, frames = reader.getframerate(), reader.getnchannels(), reader.getnframes()
        if not 8000 <= rate <= 96000 or channels not in (1, 2) or not 0 < frames <= rate * MAX_SECONDS:
            raise ValueError('Narration must be between 0 and 30 minutes, mono or stereo.')
        actual = 0
        while block := reader.readframes(65536):
            actual += len(block)
        if actual != frames * channels * 2:
            raise ValueError('Narration WAV is incomplete.')
    return {'duration': frames / rate, 'rate': rate, 'channels': channels,
            'bytes': size}


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def new_path(kind, root=None, suffix='.wav'):
    folder = Path(root) if root else library_root()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f'{kind}-{uuid.uuid4().hex}{suffix}'


def metadata(path, details):
    info = wav_info(path)
    details = dict(details, **info, sha256=digest(path), schema=1)
    with Path(path).with_suffix('.json').open('x', encoding='utf-8') as handle:
        json.dump(details, handle, ensure_ascii=False, indent=2)
    return Path(path)


def run_audio(ffmpeg, source, destination, filters='anull', seconds=None):
    command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
               '-i', str(source), '-vn', '-af', filters, '-ar', '48000', '-ac', '1',
               '-c:a', 'pcm_s16le']
    if seconds is not None:
        command += ['-t', str(seconds)]
    result = subprocess.run(command + [str(destination)], capture_output=True,
                            timeout=max(120, (seconds or MAX_SECONDS) * 3), **process_options())
    if result.returncode:
        Path(destination).unlink(missing_ok=True)
        raise ValueError('Audio processing failed: ' + result.stderr.decode('utf-8', 'replace')[-1200:])
    return wav_info(destination)


def import_audio(source, ffmpeg, root=None):
    source = Path(source).resolve()
    if not source.is_file() or source.suffix.lower() not in ('.wav', '.mp3', '.flac', '.m4a', '.ogg'):
        raise ValueError('Choose a local WAV, MP3, FLAC, M4A or OGG recording.')
    if source.stat().st_size > 512 * 1024 * 1024:
        raise ValueError('Recording exceeds 512 MB.')
    # Keep an exact private copy even when decoding fails. Never overwrite a take.
    original = new_path('original', root, source.suffix.lower())
    with source.open('rb') as src, original.open('xb') as dst:
        shutil.copyfileobj(src, dst)
    target = new_path('narration', root)
    try:
        run_audio(ffmpeg, original, target, seconds=MAX_SECONDS + 1)
        return metadata(target, {'kind': 'import', 'original': str(original),
                                 'source_sha256': digest(original)})
    except Exception:
        target.unlink(missing_ok=True)
        raise


def waveform(path, columns=600):
    """Bounded display data; scan PCM in buckets rather than keeping a long take in RAM."""
    with wave.open(str(path), 'rb') as reader:
        if reader.getsampwidth() != 2:
            raise ValueError('Waveform requires PCM 16-bit audio.')
        bucket = max(1, math.ceil(reader.getnframes() / columns))
        points = []
        while block := reader.readframes(bucket):
            samples = array('h', block)
            points.append(max(abs(x) for x in samples) / 32768)
    return points


@dataclass(frozen=True)
class VoiceSettings:
    speed: float = 1.
    pitch: float = 0.
    volume: float = 1.
    mix: float = 1.
    normalize: bool = False
    denoise: bool = False
    trim_edges: bool = False

    def validate(self):
        for key, low, high in [('speed', .5, 2), ('pitch', -12, 12),
                               ('volume', 0, 2), ('mix', 0, 1)]:
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'Invalid {key}.')

    def filters(self):
        self.validate()
        filters = []
        if self.denoise:
            filters.append('afftdn=nf=-25')
        # Edge trimming only; interior dramatic pauses are never removed.
        if self.trim_edges:
            filters += ['silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB',
                        'areverse', 'silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB',
                        'areverse']
        if self.pitch or self.speed != 1:
            filters.append(f'rubberband=tempo={self.speed:g}:pitch={2**(self.pitch/12):.12f}')
        if self.normalize:
            filters.append('loudnorm=I=-16:TP=-1.5:LRA=11')
        filters += [f'volume={self.volume:g}', 'alimiter=limit=0.95:level=false:latency=true']
        return ','.join(filters)


def process_voice(source, ffmpeg, settings, root=None):
    wav_info(source)
    target = new_path('processed', root)
    run_audio(ffmpeg, source, target, settings.filters())
    return metadata(target, {'kind': 'processing', 'source': str(source),
                             'source_sha256': digest(source), 'settings': asdict(settings)})
