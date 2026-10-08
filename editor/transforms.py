"""Immutable, UI-independent crop and optional branding settings."""
from dataclasses import dataclass, replace
import math
from pathlib import Path
from .privacy import Privacy, output_mask, privacy_filters
from .text_overlay import TextOverlay, text_geometry, text_filter
from .polish import Fade, Zoom, fade_seconds, output_duration, validate_speed, zoom_filter

FORMATS = {'Original': None, '16:9 Landscape': (16, 9),
           '9:16 Vertical': (9, 16), '1:1 Square': (1, 1)}
CORNERS = ('Top left', 'Top right', 'Bottom left', 'Bottom right')
SIZES = {'Small': .12, 'Medium': .18, 'Large': .25}


@dataclass(frozen=True)
class Crop:
    x: int
    y: int
    width: int
    height: int

    def validate(self, media):
        values = (self.x, self.y, self.width, self.height)
        if any(type(v) is not int for v in values):
            raise ValueError('Crop dimensions must be whole pixels.')
        if self.width < 2 or self.height < 2 or any(v % 2 for v in values):
            raise ValueError('Crop dimensions and position must use even pixels.')
        if self.x < 0 or self.y < 0 or self.x + self.width > media.width or self.y + self.height > media.height:
            raise ValueError('Keep the crop inside your video.')

    def moved(self, media, x, y):
        self.validate(media)
        if not all(math.isfinite(v) for v in (x, y)):
            raise ValueError('Choose a valid crop position.')
        def clamp(value, limit):
            return min(limit // 2 * 2, max(0, round(value / 2) * 2))
        return replace(self, x=clamp(x, media.width-self.width),
                       y=clamp(y, media.height-self.height))


def centered_crop(media, preset):
    media.validate()
    if preset not in FORMATS:
        raise ValueError('Choose Original, Landscape, Vertical, or Square.')
    ratio = FORMATS[preset]
    if ratio is None:
        return None
    # Exact aspect ratio, even dimensions, no upscaling or stretching.
    unit_w, unit_h = ratio[0] * 2, ratio[1] * 2
    multiple = min(media.width // unit_w, media.height // unit_h)
    if multiple < 1:
        raise ValueError('This video is too small for that format. Choose Original.')
    width, height = unit_w * multiple, unit_h * multiple
    return Crop((media.width-width)//4*2, (media.height-height)//4*2, width, height)


@dataclass(frozen=True)
class Branding:
    enabled: bool = False
    position: str = 'Bottom right'
    size: str = 'Small'

    def validate(self):
        if type(self.enabled) is not bool or self.position not in CORNERS or self.size not in SIZES:
            raise ValueError('Choose a valid watermark corner and size.')


def watermark_geometry(width, height, branding):
    """Square Pulse asset sized relative to the shorter output edge."""
    branding.validate()
    edge = min(width, height)
    size = max(1, round(edge * SIZES[branding.size]))
    margin = min(max(1, round(edge * .025)), max(0, (edge-size)//2))
    x = margin if 'left' in branding.position else width-size-margin
    y = margin if 'Top' in branding.position else height-size-margin
    return x, y, size


@dataclass(frozen=True)
class EditOptions:
    preset: str = 'Original'
    crop: Crop | None = None
    branding: Branding = Branding()
    text: TextOverlay = TextOverlay()
    privacy: Privacy = Privacy()
    zoom: Zoom = Zoom()
    speed: float = 1.0
    fade: Fade = Fade()

    def validate(self, media):
        expected = centered_crop(media, self.preset)
        self.branding.validate()
        self.text.validate()
        self.privacy.validate(media)
        self.zoom.validate()
        validate_speed(self.speed)
        self.fade.validate()
        if expected is None:
            if self.crop is not None:
                raise ValueError('Original must keep the full frame.')
        else:
            if not isinstance(self.crop, Crop):
                raise ValueError('Choose a crop for this format.')
            self.crop.validate(media)
            if (self.crop.width, self.crop.height) != (expected.width, expected.height):
                raise ValueError('The crop does not match the selected format.')

        if self.text.enabled:
            width, height = (self.crop.width, self.crop.height) if self.crop else (media.width, media.height)
            text_geometry(width, height, self.text)

    def with_format(self, media, preset):
        return replace(self, preset=preset, crop=centered_crop(media, preset))

    def output_size(self, media):
        self.validate(media)
        if self.crop:
            return self.crop.width, self.crop.height
        return (media.width+1)//2*2, (media.height+1)//2*2

    def output_duration(self, source_duration):
        return output_duration(source_duration, self.speed)


def video_filters(media, edits, asset=None, text_resources=None, duration=None):
    """Crop, privacy, zoom, overlays, timing and fades. Preview omits timing effects."""
    edits.validate(media)
    filters = []
    if edits.crop:
        c = edits.crop
        filters.append(f'crop={c.width}:{c.height}:{c.x}:{c.y}')
    filters.append('pad=ceil(iw/2)*2:ceil(ih/2)*2')
    base = ','.join(filters)
    rect = output_mask(edits.privacy.mask, media, edits.crop)
    timed = duration is not None and (
        edits.speed != 1.0 or edits.fade.fade_in or edits.fade.fade_out
    )
    if not (rect or edits.zoom.enabled or edits.text.enabled or edits.branding.enabled or timed):
        return base, False

    graph = [f'[0:v:0]{base}[base]']
    current = 'base'
    if rect:
        graph.extend(privacy_filters(rect, edits.privacy.mode))
        current = 'private'

    zoom = zoom_filter(media, edits.crop, edits.zoom)
    if zoom:
        graph.append(f'[{current}]{zoom}[zoomed]')
        current = 'zoomed'

    width, height = edits.output_size(media)
    if edits.text.enabled:
        graph.append(f'[{current}]{text_filter(width, height, edits.text, text_resources)}[text]')
        current = 'text'

    if edits.branding.enabled:
        if asset is None or not Path(asset).is_file():
            raise ValueError('Pulse branding asset is missing. Turn branding off or reinstall Pulse Capture.')
        x, y, size = watermark_geometry(width, height, edits.branding)
        graph.extend([
            f'[1:v:0]scale={size}:{size},format=rgba,colorchannelmixer=aa=0.82[wm]',
            f'[{current}][wm]overlay={x}:{y}:eof_action=repeat:shortest=0:format=auto[brand]'
        ])
        current = 'brand'

    if duration is not None:
        if edits.speed != 1.0:
            graph.append(f'[{current}]setpts=PTS/{edits.speed:g}[speed]')
            current = 'speed'
        out_duration = edits.output_duration(duration)
        fade = fade_seconds(out_duration)
        fades = []
        if edits.fade.fade_in:
            fades.append(f'fade=t=in:st=0:d={fade:.6f}')
        if edits.fade.fade_out:
            fades.append(f'fade=t=out:st={max(0, out_duration-fade):.6f}:d={fade:.6f}')
        if fades:
            graph.append(f'[{current}]{",".join(fades)}[faded]')
            current = 'faded'

    graph.append(f'[{current}]null[v]')
    return ';'.join(graph), True
