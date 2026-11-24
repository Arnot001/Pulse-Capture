"""Local photo/video cutaways on the edited output-time clock.

Media references are never moved, modified, copied, or uploaded. Imported videos
are deliberately muted in Phase A: the source recording's audio remains intact.
"""
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path

from capture.ffmpeg_backend import run
from .media import probe_media


PHOTO_EXTENSIONS = frozenset({'.png', '.jpg', '.jpeg', '.webp'})
VIDEO_EXTENSIONS = frozenset({'.mp4', '.mov', '.mkv', '.webm'})
LAYOUTS = ('Cutaway', 'Picture in picture')
MAX_CLIPS = 16
EPSILON = 0.0005


@dataclass(frozen=True)
class MediaClip:
    path: str
    kind: str
    start: float
    end: float
    source_in: float = 0.0
    source_duration: float = 0.0
    layout: str = 'Cutaway'
    x: float = 1.0  # Fraction of remaining horizontal travel, 0 = left
    y: float = 0.0  # Fraction of remaining vertical travel, 0 = top
    scale: float = 0.38  # Fraction of output width/height available to media
    source_width: int = 0
    source_height: int = 0

    @property
    def duration(self):
        return self.end - self.start

    @property
    def title(self):
        return Path(self.path).name

    def validate(self, total=None):
        if self.kind not in ('photo', 'video'):
            raise ValueError('Media clip must be a photo or video.')
        if self.layout not in LAYOUTS:
            raise ValueError('Choose Cutaway or Picture in picture.')
        if not isinstance(self.path, str) or not self.path:
            raise ValueError('Choose a local media file.')
        file = Path(self.path)
        allowed = PHOTO_EXTENSIONS if self.kind == 'photo' else VIDEO_EXTENSIONS
        if file.suffix.lower() not in allowed or not file.is_file():
            raise ValueError(f'Media file is missing or unsupported: {file.name}')
        for value in (self.start, self.end, self.source_in, self.source_duration):
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError('Media times must be finite numbers.')
        if self.start < 0 or self.end <= self.start + 0.01 - EPSILON:
            raise ValueError('Media clips need a positive duration of at least 0.01s.')
        if self.end > 86400 or (total is not None and self.end > total + EPSILON):
            raise ValueError('Media ends outside the edited output.')
        for name in ('x', 'y', 'scale'):
            value = getattr(self, name)
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError('Media placement must use finite numbers.')
        if not (0 <= self.x <= 1 and 0 <= self.y <= 1 and 0.05 <= self.scale <= 1):
            raise ValueError('Media position/size is outside the canvas.')
        if type(self.source_width) is not int or type(self.source_height) is not int or (
                self.source_width < 0 or self.source_height < 0 or
                bool(self.source_width) != bool(self.source_height)):
            raise ValueError('Invalid imported media dimensions.')
        if self.source_in < 0:
            raise ValueError('Source start cannot be negative.')
        if self.kind == 'photo' and self.source_in != 0:
            raise ValueError('Photos do not have a source start.')
        if self.kind == 'video':
            if self.source_duration <= 0:
                raise ValueError('Imported video has no valid duration.')
            if self.source_in + self.duration > self.source_duration + EPSILON:
                raise ValueError('Video duration exceeds the remaining imported footage.')


def validate_clips(clips, total=None):
    if len(clips) > MAX_CLIPS:
        raise ValueError(f'Use at most {MAX_CLIPS} imported media clips.')
    for clip in clips:
        if not isinstance(clip, MediaClip):
            raise ValueError('Invalid imported media clip.')
        clip.validate(total)


def create_clip(ffprobe, path, start, total, layout='Cutaway'):
    """Validate a chosen file with the existing FFprobe binary once on import."""
    file = Path(path).expanduser().resolve()
    ext = file.suffix.lower()
    if not file.is_file():
        raise ValueError('Selected media file does not exist.')
    source_width = source_height = 0
    if ext in PHOTO_EXTENSIONS:
        kind, source_duration = 'photo', 0.0
        result = run([str(ffprobe), '-v', 'error', '-select_streams', 'v:0',
                      '-show_entries', 'stream=width,height', '-of', 'json', str(file)], timeout=20)
        if result.returncode:
            raise ValueError('FFprobe could not read this image.')
        try:
            stream = json.loads(result.stdout)['streams'][0]
            source_width, source_height = int(stream['width']), int(stream['height'])
            if source_width < 2 or source_height < 2:
                raise ValueError('Image is too small.')
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError('Image has no readable pixels.') from exc
    elif ext in VIDEO_EXTENSIONS:
        kind = 'video'
        media = probe_media(ffprobe, file)
        source_duration = media.duration
        source_width, source_height = media.width, media.height
    else:
        raise ValueError('Choose a PNG, JPG, WEBP, MP4, MOV, MKV or WEBM file.')
    if not math.isfinite(float(start)) or not math.isfinite(float(total)) or total - start < 0.02:
        raise ValueError('Move the playhead earlier to leave room for this clip.')
    length = min(5.0, total - start, source_duration if kind == 'video' else total)
    clip = MediaClip(str(file), kind, float(start), float(start + length), 0.0, source_duration,
                     layout, source_width=source_width, source_height=source_height)
    clip.validate(total)
    return clip


