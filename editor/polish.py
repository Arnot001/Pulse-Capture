"""Pure editor-polish state for zoom, speed, fades, and promo defaults."""
from dataclasses import dataclass
import math

ZOOM_FACTORS = (1.25, 1.5, 2.0)
SPEEDS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
ZOOM_MODES = ('Static', 'Zoom in')
ZOOM_TIMINGS = {'Fast': .6, 'Medium': 1.5, 'Slow': 3.5, 'Full clip': None}
FADE_SECONDS = 0.5


@dataclass(frozen=True)
class Zoom:
    enabled: bool = False
    factor: float = 1.5
    focus_x: float = 0.5
    focus_y: float = 0.5
    mode: str = 'Static'
    motion_speed: str = 'Medium'

    def validate(self):
        if type(self.enabled) is not bool or self.factor not in ZOOM_FACTORS:
            raise ValueError('Choose a valid zoom amount.')
        if self.mode not in ZOOM_MODES or self.motion_speed not in ZOOM_TIMINGS:
            raise ValueError('Choose Static or Zoom In and a zoom motion speed.')
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1
                   for v in (self.focus_x, self.focus_y)):
            raise ValueError('Choose a zoom focus inside the video.')


@dataclass(frozen=True)
class Fade:
    fade_in: bool = False
    fade_out: bool = False

    def validate(self):
        if type(self.fade_in) is not bool or type(self.fade_out) is not bool:
            raise ValueError('Choose valid fade options.')


def validate_speed(speed):
    if isinstance(speed, bool) or speed not in SPEEDS:
        raise ValueError('Choose 0.5x, 1x, 1.5x, 2x, 3x, or 4x clip speed.')


def output_duration(source_duration, speed):
    validate_speed(speed)
    if not isinstance(source_duration, (int, float)) or not math.isfinite(source_duration) or source_duration <= 0:
        raise ValueError('The selected clip has no usable duration.')
    return source_duration / speed


def fade_seconds(duration):
    """Keep fades short and non-overlapping on tiny clips."""
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('The selected clip has no usable duration.')
    return min(FADE_SECONDS, duration / 2)


def _even_floor(value):
    return max(2, int(value) // 2 * 2)


def zoom_geometry(media, crop, zoom):
    """Return post-format crop geometry used for a static punch-in."""
    zoom.validate()
    if not zoom.enabled:
        return None
    base_x = crop.x if crop else 0
    base_y = crop.y if crop else 0
    base_w = crop.width if crop else (media.width + 1) // 2 * 2
    base_h = crop.height if crop else (media.height + 1) // 2 * 2
    width = min(base_w, _even_floor(base_w / zoom.factor))
    height = min(base_h, _even_floor(base_h / zoom.factor))

    source_x = zoom.focus_x * media.width
    source_y = zoom.focus_y * media.height
    focus_x = max(0, min(base_w, source_x - base_x))
    focus_y = max(0, min(base_h, source_y - base_y))

    max_x, max_y = base_w - width, base_h - height
    x = max(0, min(max_x, round((focus_x - width / 2) / 2) * 2))
    y = max(0, min(max_y, round((focus_y - height / 2) / 2) * 2))
    return int(x), int(y), int(width), int(height), int(base_w), int(base_h)


def zoom_filter(media, crop, zoom, speed=1.0, duration=None, preview_time=None):
    geometry = zoom_geometry(media, crop, zoom)
    if geometry is None:
        return None
    if zoom.mode == 'Zoom in':
        seconds = animation_duration(zoom, media.duration if duration is None else duration, speed, media.fps)
        clock = f'in_time/{speed:g}' if preview_time is None else f'{max(0, preview_time):.9f}'
        p = f'min(1,max(0,({clock})/{seconds:.9f}))'
        factor = f'1+{zoom.factor-1:g}*({p})*({p})*(3-2*({p}))'
        out_w, out_h = geometry[-2:]
        focus_x = zoom.focus_x * media.width - (crop.x if crop else 0)
        focus_y = zoom.focus_y * media.height - (crop.y if crop else 0)
        x = f'min(max({focus_x:.9f}-iw/zoom/2,0),iw-iw/zoom)'
        y = f'min(max({focus_y:.9f}-ih/zoom/2,0),ih-ih/zoom)'
        # One zoompan frame per input frame. Normalize VFR before assigning CFR
        # timestamps; speed conversion still follows text and branding.
        normalize = f'setpts=PTS-STARTPTS,fps={media.fps:.9f},' if preview_time is None else ''
        return (normalize + f"format=yuv444p,zoompan=z='{factor}':x='{x}':y='{y}':"
                f'd=1:s={out_w}x{out_h}:fps={media.fps:.9f},setsar=1')
    x, y, width, height, out_w, out_h = geometry
    return f'crop={width}:{height}:{x}:{y},scale={out_w}:{out_h}:flags=lanczos'


def audio_tempo_filters(speed):
    """Pitch-preserving stages, each within atempo's conservative .5..2 range."""
    validate_speed(speed)
    if speed == 1:
        return []
    if speed > 2:
        return [f'atempo={speed/2:g}', 'atempo=2']
    return [f'atempo={speed:g}']


def animation_duration(zoom, source_duration, speed, fps):
    zoom.validate()
    duration = output_duration(source_duration, speed)
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('This video has no valid frame rate.')
    if zoom.motion_speed == 'Full clip':
        # Use the exact output duration: never subtract a frame or cap to a preset.
        return duration
    # Finish by the last displayed output frame where possible. A one-frame
    # clip safely shows the initial framing; it cannot display a whole motion.
    return min(ZOOM_TIMINGS[zoom.motion_speed], max(1/fps, duration-1/fps))


def animation_progress(output_time, seconds):
    if not math.isfinite(output_time) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Choose valid zoom timing.')
    p = max(0.0, min(1.0, output_time / seconds))
    return p*p*(3-2*p)


def animated_geometry(media, crop, zoom, output_time, source_duration, speed):
    """Ideal floating-point viewport; zoompan quantizes to input pixels."""
    zoom.validate()
    seconds = animation_duration(zoom, source_duration, speed, media.fps)
    factor = 1 + (zoom.factor-1)*animation_progress(output_time, seconds)
    base_w, base_h = zoom_geometry(media, crop, zoom)[-2:]
    width, height = base_w/factor, base_h/factor
    x = zoom.focus_x*media.width - (crop.x if crop else 0) - width/2
    y = zoom.focus_y*media.height - (crop.y if crop else 0) - height/2
    return max(0, min(base_w-width, x)), max(0, min(base_h-height, y)), width, height, base_w, base_h
