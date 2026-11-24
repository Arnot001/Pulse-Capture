"""Non-destructive, output-clock microphone commentary clips and audio mixing.

Unlike 20-second SFX or the single AI narration cue, commentary clips can be
trimmed, split, moved, replaced by a converted voice and independently faded.
The original WAV remains in the private Pulse voice library.
"""
from dataclasses import dataclass, replace
import math
from pathlib import Path

from .ai_voiceover import library_root
from .voice_assets import wav_info

MAX_CLIPS = 24


@dataclass(frozen=True)
class CommentaryClip:
    file: str
    start: float
    end: float
    source_in: float = 0.0
    volume: float = 1.0
    background_gain: float = 0.5
    fade_in: float = 0.025
    fade_out: float = 0.045
    original_file: str = ""
    auto_duck: bool = True

    @property
    def title(self):
        return Path(self.original_file or self.file).stem.replace("recording-", "Take ")

    @property
    def duration(self):
        return self.end - self.start

    def validate(self, total=None):
        root = library_root().resolve()
        for path in (self.file, self.original_file or self.file):
            candidate = Path(path).resolve()
            if candidate.parent != root or candidate.suffix.lower() != ".wav" or not candidate.is_file():
                raise ValueError("Use a saved Pulse commentary WAV; original recording is protected.")
        if type(self.auto_duck) is not bool:
            raise ValueError('Auto duck must be on or off.')
        original = wav_info(self.original_file or self.file)
        current = wav_info(self.file)
        if (not all(type(x) in (float, int) and math.isfinite(x) for x in
                    (self.start, self.end, self.source_in, self.volume,
                     self.background_gain, self.fade_in, self.fade_out))):
            raise ValueError("Commentary times and levels must be finite.")
        if not 0 <= self.start < self.end <= 86400 or not 0 <= self.source_in:
            raise ValueError("Choose a valid positive commentary interval.")
        if self.source_in + self.duration > current['duration'] + 0.001:
            raise ValueError("Commentary selection extends beyond this recording.")
        if not 0 <= self.volume <= 2 or not 0 <= self.background_gain <= 1:
            raise ValueError("Voice volume or background gain is outside its range.")
        if not 0 <= self.fade_in <= 1 or not 0 <= self.fade_out <= 1:
            raise ValueError("Commentary fades must be between 0 and 1 second.")
        if total is not None and self.end > total + .001:
            raise ValueError("Commentary must fit inside the edited video.")
        return original

    def with_file(self, new_path):
        updated = replace(self, file=str(Path(new_path).resolve()),
                          original_file=self.original_file or self.file)
        duration = wav_info(new_path)['duration']
        if self.source_in + self.duration > duration + .001:
            updated = replace(updated, end=self.start + max(0, duration - self.source_in))
        updated.validate()
        return updated


def validate_commentary(cues, total=None):
    if len(cues) > MAX_CLIPS:
        raise ValueError(f"Use at most {MAX_CLIPS} commentary clips.")
    for cue in cues:
        if not isinstance(cue, CommentaryClip):
            raise ValueError("Invalid commentary clip.")
        cue.validate(total)


def split_clip(cue, at):
    cue.validate()
    if not cue.start + .05 <= at <= cue.end - .05:
        raise ValueError("Split at least 50 ms inside the selected commentary clip.")
    left = replace(cue, end=float(at))
    right = replace(cue, start=float(at), source_in=cue.source_in + at - cue.start)
    left.validate()
    right.validate()
    return left, right


def adjust_timing(cue, start, end):
    """A move preserves source-in; left-edge trimming advances source-in."""
    old_length = cue.duration
    if abs((end-start)-old_length) < 1e-4:
        source_in = cue.source_in
    elif abs(end-cue.end) < 1e-4:
        source_in = cue.source_in + start - cue.start
    else:
        source_in = cue.source_in
    updated = replace(cue, start=start, end=end, source_in=source_in)
    updated.validate()
    return updated


def add_commentary(inputs, graph, bed, cues, duration, offset=0.0):
    """Add selected WAV intervals; align all clocks to this render window.

    Plays only cues overlapping [offset,offset+duration]. The audio bed is
    ducked only during the selected clips, then the vocal WAVs are mixed.
    The same graph builder is used for export and audible preview.
    """
    audible = [c for c in cues if c.start < offset + duration and c.end > offset]
    if not audible:
        return bed
    labels = []
    gains = []
    for i, cue in enumerate(audible):
        cue.validate()
        overlap_a = max(offset, cue.start)
        overlap_b = min(offset + duration, cue.end)
        overlap = overlap_b - overlap_a
        if overlap <= 0:
            continue
        input_index = inputs.count('-i')
        inputs.extend(['-i', str(Path(cue.file).resolve())])
        track = f'commentary{i}'
        skip = cue.source_in + max(0, offset - cue.start)
        delay = overlap_a - offset
        fade_start = max(0., cue.fade_in - max(0., offset - cue.start))
        tail_left = max(0., cue.end - overlap_b)
        fade_end = max(0., cue.fade_out - tail_left)
        filters = [f'atrim=start={skip:.9f}:duration={overlap:.9f}',
                   'asetpts=PTS-STARTPTS', 'aresample=48000',
                   f'volume={cue.volume:g}']
        if fade_start:
            filters.append(f'afade=t=in:d={min(fade_start, overlap/2):.9f}')
        if fade_end:
            filters.append(f'afade=t=out:st={max(0.,overlap-fade_end):.9f}:d={min(fade_end,overlap):.9f}')
        filters.append(f'adelay={round(delay*48000)}S:all=1')
        graph.append(f'[{input_index}:a:0]' + ','.join(filters) + f'[{track}]')
        labels.append(track)
        if cue.auto_duck and cue.background_gain < 1:
            gains.append(
                f'if(between(t,{delay:.9f},{delay+overlap:.9f}),'
                f'{cue.background_gain:g},1)')
    if not labels:
        return bed
    if bed:
        gain = '1'
        for part in gains:
            gain = f'min({gain},{part})'
        graph.append(
            f'[{bed}]aresample=48000,volume=\'{gain}\':eval=frame,'
            f'apad,atrim=duration={duration:.9f}[commentarybed]')
    else:
        graph.append(
            f'anullsrc=r=48000:cl=stereo,atrim=duration={duration:.9f}'
            '[commentarybed]')
    graph.append(
        '[commentarybed]' + ''.join(f'[{x}]' for x in labels) +
        f'amix=inputs={1+len(labels)}:normalize=0:duration=first:'
        f'dropout_transition=0,alimiter=limit=0.95:level=false:latency=true,'
        f'atrim=duration={duration:.9f}[commentarymix]')
    return 'commentarymix'