@dataclass(frozen=True)
class MediaBounds:
    x: int
    y: int
    width: int
    height: int


def media_bounds(clip, width, height):
    """Pixel-exact rectangle for both canvas guides and exported FFmpeg geometry."""
    width, height = int(width), int(height)
    if width < 2 or height < 2:
        raise ValueError('Invalid output dimensions.')
    if clip.layout == 'Cutaway':
        return MediaBounds(0, 0, width, height)
    # Legacy clips without recorded dimensions use a 16:9 fallback.
    sw = clip.source_width or 16
    sh = clip.source_height or 9
    limit_w = max(2, int(width * clip.scale) // 2 * 2)
    limit_h = max(2, int(height * clip.scale) // 2 * 2)
    factor = min(limit_w / sw, limit_h / sh)
    w = min(width, max(2, int(sw * factor) // 2 * 2))
    h = min(height, max(2, int(sh * factor) // 2 * 2))
    x = round((width - w) * clip.x)
    y = round((height - h) * clip.y)
    return MediaBounds(x, y, w, h)


def with_media_position(clip, left, top, width, height):
    """Keep a proposed media rectangle in frame using normalized free space."""
    bounds = media_bounds(clip, width, height)
    x = max(0., min(1., left / max(1, width - bounds.width)))
    y = max(0., min(1., top / max(1, height - bounds.height)))
    return replace(clip, x=x, y=y)


def resized_media(clip, factor, left, top, width, height):
    """Aspect-locked resize from a fixed opposite corner, clamped to canvas."""
    candidate = replace(clip, layout='Picture in picture',
                        scale=max(0.05, min(1., clip.scale * factor)))
    return with_media_position(candidate, left, top, width, height)


def add_media(args, graph, input_label, clips, width, height, *, sample_time=None, offset=0.0):
    """Composite media over an existing FFmpeg video label; return its output label.

    sample_time: one-frame preview's absolute output time, or None for video.
    offset: output time at the start of a continuous-playback decoder segment.
    Every decoder uses source footage from the correct elapsed media time, even
    after trims, cuts, playback seeks and speed changes.
    """
    current = input_label
    for index, clip in enumerate(clips):
        if sample_time is not None:
            if not clip.start <= sample_time < clip.end:
                continue
            visible_from = sample_time
        else:
            if clip.end <= offset:
                continue
            visible_from = max(clip.start, offset)
        remaining = clip.end - visible_from
        if remaining <= 0:
            continue
        input_index = args.count('-i')
        if clip.kind == 'photo':
            args.extend(['-loop', '1', '-framerate', '30', '-t', f'{remaining:.9f}',
                         '-i', clip.path])
        else:
            seek = clip.source_in + (visible_from - clip.start)
            args.extend(['-ss', f'{seek:.9f}', '-t', f'{remaining:.9f}',
                         '-i', clip.path])
        w, h = int(width), int(height)
        placement = media_bounds(clip, w, h)
        if clip.layout == 'Cutaway':
            sizing = (f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                      f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black')
        else:
            # Exact pixel dimensions/placement also drive the selection handles.
            sizing = f'scale={placement.width}:{placement.height}:flags=bicubic'
        x, y = str(placement.x), str(placement.y)
        mark = f'mediain{index}'
        output = f'mediav{index}'
        pts = 0.0 if sample_time is not None else visible_from
        graph.append(f'[{input_index}:v:0]{sizing},format=rgba,'
                     f'trim=duration={remaining:.9f},setpts=PTS-STARTPTS+{pts:.9f}/TB[{mark}]')
        enable = '' if sample_time is not None else (
            f":enable='gte(t,{visible_from:.9f})*lt(t,{clip.end:.9f})'")
        graph.append(f'[{current}][{mark}]overlay=x={x}:y={y}:eof_action=pass:'
                     f'repeatlast=0:format=auto{enable}[{output}]')
        current = output
    return current
