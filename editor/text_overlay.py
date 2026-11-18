"""Plain-text overlay state, sizing, and safe drawtext resource handling."""
from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unicodedata

TEXT_SIZES = {'Small': .045, 'Medium': .065, 'Large': .09}
TEXT_POSITIONS = ('Top', 'Centre', 'Bottom')


@dataclass(frozen=True)
class Caption:
    start: float
    end: float
    text: str
    position: str = 'Bottom'
    style: object = None

    def validate(self):
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (self.start, self.end)):
            raise ValueError('Invalid caption time.')
        if not 0 <= self.start < self.end:
            raise ValueError('Caption end must follow its start.')
        TextOverlay(True, self.text, position=self.position).validate()
        if self.style is not None:
            from .typography import CaptionStyle, caption_layout
            if not isinstance(self.style, CaptionStyle):
                raise ValueError('Invalid caption style.')
            self.style.validate()
            caption_layout(1080, 1920, self.text, self.style)


@dataclass(frozen=True)
class TextOverlay:
    enabled: bool = False
    text: str = ''
    size: str = 'Medium'
    position: str = 'Bottom'
    captions: tuple[Caption, ...] = ()
    safe_area: bool = False

    @property
    def visible(self):
        return self.enabled or bool(self.captions)

    def validate(self):
        if type(self.safe_area) is not bool or len(self.captions) > 160:
            raise ValueError('Invalid caption settings or too many captions.')
        for caption in self.captions:
            if not isinstance(caption, Caption):
                raise ValueError('Invalid timed caption.')
            caption.validate()
        if type(self.enabled) is not bool or self.size not in TEXT_SIZES or self.position not in TEXT_POSITIONS:
            raise ValueError('Choose a valid text size and position.')
        if not isinstance(self.text, str):
            raise ValueError('Enter text for your overlay.')
        if not self.enabled:
            return
        if not self.text.strip():
            raise ValueError('Enter some text, or switch Text off.')
        if len(self.text) > 160 or self.text.count('\n') > 2:
            raise ValueError('Keep your text to 160 characters and three lines.')
        if any(unicodedata.category(c) in ('Cc', 'Cs') and c != '\n' for c in self.text):
            raise ValueError('Remove unsupported control characters from your text.')


def text_geometry(width, height, text):
    text.validate()
    margin = max(4, round(min(width, height)*(.10 if text.safe_area else .04)))
    # Conservative glyph bounds fit long lines without cropping their ends.
    def units(line):
        return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
                   for c in line)
    longest = max(1, *(units(line) for line in text.text.split('\n')))
    size = min(round(min(width, height)*TEXT_SIZES[text.size]),
               (width-2*margin)//longest,
               (height-2*margin)//(2*(text.text.count('\n')+1)))
    if size < 8:
        raise ValueError('Text is too long for this frame. Shorten it or add a line break.')
    y = {'Top': str(margin), 'Centre': '(h-text_h)/2', 'Bottom': f'h-text_h-{margin}'}[text.position]
    if text.safe_area:
        y = {'Top': str(round(height*.12)), 'Centre': '(h-text_h)/2',
             'Bottom': f'h-text_h-{round(height*.22)}'}[text.position]
    return size, margin, y


def resolve_font():
    fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for name in ('segoeui.ttf', 'arial.ttf', 'tahoma.ttf'):
        path = fonts / name
        if path.is_file():
            return path
    raise ValueError('A Windows text font is unavailable. Switch Text off or restore Segoe UI or Arial.')


def filter_path(path):
    """Escape the option parser, then the filtergraph parser; no shell involved."""
    value = Path(path).resolve().as_posix()
    value = ''.join('\\'+c if c in "\\':" else c for c in value)
    return ''.join('\\'+c if c in "\\'[],;" else c for c in value)


class TextResources:
    """Own UTF-8 text only for one preview/export; delete after FFmpeg exits."""
    def __init__(self, text, *, directory=None):
        self.temp = None
        self.font = self.path = None
        self.caption_paths = []
        text.validate()
        if text.visible:
            self.font = resolve_font()
            self.temp = TemporaryDirectory(prefix='pulse-text-', dir=directory)
            try:
                self.path = Path(self.temp.name) / 'overlay.txt'
                self.path.write_text(text.text, encoding='utf-8', newline='\n')
                for index, caption in enumerate(text.captions):
                    path = Path(self.temp.name) / f'caption-{index}.txt'
                    path.write_text(caption.text, encoding='utf-8', newline='\n')
                    self.caption_paths.append(path)
            except Exception:
                self.close()
                raise

    def close(self):
        if self.temp:
            self.temp.cleanup()
            self.temp = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _drawtext(width, height, text, resources, path):
    size, margin, y = text_geometry(width, height, text)
    if resources is None or not resources.path or not resources.path.is_file():
        raise ValueError('Text render resources are unavailable.')
    return (f'drawtext=fontfile={filter_path(resources.font)}:textfile={filter_path(path)}:'
            f'expansion=none:fontsize={size}:fontcolor=white:x=(w-text_w)/2:y={y}:'
            f'box=1:boxcolor=black@0.65:boxborderw={max(2, margin//3)}:line_spacing={max(2, size//4)}')


def caption_intervals(caption, trim, cuts):
    from .cuts import CutPlan
    intervals, elapsed = [], 0.0
    for segment in (cuts or CutPlan()).kept_segments(trim):
        start, end = max(segment.start, caption.start), min(segment.end, caption.end)
        if end > start:
            intervals.append((elapsed+start-segment.start, elapsed+end-segment.start))
        elapsed += segment.duration
    return intervals


def text_filter(width, height, text, resources, trim=None, cuts=None, source_position=None, bands=None):
    filters = []
    if text.enabled:
        if bands:
            from .typography import styled_filter, CaptionStyle
            filters.append(styled_filter(width,height,Caption(0,86400,text.text,text.position),
                           CaptionStyle(font_size=104,animation='none'),resources,[(0,86400)],source_position,bands))
        else:
            filters.append(_drawtext(width, height, text, resources, resources.path))
    if text.captions and (resources is None or len(resources.caption_paths) != len(text.captions)):
        raise ValueError('Caption resources are unavailable.')
    for caption, path in zip(text.captions, resources.caption_paths if resources else ()):
        if caption.style is not None or bands:
            from .typography import styled_filter, CaptionStyle
            style = caption.style or CaptionStyle(font_size=104)
            if source_position is not None:
                if caption.start <= source_position < caption.end:
                    filters.append(styled_filter(width, height, caption, style, resources,
                                   [(caption.start, caption.end)], source_position, bands))
            elif trim is not None:
                intervals = caption_intervals(caption, trim, cuts)
                if intervals:
                    filters.append(styled_filter(width, height, caption, style, resources, intervals, bands=bands))
            continue
        overlay = TextOverlay(True, caption.text, text.size, caption.position, safe_area=text.safe_area)
        draw = _drawtext(width, height, overlay, resources, path)
        if source_position is not None:
            if caption.start <= source_position < caption.end:
                filters.append(draw)
        elif trim is not None:
            intervals = caption_intervals(caption, trim, cuts)
            if intervals:
                enable = '+'.join(f'gte(t,{a:.9f})*lt(t,{b:.9f})' for a, b in intervals)
                filters.append(draw + f":enable='{enable}'")
    return ','.join(filters) or 'null'
