"""Pure editor-polish state for zoom, speed, fades, and promo defaults."""
from dataclasses import dataclass
import math

ZOOM_FACTORS = (1.25, 1.5, 2.0)
SPEEDS = (0.5, 1.0, 1.5, 2.0)
FADE_SECONDS = 0.5


@dataclass(frozen=True)
class Zoom:
    enabled: bool = False
    factor: float = 1.5
    focus_x: float = 0.5
    focus_y: float = 0.5

    def validate(self):
        if type(self.enabled) is not bool or self.factor not in ZOOM_FACTORS:
            raise ValueError('Choose a valid zoom amount.')
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
    if speed not in SPEEDS:
        raise ValueError('Choose 0.5x, 1.0x, 1.5x, or 2.0x speed.')


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


def zoom_filter(media, crop, zoom):
    geometry = zoom_geometry(media, crop, zoom)
    if geometry is None:
        return None
    x, y, width, height, out_w, out_h = geometry
    return f'crop={width}:{height}:{x}:{y},scale={out_w}:{out_h}:flags=lanczos'
