"""Original Pulse music state and deterministic local soundtrack generation.

Built-in tracks are synthesized from code with no third-party audio samples.
The WAV cache is generated locally on first export and can be redistributed
with Pulse-produced videos. Imported MP3/WAV files remain the user's own content.
"""
from array import array
from dataclasses import dataclass
import math
import os
from pathlib import Path
import random
import wave

TRACKS = {
    'Pulse // Night': {
        'slug': 'pulse-night-v1', 'bpm': 96, 'mood': 'Dark tech',
        'roots': (57, 53, 48, 55), 'quality': ('min', 'maj', 'maj', 'maj'),
        'lead': (64, 69, 72, 71, 67, 64, 62, 64),
    },
    'Pulse // Drive': {
        'slug': 'pulse-drive-v1', 'bpm': 124, 'mood': 'Energetic',
        'roots': (53, 49, 44, 51), 'quality': ('min', 'maj', 'maj', 'maj'),
        'lead': (72, 68, 65, 68, 72, 75, 72, 68),
    },
    'Pulse // Focus': {
        'slug': 'pulse-focus-v1', 'bpm': 88, 'mood': 'Minimal',
        'roots': (57, 48, 55, 52), 'quality': ('min7', 'maj7', 'six', 'min7'),
        'lead': (64, 67, 69, 72, 71, 67, 64, 62),
    },
    'Pulse // Lift': {
        'slug': 'pulse-lift-v1', 'bpm': 118, 'mood': 'Upbeat',
        'roots': (50, 45, 47, 43), 'quality': ('maj', 'maj', 'min', 'maj'),
        'lead': (66, 69, 71, 69, 76, 74, 71, 69),
    },
    'Pulse // Horizon': {
        'slug': 'pulse-horizon-v1', 'bpm': 76, 'mood': 'Cinematic',
        'roots': (50, 46, 41, 48), 'quality': ('min', 'maj', 'maj', 'maj'),
        'lead': (69, 65, 62, 65, 72, 69, 67, 65),
    },
    'Pulse // Circuit': {
        'slug': 'pulse-circuit-v1', 'bpm': 110, 'mood': 'Clean tech',
        'roots': (52, 48, 43, 50), 'quality': ('min', 'maj', 'maj', 'maj'),
        'lead': (71, 67, 64, 67, 74, 71, 69, 66),
    },
}
IMPORT_LABEL = 'Imported audio'
VOLUME_LEVELS = (0.0, 0.10, 0.15, 0.20, 0.30, 0.50, 0.75, 1.0)
SAMPLE_RATE = 24000
BARS = 8


@dataclass(frozen=True)
class Music:
    enabled: bool = False
    track: str = 'Pulse // Night'
    imported: Path | None = None
    music_volume: float = 0.20
    original_volume: float = 1.0
    loop: bool = True
    fade_in: bool = True
    fade_out: bool = True

    def validate(self):
        if type(self.enabled) is not bool or type(self.loop) is not bool:
            raise ValueError('Choose valid music On/Off and Loop settings.')
        if type(self.fade_in) is not bool or type(self.fade_out) is not bool:
            raise ValueError('Choose valid music fade settings.')
        if self.track not in TRACKS and self.track != IMPORT_LABEL:
            raise ValueError('Choose a Pulse track or import your own audio.')
        for value, label in ((self.music_volume, 'Music'), (self.original_volume, 'Original audio')):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'{label} volume is invalid.')
            if value < 0 or value > 1:
                raise ValueError(f'{label} volume must be between 0% and 100%.')
        if self.track == IMPORT_LABEL:
            if self.imported is None:
                raise ValueError('Choose an MP3 or WAV file to use as music.')
            path = Path(self.imported)
            if path.suffix.lower() not in ('.mp3', '.wav'):
                raise ValueError('Imported music must be an MP3 or WAV file.')
        elif self.imported is not None:
            # A remembered import may coexist while a built-in is selected.
            Path(self.imported)


def cache_folder():
    override = os.environ.get('PULSE_MUSIC_CACHE')
    if override:
        return Path(override)
    base = os.environ.get('LOCALAPPDATA')
    if base:
        return Path(base) / 'Pulse Capture' / 'music'
    return Path.home() / '.pulse-capture' / 'music'


def track_path(track):
    if track not in TRACKS:
        raise ValueError('Choose a built-in Pulse track.')
    return cache_folder() / (TRACKS[track]['slug'] + '.wav')


