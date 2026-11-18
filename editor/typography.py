"""Bundled-font ASS captions: identical layout/animation in preview and export."""
from dataclasses import dataclass
from pathlib import Path
import re
import textwrap
from .reactions import finite

FONT_DIR = Path(__file__).resolve().parent.parent/'assets'/'fonts'
THEMES = ('Comedy Bold', 'Cinematic', 'Meme / Reaction', 'Clean News')


@dataclass(frozen=True)
class CaptionStyle:
    theme: str = 'Comedy Bold'
    font_size: int = 88
    outline: int = 5
    shadow: int = 3
    colour: str = '#FFFFFF'
    highlight: str = ''
    highlight_colour: str = '#FFD83D'
    alignment: str = 'centre'
    animation: str = 'pop'
    band_width: float = 1
    band_y: float = .5

    def validate(self):
        if self.theme not in THEMES or self.alignment not in ('left', 'centre', 'right') or self.animation not in ('none','fade','pop','shake'):
            raise ValueError('Unsupported caption theme, alignment or animation.')
        for value, low, high in ((self.font_size,40,120),(self.outline,0,10),(self.shadow,0,10)):
            if type(value) is not int:
                raise ValueError('Caption sizes must use whole pixels.')
            finite(value,low,high,'Caption size')
        for colour in (self.colour, self.highlight_colour):
            if type(colour) is not str or not re.fullmatch('#[0-9a-fA-F]{6}',colour):
                raise ValueError('Caption colours must be #RRGGBB.')
        if type(self.highlight) is not str or len(self.highlight)>80 or any(ord(c)<32 or c in '{}\\' for c in self.highlight):
            raise ValueError('Highlight must be a plain phrase of at most 80 characters.')
        finite(self.band_width, .3, 1, 'Caption band width')
        finite(self.band_y, 0, 1, 'Caption position within band')


def theme_style(theme):
    if theme == 'Cinematic':
        return CaptionStyle(theme,80,3,2,animation='fade')
    if theme == 'Clean News':
        return CaptionStyle(theme,76,3,2,animation='none')
    if theme == 'Meme / Reaction':
        return CaptionStyle(theme,96,6,3,animation='shake')
    return CaptionStyle()


def ass_colour(colour):
    return '&H'+colour[5:7]+colour[3:5]+colour[1:3]+'&'


def ass_time(value):
    cs = round(value*100)
    return f'{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'


def literal(value):
    # ASS treats these characters as markup even when passed through a file.
    return value.replace('\\','＼').replace('{','｛').replace('}','｝')


def caption_layout(width, height, text, style):
    style.validate()
    if style.highlight and style.highlight not in text:
        raise ValueError('Caption highlight must occur in its text.')
    factor = min(width,height)/1080
    size = max(12,round(style.font_size*factor))
    usable = width*.78
    # Wrap before reducing size; reserve room for the pop/shake and outline.
    columns = max(4,int(usable/(size*.72)))
    lines = []
    for line in text.split('\n'):
        lines.extend(textwrap.wrap(line,columns,break_long_words=True) or [''])
    while len(lines)>3 and size>max(12,round(48*factor)):
        size -= 1
        columns = max(4,int(usable/(size*.72)))
        lines = textwrap.wrap(' '.join(text.split()),columns) or ['']
    if len(lines)>3:
        raise ValueError('Caption is too long for a readable safe area; shorten it.')
    return size, lines


def styled_filter(width, height, caption, style, resources, intervals, sample_time=None, bands=None):
    from .text_overlay import filter_path
    size, lines = caption_layout(width, height, caption.text, style)
    factor = min(width,height)/1080
    rendered = r'\N'.join(literal(line) for line in lines)
    if style.highlight:
        # Highlight each word of a phrase even when the safe-area wrap splits it.
        phrase = [literal(word) for word in style.highlight.split()]
        pattern = r'(?:\s|\\N)+'.join(re.escape(word) for word in phrase)
        rendered = re.sub(pattern, lambda match: r'{\c'+ass_colour(style.highlight_colour)+'}'+match[0]+r'{\c'+ass_colour(style.colour)+'}', rendered)
    align = {'left':1,'centre':2,'right':3}[style.alignment]
    x = {'left':width*.11,'centre':width*.5,'right':width*.89}[style.alignment]
    y = height*.12 if caption.position=='Top' else height*.78 if caption.position=='Bottom' else height*.5
    anchor = align+6 if caption.position=='Top' else align if caption.position=='Bottom' else align+3
    clip = ''
    if bands:
        from .comedy_layout import fit_caption
        if caption.position not in ('Top','Bottom'):
            raise ValueError('Comedy Layout captions must use the Top or Bottom band.')
        band = bands[caption.position.lower()]
        size, lines, block_h, padding = fit_caption(caption.text, style, band, width)
        rendered = r'\N'.join(literal(line) for line in lines)
        if style.highlight:
            rendered = re.sub(pattern, lambda match: r'{\c'+ass_colour(style.highlight_colour)+'}'+match[0]+r'{\c'+ass_colour(style.colour)+'}', rendered)
        x = {'left':band.x+padding, 'centre':band.x+band.width/2,
             'right':band.x+band.width-padding}[style.alignment]
        y = band.y+padding+(band.height-2*padding-block_h)*style.band_y+block_h/2
        anchor = align+3
        clip = f'\\clip({band.x},{band.y},{band.x+band.width},{band.y+band.height})'
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Pulse,DejaVu Sans,{size},{ass_colour(style.colour)},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,{90 if style.theme in ('Cinematic','Clean News') else 100},100,0,0,1,{style.outline*factor},{style.shadow*factor},{anchor},0,0,0,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
'''
    events = []
    for start,end in intervals:
        tags = f'\\an{anchor}\\pos({x:.2f},{y:.2f})'+clip
        if style.animation=='pop':
            tags += r'\fscx75\fscy75\t(0,120,\fscx100\fscy100)'
        elif style.animation=='fade':
            tags += r'\fad(120,120)'
        elif style.animation=='shake':
            # Bounded impact jitter, then a steady hold.
            for i in range(6):
                a,b=start+i*.025,min(end,start+(i+1)*.025)
                if a<b:
                    jitter = (-1 if i%2 else 1)*width*.006
                    events.append(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Pulse,,0,0,0,,{{\\an{anchor}\\pos({x+jitter:.2f},{y:.2f}){clip}}}{rendered}')
            start = min(end,start+.15)
        if end>start:
            events.append(f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Pulse,,0,0,0,,{{{tags}}}{rendered}')
    path = Path(resources.temp.name)/f'style-{len(list(Path(resources.temp.name).glob("style-*.ass")))}.ass'
    path.write_text(header+'\n'.join(events)+'\n', encoding='utf-8')
    draw = f'ass=filename={filter_path(path)}:fontsdir={filter_path(FONT_DIR)}'
    if sample_time is not None:
        draw = f'setpts={sample_time:.9f}/TB,{draw},setpts=PTS-STARTPTS'
    return draw
