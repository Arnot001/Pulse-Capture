"""Plain-text overlay state, sizing, and safe drawtext resource handling."""
from dataclasses import dataclass
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unicodedata

TEXT_SIZES = {'Small': .045, 'Medium': .065, 'Large': .09}
TEXT_POSITIONS = ('Top', 'Centre', 'Bottom')


@dataclass(frozen=True)
class TextOverlay:
    enabled: bool = False
    text: str = ''
    size: str = 'Medium'
    position: str = 'Bottom'

    def validate(self):
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
    margin = max(4, round(min(width, height)*.04))
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
        text.validate()
        if text.enabled:
            self.font = resolve_font()
            self.temp = TemporaryDirectory(prefix='pulse-text-', dir=directory)
            try:
                self.path = Path(self.temp.name) / 'overlay.txt'
                self.path.write_text(text.text, encoding='utf-8', newline='\n')
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


def text_filter(width, height, text, resources):
    size, margin, y = text_geometry(width, height, text)
    if resources is None or not resources.path or not resources.path.is_file():
        raise ValueError('Text render resources are unavailable.')
    return (f'drawtext=fontfile={filter_path(resources.font)}:textfile={filter_path(resources.path)}:'
            f'expansion=none:fontsize={size}:fontcolor=white:x=(w-text_w)/2:y={y}:'
            f'box=1:boxcolor=black@0.65:boxborderw={max(2, margin//3)}:line_spacing={max(2, size//4)}')
