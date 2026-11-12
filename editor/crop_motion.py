"""Source-time crop keyframes for a smoothly moving YouTube Shorts frame.

Keyframes stay in original video time, so trimming and removing sections do not
change their meaning. All geometry is in even source pixels for H.264/yuv420p.
"""
from dataclasses import dataclass
import math


MAX_CROP_KEYFRAMES = 64


@dataclass(frozen=True)
class CropKeyframe:
    time: float
    x: int
    y: int


@dataclass(frozen=True)
class CropMotion:
    keyframes: tuple[CropKeyframe, ...] = ()

    def validate(self, media, crop):
        if not self.keyframes:
            return
        if crop is None:
            raise ValueError('Select YouTube Shorts before adding crop keyframes.')
        if len(self.keyframes) > MAX_CROP_KEYFRAMES:
            raise ValueError(f'Use no more than {MAX_CROP_KEYFRAMES} crop keyframes.')
        previous = -1.0
        for key in self.keyframes:
            if not isinstance(key, CropKeyframe) or not isinstance(key.time, (int, float)):
                raise ValueError('Invalid crop keyframe.')
            if not math.isfinite(key.time) or not (0 <= key.time <= media.duration + 0.0005):
                raise ValueError('Keep crop keyframes inside your video.')
            if key.time <= previous + 1e-8:
                raise ValueError('Crop keyframes must have distinct, increasing times.')
            if any(type(v) is not int or v < 0 or v % 2 for v in (key.x, key.y)):
                raise ValueError('Crop keyframe positions must be even source pixels.')
            if key.x + crop.width > media.width or key.y + crop.height > media.height:
                raise ValueError('Keep each crop keyframe inside your video.')
            previous = key.time

    def sample(self, media, crop, time):
        """Interpolate at a source timestamp; snap to even pixels like FFmpeg."""
        if not self.keyframes:
            return crop
        self.validate(media, crop)
        if not isinstance(time, (int, float)) or not math.isfinite(time):
            raise ValueError('Choose a valid crop preview time.')
        keys = self.keyframes
        if time <= keys[0].time:
            return crop.moved(media, keys[0].x, keys[0].y)
        for left, right in zip(keys, keys[1:]):
            if time <= right.time:
                part = (time - left.time) / (right.time - left.time)
                # Round to the nearest chroma-aligned coordinate.
                x = math.floor((left.x + (right.x-left.x)*part+1) / 2) * 2
                y = math.floor((left.y + (right.y-left.y)*part+1) / 2) * 2
                return crop.moved(media, x, y)
        return crop.moved(media, keys[-1].x, keys[-1].y)

    def at(self, media, crop, time):
        """Create or replace a keyframe at the nearest source frame."""
        if not isinstance(time, (int, float)) or not math.isfinite(time):
            raise ValueError('Choose a valid keyframe time.')
        media.validate()
        crop.validate(media)
        if not (0 <= time <= media.duration + 0.0005):
            raise ValueError('Keep crop keyframes inside your video.')
        snapped = min(media.duration, round(time * media.fps) / media.fps)
        snap_margin = .50001 / media.fps
        items = list(self.keyframes)
        for index, key in enumerate(items):
            if abs(key.time-snapped) <= snap_margin:
                items[index] = CropKeyframe(key.time, crop.x, crop.y)
                updated = CropMotion(tuple(items))
                updated.validate(media, crop)
                return updated
        items.append(CropKeyframe(snapped, crop.x, crop.y))
        items.sort(key=lambda item: item.time)
        updated = CropMotion(tuple(items))
        updated.validate(media, crop)
        return updated

    def remove_at(self, media, crop, time):
        margin = .50001 / media.fps
        items = tuple(key for key in self.keyframes if abs(key.time-time) > margin)
        if len(items) == len(self.keyframes):
            raise ValueError('Move to a saved crop keyframe before deleting it.')
        updated = CropMotion(items)
        updated.validate(media, crop)
        return updated


def motion_crop_filter(crop, motion, time_offset=0, source_position=None):
    """Build one FFmpeg crop filter. Source-time interpolation uses t on export.

    The input PTS starts at zero after input-side -ss. An explicit offset maps
    that local time back onto the saved source-time keyframes. With CUT, this
    filter is applied before trim/concat, so source timestamps need no offset.
    """
    if source_position is not None:
        raise ValueError('Render preview crops using CropMotion.sample instead.')
    if not motion.keyframes:
        return f'crop={crop.width}:{crop.height}:{crop.x}:{crop.y}'

    def formula(axis):
        frames = motion.keyframes
        base = getattr(frames[0], axis)
        terms = [str(base)]
        for a, b in zip(frames, frames[1:]):
            change = getattr(b, axis) - getattr(a, axis)
            if change:
                # clip() clamps each segment to [0, 1] and preserves the
                # exact positions before the first and after the last key.
                progress = f'clip((t+{time_offset:.9f}-{a.time:.9f})/{b.time-a.time:.9f},0,1)'
                terms.append(f'({change})*{progress}')
        # Match even-pixel preview rounding; never leave the source frame.
        return 'trunc((' + '+'.join(terms) + '+1)/2)*2'

    return (f"crop={crop.width}:{crop.height}:"
            f"x='{formula('x')}':y='{formula('y')}'")