def _freq(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _triad(root, quality):
    if quality == 'min':
        return (root, root + 3, root + 7)
    if quality == 'maj':
        return (root, root + 4, root + 7)
    if quality == 'min7':
        return (root, root + 3, root + 7, root + 10)
    if quality == 'maj7':
        return (root, root + 4, root + 7, root + 11)
    if quality == 'six':
        return (root, root + 4, root + 7, root + 9)
    raise ValueError('Unknown Pulse chord quality.')


def _fract(value):
    return value - math.floor(value)


def _triangle(phase):
    return 2 / math.pi * math.asin(math.sin(phase))


def _noise(index):
    # Deterministic pseudo-noise: no external samples and no RNG state.
    return _fract(math.sin((index + 1) * 12.9898) * 43758.5453) * 2 - 1


def _soft_clip(value):
    return math.tanh(value * 1.15) / math.tanh(1.15)


def _sample(track, index, time_seconds):
    recipe = TRACKS[track]
    bpm = recipe['bpm']
    beat = 60.0 / bpm
    beats = time_seconds / beat
    bar = int(beats // 4) % 8
    beat_in_bar = beats % 4
    chord_index = bar % 4
    root = recipe['roots'][chord_index]
    chord = _triad(root, recipe['quality'][chord_index])

    # Warm pad. Slow tremolo prevents a static sine bed.
    pad = 0.0
    for i, note in enumerate(chord):
        detune = (-3.5 if i % 2 == 0 else 3.5)
        freq = _freq(note) * 2 ** (detune / 1200)
        pad += _triangle(2 * math.pi * freq * time_seconds + i * .7)
    pad *= (0.085 + 0.012 * math.sin(2 * math.pi * time_seconds / (beat * 8))) / len(chord)

    # Bass note pulses each beat and decays before the next.
    beat_phase = beat_in_bar % 1.0
    bass_env = math.exp(-3.8 * beat_phase)
    bass_freq = _freq(root - 12)
    bass = math.sin(2 * math.pi * bass_freq * time_seconds) * bass_env * .20

    # Eighth-note melodic pluck.
    step = int(beats * 2) % 8
    step_phase = (beats * 2) % 1
    lead_note = recipe['lead'][(step + (2 if bar >= 4 else 0)) % 8]
    lead_env = math.exp(-6.2 * step_phase)
    lead_freq = _freq(lead_note)
    lead = _triangle(2 * math.pi * lead_freq * time_seconds) * lead_env
    lead_amp = .055 if track == 'Pulse // Focus' else .075
    if track == 'Pulse // Horizon':
        lead_amp = .050
    lead *= lead_amp

    # Drum synthesis. Horizon is intentionally sparse.
    kick = snare = hat = 0.0
    kick_phase = beat_phase
    if track != 'Pulse // Horizon' or beat_in_bar < 1:
        kenv = math.exp(-16 * kick_phase)
        kfreq = 48 + 82 * math.exp(-18 * kick_phase)
        kick = math.sin(2 * math.pi * kfreq * (kick_phase * beat)) * kenv * (
            .38 if track == 'Pulse // Focus' else .50
        )
    if track == 'Pulse // Horizon':
        if 2 <= beat_in_bar < 2.22:
            p = beat_in_bar - 2
            snare = _noise(index) * math.exp(-20 * p) * .055
    else:
        nearest = beat_in_bar - (1 if beat_in_bar < 2 else 3)
        if 0 <= nearest < .18:
            snare = (_noise(index) * .75 + math.sin(2 * math.pi * 180 * time_seconds) * .25)
            snare *= math.exp(-24 * nearest) * .14
        hat_step = (beats * (4 if track == 'Pulse // Drive' else 2)) % 1
        hat = (_noise(index) - _noise(max(0, index - 1))) * math.exp(-65 * hat_step) * .025

    # Small stereo movement is enough for a background bed without fighting speech.
    pan = .24 if step % 2 else -.24
    lead_l = lead * math.sqrt((1 - pan) / 2)
    lead_r = lead * math.sqrt((1 + pan) / 2)
    centre = pad + bass + kick + snare
    left = centre * .70 + lead_l + hat * .50
    right = centre * .70 + lead_r + hat * .54
    return _soft_clip(left), _soft_clip(right)


def generate_track(track, destination=None):
    """Generate one deterministic original Pulse loop as 16-bit stereo WAV."""
    if track not in TRACKS:
        raise ValueError('Choose a built-in Pulse track.')
    destination = Path(destination or track_path(track))
    destination.parent.mkdir(parents=True, exist_ok=True)
    recipe = TRACKS[track]
    beat = 60.0 / recipe['bpm']
    duration = BARS * 4 * beat
    frames = int(round(duration * SAMPLE_RATE))
    temp = destination.with_suffix('.partial.wav')
    pcm = array('h')
    edge = max(1, int(.008 * SAMPLE_RATE))
    for index in range(frames):
        time_seconds = index / SAMPLE_RATE
        left, right = _sample(track, index, time_seconds)
        if index < edge:
            gain = index / edge
            left *= gain
            right *= gain
        elif index >= frames - edge:
            gain = (frames - 1 - index) / edge
            left *= max(0, gain)
            right *= max(0, gain)
        pcm.append(max(-32767, min(32767, round(left * 23000))))
        pcm.append(max(-32767, min(32767, round(right * 23000))))
    try:
        with wave.open(str(temp), 'wb') as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(pcm.tobytes())
        os.replace(temp, destination)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    return destination


def resolve_music_path(music):
    music.validate()
    if not music.enabled:
        return None
    if music.track == IMPORT_LABEL:
        path = Path(music.imported)
        if not path.is_file():
            raise ValueError('Imported music file could not be found. Choose it again.')
        return path
    path = track_path(music.track)
    if not path.is_file() or path.stat().st_size < 44:
        path = generate_track(music.track, path)
    return path


def music_duration(track):
    if track not in TRACKS:
        raise ValueError('Choose a built-in Pulse track.')
    return BARS * 4 * 60.0 / TRACKS[track]['bpm']
