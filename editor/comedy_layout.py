"""Safe, output-pixel caption/reaction bands outside full-frame landscape footage."""
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import unicodedata


@dataclass(frozen=True)
class Band:
    x: int
    y: int
    width: int
    height: int


def regions(source_size, width=1080, height=1920):
    if (not isinstance(source_size, (tuple,list)) or len(source_size)!=2 or
            any(type(n) is not int or not 2<=n<=100000 for n in source_size)):
        raise ValueError('Comedy Layout needs valid original landscape dimensions.')
    sw, sh = source_size
    if sw<=sh:
        raise ValueError('Comedy Layout needs landscape footage. Use Full Frame or Crop to Fill for portrait video.')
    scale = min(width/((sw+1)//2*2), height/((sh+1)//2*2))
    picture_h = int(((sh+1)//2*2)*scale)//2*2
    picture_y = (height-picture_h)//4*2
    margin, gap = round(width*.10), round(height*.018)
    top_y, bottom_end = round(height*.09), round(height*.82)
    bottom_y = picture_y+picture_h+gap
    result = {'top': Band(margin,top_y,width-2*margin,picture_y-gap-top_y),
              'bottom': Band(margin,bottom_y,width-2*margin,bottom_end-bottom_y)}
    if min(b.height for b in result.values()) < height*.06:
        raise ValueError('This footage leaves too little safe band space for Comedy Layout.')
    return result


@lru_cache(maxsize=1)
def advances():
    # Measured from the unmodified bundled DejaVu Sans Bold at 2048 px.
    # Runtime needs only the standard library; no font rasterizer dependency.
    return json.loads((Path(__file__).resolve().parent.parent/'assets'/'caption-advances.json').read_text(encoding='utf-8'))


def measure(text, size):
    return size*sum(0 if unicodedata.combining(c) else advances().get(c,1.2) for c in text)


def wrap(text, size, width):
    lines=[]
    for paragraph in text.split('\n'):
        line=''
        for word in paragraph.split():
            if line and measure(line+' '+word,size)>width:
                lines.append(line); line=''
            while measure(word,size)>width:
                take=1
                while take<len(word) and measure(word[:take+1],size)<=width:take+=1
                if measure(word[:take],size)>width:
                    raise ValueError('Caption glyph cannot fit in this band.')
                lines.append(word[:take]); word=word[take:]
            line=(line+' '+word).strip()
        if line:lines.append(line)
    return lines or ['']


def fit_caption(text, style, band, width=1080):
    """Shrink only as needed; reject captions that cannot remain mobile-readable."""
    factor=width/1080
    padding=math.ceil((style.outline+style.shadow+12)*factor)
    available=band.width*style.band_width-2*padding
    maximum=max(1,round(style.font_size*factor))
    minimum=min(maximum,max(12,round(64*factor)))
    for size in range(maximum,minimum-1,-1):
        lines=wrap(text,size,available)
        block_h=len(lines)*size*1.25
        if len(lines)<=3 and block_h+2*padding<=band.height:
            return size, lines, block_h, padding
    raise ValueError('Caption does not fit its comedy band at a readable size. Shorten it or split it into timed captions.')


def overlay_region(cue, bands, width, height):
    if cue.zone == 'canvas':
        return Band(0,0,width,height)
    if not bands:
        raise ValueError('Top/bottom band overlays require Comedy Layout.')
    return bands[cue.zone]


def overlay_size(cue, width, height, band):
    requested=max(16,round(min(width,height)*cue.scale))
    if cue.zone=='canvas':return requested
    # Rotation uses a diagonal-sized square; reserve animation travel as well.
    return min(requested,max(8,int(min(band.width,band.height)/(math.sqrt(2)+.3))))
