"""Immutable, UI-independent crop and optional branding settings."""
from dataclasses import dataclass, replace
import math
from pathlib import Path

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

    def validate(self, media):
        expected = centered_crop(media, self.preset)
        self.branding.validate()
        if expected is None:
            if self.crop is not None:
                raise ValueError('Original must keep the full frame.')
        else:
            if not isinstance(self.crop, Crop):
                raise ValueError('Choose a crop for this format.')
            self.crop.validate(media)
            if (self.crop.width, self.crop.height) != (expected.width, expected.height):
                raise ValueError('The crop does not match the selected format.')

    def with_format(self, media, preset):
        return replace(self, preset=preset, crop=centered_crop(media, preset))

    def output_size(self, media):
        self.validate(media)
        if self.crop:
            return self.crop.width, self.crop.height
        return (media.width+1)//2*2, (media.height+1)//2*2


def video_filters(media, edits, asset=None):
    """Crop, pad, then brand. Shared by export and the rendered preview."""
    edits.validate(media)
    filters = []
    if edits.crop:
        c = edits.crop
        filters.append(f'crop={c.width}:{c.height}:{c.x}:{c.y}')
    filters.append('pad=ceil(iw/2)*2:ceil(ih/2)*2')
    base = ','.join(filters)
    if not edits.branding.enabled:
        return base, False
    if asset is None or not Path(asset).is_file():
        raise ValueError('Pulse branding asset is missing. Turn branding off or reinstall Pulse Capture.')
    x, y, size = watermark_geometry(*edits.output_size(media), edits.branding)
    graph = (f'[0:v:0]{base}[base];'
             f'[1:v:0]scale={size}:{size},format=rgba,colorchannelmixer=aa=0.82[wm];'
             f'[base][wm]overlay={x}:{y}:eof_action=repeat:shortest=0:format=auto[v]')
    return graph, True
