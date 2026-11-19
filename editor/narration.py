"""Dedicated output-clock narration cue, independent of <=20-second sound effects."""
from dataclasses import dataclass
import math
from pathlib import Path

from .ai_voiceover import library_root, valid_wav


@dataclass(frozen=True)
class Narration:
    file: str
    start: float = 0.0
    volume: float = 1.0
    background_gain: float = 0.35

    def validate(self, duration=None):
        path = Path(self.file).resolve()
        root = library_root().resolve()
        if path.parent != root or path.suffix.lower() != ".wav" or not path.is_file():
            raise ValueError("Narration must be a saved WAV from the Pulse voiceover library.")
        length = valid_wav(path)
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in
               (self.start, self.volume, self.background_gain)):
            raise ValueError("Narration settings must be finite numbers.")
        if not 0 <= self.start < 86400 or not 0 <= self.volume <= 2 or not 0 <= self.background_gain <= 1:
            raise ValueError("Narration start or volume is invalid.")
        if duration is not None and self.start >= duration:
            raise ValueError("Narration begins after the end of the video.")
        return length


def add_narration(inputs, graph, base_label, cue, duration, offset=0.0):
    """Compile narration and gentle background ducking after source/music/SFX mixing.

    inputs is the FFmpeg input-argument list (or dummy '-i' tokens for an
    export), and the returned label can be mapped by preview or export.
    """
    length = cue.validate()
    if cue.start >= duration + offset or cue.start + length <= offset:
        return base_label
    remaining = min(cue.start + length, duration + offset) - max(cue.start, offset)
    skipped = max(0., offset - cue.start)
    delay = max(0., cue.start - offset)
    index = inputs.count("-i")
    inputs.extend(["-i", str(Path(cue.file).resolve())])
    graph.append(
        f"[{index}:a:0]aresample=48000,atrim=start={skipped:.9f}:"
        f"end={skipped+remaining:.9f},asetpts=PTS-STARTPTS,"
        f"volume={cue.volume:g},adelay={round(delay*48000)}S:all=1[narrationtrack]"
    )
    if base_label:
        graph.append(f"[{base_label}]aresample=48000,"
                     f"volume='if(between(t,{delay:.9f},{delay+remaining:.9f}),"
                     f"{cue.background_gain:g},1)':eval=frame,"
                     f"apad,atrim=duration={duration:.9f}[narrationbed]")
    else:
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.9f}[narrationbed]")
    graph.append(
        "[narrationbed][narrationtrack]"
        f"amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        f"alimiter=limit=0.95:level=false:latency=true,"
        f"atrim=duration={duration:.9f}[narrationmix]"
    )
    return "narrationmix"
