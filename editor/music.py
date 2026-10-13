"""Original Pulse music state and deterministic local soundtrack generation.

Built-in tracks are composed and synthesized from code with no third-party audio
samples. Version 2 uses track-specific arrangements, palettes and transitions
instead of one shared loop recipe. Generated WAVs are cached locally; imported
MP3/WAV files remain the user's own content.
"""
from array import array
from dataclasses import dataclass
import math
import os
from pathlib import Path
import threading
import wave

TRACKS = {
    'Pulse // Night': {
        'slug': 'pulse-night-v2', 'bpm': 96, 'mood': 'Dark tech',
        'seed': 11, 'palette': 'night', 'swing': .055,
        'roots_a': (57, 53, 48, 55), 'quality_a': ('min9', 'maj7', 'maj9', 'sus2'),
        'roots_b': (57, 60, 53, 52), 'quality_b': ('min9', 'maj7', 'maj7', 'min7'),
        'lead_a': (64, None, 67, 69, 72, 71, 67, None),
        'lead_b': (76, 72, 71, 67, 74, 72, 69, 71),
        'bass': (0, None, 7, 0, 12, None, 7, -2),
        'pad': 'dark', 'lead': 'glass', 'bass_tone': 'dark',
        'lead_div': 2, 'arp_div': 4, 'hat_div': 2,
    },
    'Pulse // Drive': {
        'slug': 'pulse-drive-v2', 'bpm': 124, 'mood': 'Energetic',
        'seed': 23, 'palette': 'drive', 'swing': .018,
        'roots_a': (53, 49, 44, 51), 'quality_a': ('min7', 'maj7', 'maj', 'sus4'),
        'roots_b': (53, 56, 49, 51), 'quality_b': ('min9', 'maj', 'maj7', 'sus2'),
        'lead_a': (72, 68, 65, 68, 72, 75, 72, 68),
        'lead_b': (77, 75, 72, 68, 80, 77, 75, 72),
        'bass': (0, 0, 7, 0, 12, 7, 5, 7),
        'pad': 'saw', 'lead': 'pulse', 'bass_tone': 'saw',
        'lead_div': 2, 'arp_div': 4, 'hat_div': 4,
    },
    'Pulse // Focus': {
        'slug': 'pulse-focus-v2', 'bpm': 88, 'mood': 'Minimal',
        'seed': 37, 'palette': 'focus', 'swing': .085,
        'roots_a': (57, 48, 55, 52), 'quality_a': ('min9', 'maj7', 'six', 'min7'),
        'roots_b': (57, 52, 55, 48), 'quality_b': ('min7', 'min9', 'sus2', 'maj9'),
        'lead_a': (64, None, 67, None, 69, None, 72, None),
        'lead_b': (71, None, 67, 64, 74, None, 72, 67),
        'bass': (0, None, 7, None, 0, None, 10, None),
        'pad': 'warm', 'lead': 'soft', 'bass_tone': 'warm',
        'lead_div': 2, 'arp_div': 2, 'hat_div': 2,
    },
    'Pulse // Lift': {
        'slug': 'pulse-lift-v2', 'bpm': 118, 'mood': 'Upbeat',
        'seed': 41, 'palette': 'lift', 'swing': .025,
        'roots_a': (50, 45, 47, 43), 'quality_a': ('maj9', 'maj', 'min7', 'maj7'),
        'roots_b': (50, 47, 43, 45), 'quality_b': ('maj', 'min7', 'maj9', 'sus4'),
        'lead_a': (66, 69, 71, 69, 76, 74, 71, 69),
        'lead_b': (78, 76, 74, 71, 81, 78, 76, 74),
        'bass': (0, 7, 12, 7, 0, 7, 9, 7),
        'pad': 'bright', 'lead': 'glass', 'bass_tone': 'warm',
        'lead_div': 2, 'arp_div': 4, 'hat_div': 4,
    },
    'Pulse // Horizon': {
        'slug': 'pulse-horizon-v2', 'bpm': 76, 'mood': 'Cinematic',
        'seed': 59, 'palette': 'horizon', 'swing': .0,
        'roots_a': (50, 46, 41, 48), 'quality_a': ('min9', 'maj7', 'maj9', 'sus2'),
        'roots_b': (50, 53, 46, 48), 'quality_b': ('min7', 'maj9', 'maj7', 'sus4'),
        'lead_a': (69, None, 65, None, 62, 65, None, 67),
        'lead_b': (74, 72, 69, None, 77, 74, 72, 69),
        'bass': (0, None, None, 7, 0, None, 12, None),
        'pad': 'strings', 'lead': 'soft', 'bass_tone': 'dark',
        'lead_div': 1, 'arp_div': 2, 'hat_div': 1,
    },
    'Pulse // Circuit': {
        'slug': 'pulse-circuit-v2', 'bpm': 110, 'mood': 'Clean tech',
        'seed': 71, 'palette': 'circuit', 'swing': .035,
        'roots_a': (52, 48, 43, 50), 'quality_a': ('min7', 'maj7', 'maj9', 'sus2'),
        'roots_b': (52, 55, 48, 50), 'quality_b': ('min9', 'maj', 'maj7', 'sus4'),
        'lead_a': (71, 67, 64, 67, 74, 71, 69, 66),
        'lead_b': (76, 74, 71, 67, 79, 76, 74, 71),
        'bass': (0, 7, 3, 10, 0, 12, 7, 3),
        'pad': 'digital', 'lead': 'pulse', 'bass_tone': 'digital',
        'lead_div': 2, 'arp_div': 4, 'hat_div': 4,
    },
}
IMPORT_LABEL = 'Imported audio'
VOLUME_LEVELS = (0.0, 0.10, 0.15, 0.20, 0.30, 0.50, 0.75, 1.0)
SAMPLE_RATE = 30000
BARS = 12
ARRANGEMENT_BARS = 12


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


