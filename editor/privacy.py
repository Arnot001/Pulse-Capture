"""Source-anchored rectangular privacy masks and shared viewport mapping."""
from dataclasses import dataclass, replace
from .models import TrimRange
from .cuts import CutPlan
import math

MODES = ('Blur', 'Pixelate')


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height

    def validate(self, width, height):
        if any(type(v) is not int for v in (self.x, self.y, self.width, self.height)):
            raise ValueError('Choose a valid privacy rectangle.')
        if self.width < 2 or self.height < 2:
            raise ValueError('Draw a privacy box at least two pixels wide and high.')
        if self.x < 0 or self.y < 0 or self.right > width or self.bottom > height:
            raise ValueError('Keep the privacy box inside your video.')

    def intersect(self, other):
        x, y = max(self.x, other.x), max(self.y, other.y)
        right, bottom = min(self.right, other.right), min(self.bottom, other.bottom)
        return Rect(x, y, right-x, bottom-y) if right > x and bottom > y else None

    def moved(self, bounds, x, y):
        if not all(math.isfinite(v) for v in (x, y)):
            raise ValueError('Choose a valid privacy position.')
        width, height = min(self.width, bounds.width), min(self.height, bounds.height)
        return Rect(round(max(bounds.x, min(x, bounds.right-width))),
                    round(max(bounds.y, min(y, bounds.bottom-height))), width, height)


def source_viewport(media, crop=None):
    return Rect(crop.x, crop.y, crop.width, crop.height) if crop else Rect(0, 0, media.width, media.height)


def output_mask(mask, media, crop=None):
    """Intersect in source space, then translate to cropped output space."""
    if mask is None:
        return None
    mask.validate(media.width, media.height)
    viewport = source_viewport(media, crop)
    visible = mask.intersect(viewport)
    return replace(visible, x=visible.x-viewport.x, y=visible.y-viewport.y) if visible else None


def rectangle_from_points(bounds, x1, y1, x2, y2):
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
        raise ValueError('Choose a valid privacy rectangle.')
    x1, x2 = sorted(round(max(bounds.x, min(v, bounds.right))) for v in (x1, x2))
    y1, y2 = sorted(round(max(bounds.y, min(v, bounds.bottom))) for v in (y1, y2))
    if x2-x1 < 2 or y2-y1 < 2:
        return None
    return Rect(x1, y1, x2-x1, y2-y1)


@dataclass(frozen=True)
class PrivacyMask:
    mode: str
    rect: Rect
    start: float
    end: float

    def validate(self, media):
        media.validate()
        if self.mode not in MODES:
            raise ValueError('Choose Blur or Pixelate.')
        if not isinstance(self.rect, Rect):
            raise ValueError('Draw a privacy rectangle first.')
        self.rect.validate(media.width, media.height)
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (self.start, self.end)):
            raise ValueError('Choose valid privacy Start and End times.')
        if self.start < 0 or self.end > media.duration:
            raise ValueError('Keep privacy times inside the source video.')
        if self.end <= self.start:
            raise ValueError('Privacy End must be after Start.')
        if self.end-self.start < min(1/media.fps, media.duration)-0.0005:
            raise ValueError('Keep privacy active for at least one frame.')

    def active(self, position):
        # Half-open intervals avoid an extra protected frame after End.
        return self.start <= position < self.end


@dataclass(frozen=True)
class Privacy:
    # Deliberate insertion order also defines deterministic overlap rendering.
    masks: tuple[PrivacyMask, ...] = ()

    def validate(self, media):
        if not isinstance(self.masks, tuple):
            raise ValueError('Choose a valid privacy mask collection.')
        for mask in self.masks:
            if not isinstance(mask, PrivacyMask):
                raise ValueError('Choose a valid privacy mask.')
            mask.validate(media)

    def active_masks(self, position):
        return tuple(mask for mask in self.masks if mask.active(position))


def mask_intervals(mask, trim, cuts=None, speed=1.0):
    """Source interval -> kept timeline. Privacy filters use speed=1 (pre-speed).

    Passing clip speed explicitly yields final-output intervals for consumers.
    Keep pieces separate and in source order, including adjacent joined pieces.
    """
    from .polish import validate_speed
    validate_speed(speed)
    elapsed = 0.0
    intervals = []
    for segment in (cuts or CutPlan()).kept_segments(trim):
        start, end = max(mask.start, segment.start), min(mask.end, segment.end)
        if end > start:
            intervals.append(TrimRange((elapsed+start-segment.start)/speed,
                                       (elapsed+end-segment.start)/speed))
        elapsed += segment.duration
    return tuple(intervals)


def privacy_filters(rect, mode, input_label="base", output_label="private", enable=None):
    """Exact pixel placement, including odd offsets and clipped one-pixel edges."""
    crop = f'crop={rect.width}:{rect.height}:{rect.x}:{rect.y}:exact=1'
    if mode == 'Blur':
        effect = 'gblur=sigma=18:steps=3'
    elif mode == 'Pixelate':
        effect = (f'scale={max(1, rect.width//18)}:{max(1, rect.height//18)}:flags=area,'
                  f'scale={rect.width}:{rect.height}:flags=neighbor')
    else:
        raise ValueError('Choose Blur or Pixelate.')
    back, region, hidden = (output_label + suffix for suffix in ('_back', '_region', '_hidden'))
    timing = f":enable='{enable}'" if enable is not None else ''
    return [
        f'[{input_label}]format=yuv444p,split[{back}][{region}]',
        f'[{region}]{crop},{effect}[{hidden}]',
        f'[{back}][{hidden}]overlay={rect.x}:{rect.y}:format=yuv444:shortest=1{timing}[{output_label}]',
    ]
