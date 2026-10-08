"""Pure editing state and time input. No Tk or subprocess dependencies."""
from dataclasses import dataclass
import math
from pathlib import Path
import re


def parse_time(text):
    """Accept seconds, minutes:seconds, or hours:minutes:seconds."""
    text = str(text).strip()
    if not re.fullmatch(r'\d+(?::\d{1,2}){0,2}(?:\.\d{1,3})?', text):
        raise ValueError('Enter seconds or a time such as 1:23.500.')
    parts = [float(part) for part in text.split(':')]
    if any(part >= 60 for part in parts[1:]):
        raise ValueError('Minutes and seconds after a colon must be below 60.')
    value = 0.0
    for part in parts:
        value = value * 60 + part
    if not math.isfinite(value):
        raise ValueError('Enter a valid time.')
    return value


def format_time(seconds):
    milliseconds = max(0, round(seconds * 1000))
    whole, ms = divmod(milliseconds, 1000)
    minutes, secs = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}.{ms:03d}' if hours else f'{minutes}:{secs:02d}.{ms:03d}'


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool

    def validate(self):
        if not math.isfinite(self.duration) or self.duration <= 0:
            raise ValueError('This video has no usable duration.')
        if self.width < 2 or self.height < 2 or not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError('This video has invalid dimensions or frame rate.')


@dataclass(frozen=True)
class TrimRange:
    start: float
    end: float

    @property
    def duration(self):
        return self.end - self.start

    def validate(self, media):
        media.validate()
        if not all(math.isfinite(v) for v in (self.start, self.end)):
            raise ValueError('Start and End must be valid times.')
        if self.start < 0:
            raise ValueError('Start cannot be before the beginning of the video.')
        if self.end > media.duration + 0.0005:
            raise ValueError('End cannot be after the end of the video.')
        if self.end <= self.start:
            raise ValueError('End must be after Start.')
        if self.duration < min(1 / media.fps, media.duration) - 0.0005:
            raise ValueError('Keep at least one frame of video.')