def arrangement_section(bar):
    """Return the musical section for a zero-based bar in the 12-bar arrangement."""
    bar = int(bar) % ARRANGEMENT_BARS
    if bar == 0:
        return 'INTRO'
    if 1 <= bar <= 4:
        return 'A'
    if 5 <= bar <= 8:
        return 'B'
    if 9 <= bar <= 10:
        return 'LIFT'
    return 'TURN'


def _freq(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _chord(root, quality):
    intervals = {
        'min7': (0, 3, 7, 10),
        'maj7': (0, 4, 7, 11),
        'min9': (0, 3, 7, 10, 14),
        'maj9': (0, 4, 7, 11, 14),
        'six': (0, 4, 7, 9),
        'sus2': (0, 2, 7, 10),
        'sus4': (0, 5, 7, 10),
        'maj': (0, 4, 7),
    }
    if quality not in intervals:
        raise ValueError('Unknown Pulse chord quality.')
    return tuple(root + interval for interval in intervals[quality])


def _voicing(notes, inversion):
    notes = list(notes)
    for index in range(min(inversion, len(notes))):
        notes[index] += 12
    notes.sort()
    return tuple(notes)


def _fract(value):
    return value - math.floor(value)


def _rand01(seed, key):
    return _fract(math.sin((key + 1) * (12.9898 + seed * .173)) * 43758.5453)


def _noise(index, seed=0):
    return _rand01(seed + 97, index) * 2 - 1


def _triangle(phase):
    return 2 / math.pi * math.asin(math.sin(phase))


def _osc(phase, timbre):
    if timbre == 'warm':
        return .82 * math.sin(phase) + .13 * math.sin(2 * phase) + .05 * math.sin(3 * phase)
    if timbre == 'dark':
        return .74 * math.sin(phase) + .19 * math.sin(2 * phase) + .07 * math.sin(3 * phase)
    if timbre == 'bright':
        return .58 * math.sin(phase) + .23 * math.sin(2 * phase) + .12 * math.sin(3 * phase) + .07 * math.sin(4 * phase)
    if timbre == 'strings':
        return .66 * math.sin(phase) + .20 * math.sin(2 * phase) + .09 * math.sin(3 * phase) + .05 * math.sin(5 * phase)
    if timbre == 'glass':
        return .72 * math.sin(phase) + .20 * math.sin(2 * phase) + .08 * math.sin(4 * phase)
    if timbre == 'soft':
        return .88 * math.sin(phase) + .12 * _triangle(phase)
    if timbre == 'pulse':
        return .69 * math.sin(phase) + .22 * math.sin(3 * phase) + .09 * math.sin(5 * phase)
    if timbre == 'digital':
        return .61 * math.sin(phase) + .24 * _triangle(phase) + .10 * math.sin(4 * phase) + .05 * math.sin(7 * phase)
    if timbre == 'saw':
        return (
            .56 * math.sin(phase) + .24 * math.sin(2 * phase) +
            .13 * math.sin(3 * phase) + .07 * math.sin(4 * phase)
        )
    return math.sin(phase)


def _soft_clip(value):
    return math.tanh(value * 1.08) / math.tanh(1.08)


def _grid(beats, division, swing):
    raw = beats * division
    event = math.floor(raw)
    phase = raw - event
    shift = swing if division >= 2 and event % 2 else 0.0
    local = phase - shift
    if local < 0:
        return event, None
    return event, local / max(.001, 1 - shift)


def _hit_phase(beat_in_bar, positions, window=.5):
    best = None
    for position in positions:
        delta = beat_in_bar - position
        if 0 <= delta < window and (best is None or delta < best):
            best = delta
    return best


def _progression(recipe, bar, section):
    index = max(0, bar - 1) % 4
    if section in ('B', 'LIFT'):
        roots, qualities = recipe['roots_b'], recipe['quality_b']
    else:
        roots, qualities = recipe['roots_a'], recipe['quality_a']
    root = roots[index]
    quality = qualities[index]
    inversion = (bar + (1 if section in ('B', 'LIFT') else 0)) % 3
    return root, _voicing(_chord(root, quality), inversion)


def _pad(recipe, chord, section, bar, beat_in_bar, time_seconds):
    palette = recipe['palette']
    section_gain = {'INTRO': .52, 'A': .78, 'B': .92, 'LIFT': 1.0, 'TURN': .70}[section]
    if section == 'INTRO':
        section_gain *= min(1.0, .35 + beat_in_bar / 4)
    if section == 'TURN' and beat_in_bar > 3.2:
        section_gain *= max(.2, (4 - beat_in_bar) / .8)

    movement = .92 + .08 * math.sin(
        2 * math.pi * time_seconds / ((60 / recipe['bpm']) * (6 if palette == 'horizon' else 4))
    )
    timbre = recipe['pad']
    total_l = total_r = 0.0
    voices = chord[:4]
    for i, note in enumerate(voices):
        detune = 3.4 + i * .7
        freq = _freq(note)
        phase_l = 2 * math.pi * freq * (2 ** (-detune / 1200)) * time_seconds + i * .43
        phase_r = 2 * math.pi * freq * (2 ** (detune / 1200)) * time_seconds + i * .71
        total_l += _osc(phase_l, timbre)
        total_r += _osc(phase_r, timbre)
    amp = {
        'night': .073, 'drive': .052, 'focus': .082,
        'lift': .060, 'horizon': .105, 'circuit': .050,
    }[palette] * section_gain * movement / max(1, len(voices))
    return total_l * amp, total_r * amp


def _bass(recipe, root, section, beats, time_seconds):
    palette = recipe['palette']
    division = 1 if palette in ('focus', 'horizon') else 2
    event, phase = _grid(beats, division, recipe['swing'])
    if phase is None:
        return 0.0
    pattern = recipe['bass']
    offset = pattern[event % len(pattern)]
    if offset is None:
        return 0.0
    note = root - 12 + offset
    velocity = .88 + .18 * (_rand01(recipe['seed'], event) - .5)
    decay = 3.0 if palette in ('focus', 'horizon') else 4.8
    env = math.exp(-decay * phase)
    freq = _freq(note)
    fundamental = math.sin(2 * math.pi * freq * time_seconds)
    upper = _osc(2 * math.pi * freq * time_seconds, recipe['bass_tone'])
    amp = {
        'night': .21, 'drive': .245, 'focus': .14,
        'lift': .19, 'horizon': .18, 'circuit': .205,
    }[palette]
    if section == 'INTRO':
        amp *= .48
    elif section == 'LIFT':
        amp *= 1.10
    elif section == 'TURN':
        amp *= .72
    return (fundamental * .72 + upper * .28) * env * amp * velocity


def _lead(recipe, section, bar, beats, time_seconds):
    division = recipe['lead_div']
    event, phase = _grid(beats, division, recipe['swing'])
    if phase is None:
        return 0.0, 0.0
    local_step = event % 8
    pattern = recipe['lead_b'] if section in ('B', 'LIFT') else recipe['lead_a']
    note = pattern[local_step]
    if note is None:
        return 0.0, 0.0
    if section == 'INTRO' and local_step not in (0, 4):
        return 0.0, 0.0
    if section == 'A' and recipe['palette'] in ('night', 'focus', 'horizon') and local_step % 2:
        return 0.0, 0.0
    if section == 'TURN' and local_step not in (0, 3, 6):
        return 0.0, 0.0

    velocity = .78 + .30 * _rand01(recipe['seed'] + bar, event)
    cents = (_rand01(recipe['seed'] + 3, event) - .5) * 5.0
    freq = _freq(note) * 2 ** (cents / 1200)
    decay = {
        'night': 7.0, 'drive': 8.5, 'focus': 5.2,
        'lift': 7.2, 'horizon': 3.2, 'circuit': 9.0,
    }[recipe['palette']]
    env = math.exp(-decay * phase)
    tone = _osc(2 * math.pi * freq * time_seconds, recipe['lead'])
    amp = {
        'night': .075, 'drive': .070, 'focus': .046,
        'lift': .072, 'horizon': .055, 'circuit': .066,
    }[recipe['palette']]
    if section == 'B':
        amp *= 1.15
    elif section == 'LIFT':
        amp *= 1.28
    pan = ((_rand01(recipe['seed'] + 9, event) * 2) - 1) * .34
    left = tone * env * amp * velocity * math.sqrt((1 - pan) / 2)
    right = tone * env * amp * velocity * math.sqrt((1 + pan) / 2)
    return left, right


def _arp(recipe, chord, section, beats, time_seconds):
    palette = recipe['palette']
    if palette == 'horizon' and section not in ('B', 'LIFT'):
        return 0.0, 0.0
    if palette == 'focus' and section != 'LIFT':
        return 0.0, 0.0
    if section == 'INTRO':
        return 0.0, 0.0

    division = recipe['arp_div']
    event, phase = _grid(beats, division, recipe['swing'] * .6)
    if phase is None:
        return 0.0, 0.0
    order = (0, 2, 1, 3, 1, 2, 4, 2)
    note = chord[order[event % len(order)] % len(chord)]
    if event % 8 in (4, 6) and section in ('B', 'LIFT'):
        note += 12
    freq = _freq(note)
    env = math.exp(-(9.0 if palette != 'horizon' else 4.2) * phase)
    tone = _osc(2 * math.pi * freq * time_seconds, 'glass' if palette != 'circuit' else 'digital')
    amp = {
        'night': .027, 'drive': .045, 'focus': .020,
        'lift': .041, 'horizon': .026, 'circuit': .052,
    }[palette]
    if section == 'LIFT':
        amp *= 1.35
    pan = .42 if event % 2 else -.42
    return (
        tone * env * amp * math.sqrt((1 - pan) / 2),
        tone * env * amp * math.sqrt((1 + pan) / 2),
    )


def _counter_motif(recipe, section, beats, time_seconds):
    if section not in ('B', 'LIFT'):
        return 0.0, 0.0
    palette = recipe['palette']
    if palette == 'focus' and section != 'LIFT':
        return 0.0, 0.0
    event, phase = _grid(beats, 1, 0)
    if phase is None or event % 2:
        return 0.0, 0.0
    note = recipe['lead_b'][(event // 2 + 3) % len(recipe['lead_b'])]
    if note is None:
        return 0.0, 0.0
    note -= 12
    freq = _freq(note)
    env = math.exp(-2.6 * phase)
    tone = _osc(2 * math.pi * freq * time_seconds, 'soft')
    amp = .026 if palette != 'horizon' else .040
    if section == 'LIFT':
        amp *= 1.25
    return tone * env * amp * .82, tone * env * amp


def _drums(recipe, section, bar, beat_in_bar, beats, index, time_seconds):
    palette = recipe['palette']
    if section == 'INTRO':
        intro_scale = .35 if bar == 0 else .55
    else:
        intro_scale = 1.0

    if palette == 'focus':
        kicks = (0.0, 2.5) if section in ('B', 'LIFT') else (0.0, 2.0)
    elif palette == 'circuit':
        kicks = (0.0, 1.5, 2.5) if section in ('B', 'LIFT') else (0.0, 2.5)
    elif palette == 'horizon':
        kicks = (0.0, 2.0) if section == 'LIFT' else (0.0,)
    elif palette == 'night':
        kicks = (0.0, 1.0, 2.0, 3.0) if section in ('B', 'LIFT') else (0.0, 2.0)
    else:
        kicks = (0.0, 1.0, 2.0, 3.0)

    kick = 0.0
    kphase = _hit_phase(beat_in_bar, kicks, .42)
    if kphase is not None:
        env = math.exp(-15 * kphase)
        freq = 46 + 92 * math.exp(-18 * kphase)
        kick = math.sin(2 * math.pi * freq * (kphase * 60 / recipe['bpm'])) * env
        kick *= {
            'night': .43, 'drive': .53, 'focus': .24,
            'lift': .47, 'horizon': .48, 'circuit': .40,
        }[palette] * intro_scale

    if palette == 'horizon':
        snares = (2.0,) if section in ('B', 'LIFT') else ()
    elif palette == 'circuit':
        snares = (1.5, 3.5)
    elif palette == 'focus':
        snares = (2.0,)
    else:
        snares = (1.0, 3.0)
    snare = 0.0
    sphase = _hit_phase(beat_in_bar, snares, .28)
    if sphase is not None:
        noise = _noise(index, recipe['seed']) * .72 + math.sin(2 * math.pi * 185 * time_seconds) * .28
        snare = noise * math.exp(-21 * sphase) * {
            'night': .13, 'drive': .17, 'focus': .065,
            'lift': .15, 'horizon': .075, 'circuit': .105,
        }[palette] * intro_scale

    hat = 0.0
    if palette != 'horizon' or section == 'LIFT':
        division = recipe['hat_div']
        event, hphase = _grid(beats, division, recipe['swing'])
        if hphase is not None:
            velocity = (.58 if event % 2 else 1.0) * (.84 + .22 * _rand01(recipe['seed'] + 17, event))
            noise = _noise(index, recipe['seed'] + 31) - _noise(max(0, index - 1), recipe['seed'] + 31)
            hat = noise * math.exp(-55 * hphase) * .024 * velocity * intro_scale
            if section == 'LIFT':
                hat *= 1.22

    # Deterministic tom/snare fill at transitions and at the loop turnaround.
    fill = 0.0
    if bar in (4, 8, 11) and beat_in_bar >= 3.0:
        event, fphase = _grid((beat_in_bar - 3.0), 4, .02)
        if fphase is not None:
            pitch = 230 - (event % 4) * 28
            tone = math.sin(2 * math.pi * pitch * time_seconds)
            noise = _noise(index, recipe['seed'] + 53)
            fill = (tone * .55 + noise * .45) * math.exp(-10 * fphase)
            fill *= .08 + .025 * (event % 4)

    return kick, snare, hat, fill


def _effects(recipe, section, bar, beat_in_bar, index, time_seconds):
    palette = recipe['palette']
    left = right = 0.0

    # Two-bar-section transitions get a synthesized riser, not a sample.
    if bar in (4, 8) and beat_in_bar >= 2.0:
        p = (beat_in_bar - 2.0) / 2.0
        noise = _noise(index, recipe['seed'] + 81)
        shimmer = math.sin(2 * math.pi * (280 + 900 * p * p) * time_seconds)
        amount = (p ** 2) * (.035 if palette != 'horizon' else .050)
        left += (noise * .45 + shimmer * .55) * amount
        right += (-noise * .38 + shimmer * .62) * amount

    # New sections land with a low impact and a short high-frequency splash.
    if bar in (5, 9) and beat_in_bar < .55:
        p = beat_in_bar
        low = math.sin(2 * math.pi * (58 - 16 * min(1, p / .55)) * time_seconds)
        boom = low * math.exp(-6 * p) * (.13 if palette != 'horizon' else .20)
        splash = _noise(index, recipe['seed'] + 101) * math.exp(-16 * p) * .032
        left += boom + splash
        right += boom - splash * .7

    # The final bar deliberately breathes before looping back into the intro.
    if section == 'TURN' and beat_in_bar >= 3.5:
        p = (beat_in_bar - 3.5) / .5
        sweep = math.sin(2 * math.pi * (560 - 300 * p) * time_seconds)
        left += sweep * (1 - p) * .020
        right -= sweep * (1 - p) * .016
    return left, right


def _sample(track, index, time_seconds):
    recipe = TRACKS[track]
    beat = 60.0 / recipe['bpm']
    beats = time_seconds / beat
    bar = int(beats // 4) % ARRANGEMENT_BARS
    beat_in_bar = beats % 4
    section = arrangement_section(bar)
    root, chord = _progression(recipe, bar, section)

    pad_l, pad_r = _pad(recipe, chord, section, bar, beat_in_bar, time_seconds)
    bass = _bass(recipe, root, section, beats, time_seconds)
    lead_l, lead_r = _lead(recipe, section, bar, beats, time_seconds)
    arp_l, arp_r = _arp(recipe, chord, section, beats, time_seconds)
    counter_l, counter_r = _counter_motif(recipe, section, beats, time_seconds)
    kick, snare, hat, fill = _drums(
        recipe, section, bar, beat_in_bar, beats, index, time_seconds
    )
    fx_l, fx_r = _effects(recipe, section, bar, beat_in_bar, index, time_seconds)

    # Electronic tracks duck harmonic material very slightly around kicks.
    duck = 1.0
    if recipe['palette'] in ('drive', 'lift', 'night'):
        phase = beat_in_bar % 1.0
        duck = .70 + .30 * min(1.0, phase / .18)

    harmonic_l = (pad_l + lead_l + arp_l + counter_l) * duck
    harmonic_r = (pad_r + lead_r + arp_r + counter_r) * duck
    centre = bass * (.88 if recipe['palette'] == 'focus' else 1.0) + kick + snare + fill

    # Slightly different hat/FX balance creates width without phasey voice content.
    left = centre * .71 + harmonic_l + hat * .46 + fx_l
    right = centre * .71 + harmonic_r + hat * .54 + fx_r

    # Lightweight master: headroom, soft saturation and a fixed ceiling.
    left = max(-.96, min(.96, _soft_clip(left * .93)))
    right = max(-.96, min(.96, _soft_clip(right * .93)))
    return left, right


def generate_track(track, destination=None):
    """Generate one deterministic original Pulse arrangement as 16-bit stereo WAV."""
    if track not in TRACKS:
        raise ValueError('Choose a built-in Pulse track.')
    destination = Path(destination or track_path(track))
    destination.parent.mkdir(parents=True, exist_ok=True)
    recipe = TRACKS[track]
    beat = 60.0 / recipe['bpm']
    duration = BARS * 4 * beat
    frames = int(round(duration * SAMPLE_RATE))
    temp = destination.with_name(
        destination.name + f'.{os.getpid()}.{threading.get_ident()}.partial'
    )
    pcm = array('h')
    edge = max(1, int(.012 * SAMPLE_RATE))
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
        pcm.append(max(-32767, min(32767, round(left * 23500))))
        pcm.append(max(-32767, min(32767, round(right * 23500))))
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
